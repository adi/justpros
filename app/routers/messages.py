import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.db import database
from app.storage import get_avatar_url

# Cloudflare Durable Chat worker URL for real-time notifications
CHAT_WORKER_URL = "https://chat.justpros.org"

router = APIRouter(prefix="/api/messages", tags=["messages"])


async def notify_user(user_handle: str, notification_type: str = "new_message") -> None:
    """Send a real-time notification to a user via CF Durable Chat worker.

    This broadcasts a message to the user's personal notification room.
    The client WebSocket connection will receive this and refresh messages.
    Uses the /broadcast HTTP endpoint (server-to-server communication).
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # POST to the PartyServer room's broadcast endpoint
            # PartyServer routes: /parties/:className/:roomName
            await client.post(
                f"{CHAT_WORKER_URL}/parties/chat/{user_handle}/broadcast",
                json={"message": notification_type},
            )
    except Exception:
        # Notification failures are non-critical, don't break the request
        pass


# --- Pydantic Models ---


class ConnectionRequestCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 500:
            raise ValueError("Message must be 1-500 characters")
        return v


class MessageCreate(BaseModel):
    content: str
    reply_to: int | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 2000:
            raise ValueError("Message must be 1-2000 characters")
        return v


class AbuseReportCreate(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10 or len(v) > 1000:
            raise ValueError("Reason must be 10-1000 characters")
        return v


# --- Helper Functions ---


def _format_user_name(user: dict) -> str:
    """Format user's full name from first/middle/last."""
    first_name = user.get("first_name") or ""
    middle_name = user.get("middle_name")
    last_name = user.get("last_name") or ""
    if middle_name:
        return f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
    return f"{first_name} {last_name}".strip()


async def _get_user_by_handle(handle: str) -> dict | None:
    """Get user by handle."""
    return await database.fetch_one(
        """
        SELECT id, handle, first_name, middle_name, last_name, headline, avatar_path
        FROM users WHERE handle = :handle
        """,
        {"handle": handle.lower()},
    )


async def _is_connected(user1_id: int, user2_id: int) -> bool:
    """Check if two users are connected (confirm message exists between them)."""
    result = await database.fetch_one(
        """
        SELECT 1 FROM messages
        WHERE kind = 'confirm'
          AND ((sender_id = :u1 AND receiver_id = :u2)
               OR (sender_id = :u2 AND receiver_id = :u1))
        LIMIT 1
        """,
        {"u1": user1_id, "u2": user2_id},
    )
    return result is not None


async def _has_pending_connection_request(from_user_id: int, to_user_id: int) -> bool:
    """Check if there's a pending connection request (request without confirm response)."""
    # A connection request is pending if:
    # 1. There's a connection_request from from_user to to_user
    # 2. There's no confirm from to_user to from_user after the request
    # 3. The receiver hasn't deleted the conversation (which acts as ignore)
    request = await database.fetch_one(
        """
        SELECT m.id, m.created_at FROM messages m
        WHERE m.kind = 'connection_request'
          AND m.sender_id = :from_id
          AND m.receiver_id = :to_id
          AND m.receiver_deleted IS NULL
        ORDER BY m.created_at DESC
        LIMIT 1
        """,
        {"from_id": from_user_id, "to_id": to_user_id},
    )

    if not request:
        return False

    # Check if there's a confirm after this request
    confirm = await database.fetch_one(
        """
        SELECT 1 FROM messages
        WHERE kind = 'confirm'
          AND sender_id = :to_id
          AND receiver_id = :from_id
          AND created_at > :request_time
        LIMIT 1
        """,
        {"to_id": to_user_id, "from_id": from_user_id, "request_time": request["created_at"]},
    )

    return confirm is None


async def _get_last_read_message_id(user_id: int, other_user_id: int) -> int | None:
    """Get the last read message ID for a conversation.

    Derives the conversation from the message's sender/receiver.
    """
    result = await database.fetch_one(
        """
        SELECT cr.last_read_message_id
        FROM conversation_reads cr
        JOIN messages m ON m.id = cr.last_read_message_id
        WHERE cr.user_id = :user_id
          AND (
              (m.sender_id = :user_id AND m.receiver_id = :other_user_id)
              OR (m.sender_id = :other_user_id AND m.receiver_id = :user_id)
          )
        """,
        {"user_id": user_id, "other_user_id": other_user_id},
    )
    return result["last_read_message_id"] if result else None


async def _update_last_read(user_id: int, other_user_id: int, message_id: int) -> None:
    """Update the last read message ID for a conversation.

    Since we don't store other_user_id, we need to:
    1. Find existing read marker for this conversation (by joining to messages)
    2. Delete it if exists
    3. Insert new one
    """
    # Delete existing read marker for this conversation
    await database.execute(
        """
        DELETE FROM conversation_reads
        WHERE user_id = :user_id
          AND last_read_message_id IN (
              SELECT m.id FROM messages m
              WHERE (m.sender_id = :user_id AND m.receiver_id = :other_user_id)
                 OR (m.sender_id = :other_user_id AND m.receiver_id = :user_id)
          )
        """,
        {"user_id": user_id, "other_user_id": other_user_id},
    )

    # Insert new read marker
    await database.execute(
        """
        INSERT INTO conversation_reads (user_id, last_read_message_id)
        VALUES (:user_id, :message_id)
        """,
        {"user_id": user_id, "message_id": message_id},
    )


def _format_other_user(user: dict) -> dict:
    """Format user info for API response."""
    avatar_path = user.get("avatar_path")
    return {
        "id": user["id"],
        "handle": user["handle"],
        "name": _format_user_name(user),
        "headline": user.get("headline"),
        "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
    }


# --- Endpoints ---


@router.get("")
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    filter: str = "important",
    limit: int = 50,
) -> list[dict]:
    """
    List conversations for current user.

    Filters:
    - important: connected conversations + new claims from strangers
    - connections: only connected conversations
    - all: everything
    """
    user_id = current_user["id"]

    # Get all conversation partners (distinct users we have messages with)
    # where messages aren't deleted from our perspective
    conversations_query = """
        WITH conversation_partners AS (
            SELECT DISTINCT
                CASE
                    WHEN sender_id = :user_id THEN receiver_id
                    ELSE sender_id
                END as other_user_id
            FROM messages
            WHERE (sender_id = :user_id AND sender_deleted IS NULL)
               OR (receiver_id = :user_id AND receiver_deleted IS NULL)
        ),
        conversation_data AS (
            SELECT
                cp.other_user_id as id,
                u.handle,
                u.first_name,
                u.middle_name,
                u.last_name,
                u.headline,
                u.avatar_path,
                -- Check if connected (confirm message exists)
                EXISTS (
                    SELECT 1 FROM messages
                    WHERE kind = 'confirm'
                      AND ((sender_id = :user_id AND receiver_id = cp.other_user_id)
                           OR (sender_id = cp.other_user_id AND receiver_id = :user_id))
                ) as is_connected,
                -- Get last message
                (
                    SELECT m.id FROM messages m
                    WHERE ((m.sender_id = :user_id AND m.receiver_id = cp.other_user_id AND m.sender_deleted IS NULL)
                           OR (m.sender_id = cp.other_user_id AND m.receiver_id = :user_id AND m.receiver_deleted IS NULL))
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) as last_message_id,
                (
                    SELECT m.content FROM messages m
                    WHERE ((m.sender_id = :user_id AND m.receiver_id = cp.other_user_id AND m.sender_deleted IS NULL)
                           OR (m.sender_id = cp.other_user_id AND m.receiver_id = :user_id AND m.receiver_deleted IS NULL))
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) as last_message_content,
                (
                    SELECT m.kind FROM messages m
                    WHERE ((m.sender_id = :user_id AND m.receiver_id = cp.other_user_id AND m.sender_deleted IS NULL)
                           OR (m.sender_id = cp.other_user_id AND m.receiver_id = :user_id AND m.receiver_deleted IS NULL))
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) as last_message_kind,
                (
                    SELECT m.sender_id FROM messages m
                    WHERE ((m.sender_id = :user_id AND m.receiver_id = cp.other_user_id AND m.sender_deleted IS NULL)
                           OR (m.sender_id = cp.other_user_id AND m.receiver_id = :user_id AND m.receiver_deleted IS NULL))
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) as last_message_sender_id,
                (
                    SELECT m.created_at FROM messages m
                    WHERE ((m.sender_id = :user_id AND m.receiver_id = cp.other_user_id AND m.sender_deleted IS NULL)
                           OR (m.sender_id = cp.other_user_id AND m.receiver_id = :user_id AND m.receiver_deleted IS NULL))
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) as last_message_at,
                -- Unread count (messages from them that are newer than our read marker)
                (
                    SELECT COUNT(*) FROM messages m
                    WHERE m.sender_id = cp.other_user_id
                      AND m.receiver_id = :user_id
                      AND m.receiver_deleted IS NULL
                      AND m.id > COALESCE((
                          SELECT cr.last_read_message_id
                          FROM conversation_reads cr
                          JOIN messages rm ON rm.id = cr.last_read_message_id
                          WHERE cr.user_id = :user_id
                            AND ((rm.sender_id = :user_id AND rm.receiver_id = cp.other_user_id)
                                 OR (rm.sender_id = cp.other_user_id AND rm.receiver_id = :user_id))
                      ), 0)
                ) as unread_count,
                -- Has pending request from them (for "important" filter)
                EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.kind = 'connection_request'
                      AND m.sender_id = cp.other_user_id
                      AND m.receiver_id = :user_id
                      AND m.receiver_deleted IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM messages m2
                          WHERE m2.kind = 'confirm'
                            AND m2.sender_id = :user_id
                            AND m2.receiver_id = cp.other_user_id
                            AND m2.created_at > m.created_at
                      )
                ) as has_pending_request_from_them,
                -- Has pending request from me (for "important" filter)
                EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.kind = 'connection_request'
                      AND m.sender_id = :user_id
                      AND m.receiver_id = cp.other_user_id
                      AND m.sender_deleted IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM messages m2
                          WHERE m2.kind = 'confirm'
                            AND m2.sender_id = cp.other_user_id
                            AND m2.receiver_id = :user_id
                            AND m2.created_at > m.created_at
                      )
                ) as has_pending_request_from_me
            FROM conversation_partners cp
            JOIN users u ON u.id = cp.other_user_id
        )
        SELECT * FROM conversation_data
        WHERE last_message_id IS NOT NULL
    """

    # Add filter conditions
    if filter == "connections":
        conversations_query += " AND is_connected = true"
    elif filter == "important":
        conversations_query += " AND (is_connected = true OR has_pending_request_from_them = true OR has_pending_request_from_me = true)"
    # "all" has no additional filter

    conversations_query += " ORDER BY last_message_at DESC LIMIT :limit"

    conversations = await database.fetch_all(
        conversations_query,
        {"user_id": user_id, "limit": limit},
    )

    results = []
    for conv in conversations:
        results.append({
            "other_user": _format_other_user(dict(conv)),
            "is_connected": conv["is_connected"],
            "last_message": {
                "content": conv["last_message_content"],
                "kind": conv["last_message_kind"],
                "is_mine": conv["last_message_sender_id"] == user_id,
            },
            "unread_count": conv["unread_count"],
            "last_message_at": conv["last_message_at"].isoformat() if conv["last_message_at"] else None,
            "has_pending_request": conv["has_pending_request_from_them"],
        })

    return results


@router.get("/unread-count")
async def get_unread_count(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get total unread message count for navbar badge."""
    user_id = current_user["id"]

    result = await database.fetch_one(
        """
        SELECT COUNT(*) as count
        FROM messages m
        WHERE m.receiver_id = :user_id
          AND m.receiver_deleted IS NULL
          AND m.id > COALESCE((
              SELECT cr.last_read_message_id
              FROM conversation_reads cr
              JOIN messages rm ON rm.id = cr.last_read_message_id
              WHERE cr.user_id = :user_id
                AND ((rm.sender_id = :user_id AND rm.receiver_id = m.sender_id)
                     OR (rm.sender_id = m.sender_id AND rm.receiver_id = :user_id))
          ), 0)
        """,
        {"user_id": user_id},
    )

    return {"count": result["count"] if result else 0}


@router.get("/pending-requests-count")
async def get_pending_requests_count(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get count of pending connection requests needing response for navbar badge."""
    user_id = current_user["id"]

    result = await database.fetch_one(
        """
        SELECT COUNT(DISTINCT m.sender_id) as count
        FROM messages m
        WHERE m.kind = 'connection_request'
          AND m.receiver_id = :user_id
          AND m.receiver_deleted IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM messages m2
              WHERE m2.kind = 'confirm'
                AND m2.sender_id = :user_id
                AND m2.receiver_id = m.sender_id
                AND m2.created_at > m.created_at
          )
        """,
        {"user_id": user_id},
    )

    return {"count": result["count"] if result else 0}


@router.get("/with/{handle}")
async def get_conversation_with_user(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get conversation state with a specific user."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot message yourself")

    other_user_id = other_user["id"]

    # Check connection status
    connected = await _is_connected(user_id, other_user_id)

    # Check for pending requests in both directions
    pending_request_from_me = await _has_pending_connection_request(user_id, other_user_id)
    pending_request_from_them = await _has_pending_connection_request(other_user_id, user_id)

    return {
        "other_user": _format_other_user(dict(other_user)),
        "is_connected": connected,
        "pending_request_from_me": pending_request_from_me,
        "pending_request_from_them": pending_request_from_them,
        "can_send_text": connected,
        "can_send_request": not connected and not pending_request_from_me,
    }


@router.get("/with/{handle}/messages")
async def get_messages(
    handle: str,
    current_user: dict = Depends(get_current_user),
    before_id: int | None = None,
    limit: int = 50,
) -> dict:
    """Get messages in a conversation."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Build query for messages
    if before_id:
        messages = await database.fetch_all(
            """
            SELECT id, kind, sender_id, receiver_id, content, reply_to, created_at
            FROM messages
            WHERE ((sender_id = :user_id AND receiver_id = :other_id AND sender_deleted IS NULL)
                   OR (sender_id = :other_id AND receiver_id = :user_id AND receiver_deleted IS NULL))
              AND id < :before_id
            ORDER BY created_at DESC
            LIMIT :limit
            """,
            {"user_id": user_id, "other_id": other_user_id, "before_id": before_id, "limit": limit},
        )
    else:
        messages = await database.fetch_all(
            """
            SELECT id, kind, sender_id, receiver_id, content, reply_to, created_at
            FROM messages
            WHERE ((sender_id = :user_id AND receiver_id = :other_id AND sender_deleted IS NULL)
                   OR (sender_id = :other_id AND receiver_id = :user_id AND receiver_deleted IS NULL))
            ORDER BY created_at DESC
            LIMIT :limit
            """,
            {"user_id": user_id, "other_id": other_user_id, "limit": limit},
        )

    # Mark as read (update last_read_message_id)
    if messages:
        max_message_id = max(m["id"] for m in messages)
        await _update_last_read(user_id, other_user_id, max_message_id)

    # Check connection status
    connected = await _is_connected(user_id, other_user_id)

    # Check for pending request from them
    pending_request_from_them = await _has_pending_connection_request(other_user_id, user_id)

    return {
        "other_user": _format_other_user(dict(other_user)),
        "is_connected": connected,
        "pending_request_from_them": pending_request_from_them,
        "messages": [
            {
                "id": m["id"],
                "kind": m["kind"],
                "sender_id": m["sender_id"],
                "is_mine": m["sender_id"] == user_id,
                "content": m["content"],
                "reply_to": m["reply_to"],
                "created_at": m["created_at"].isoformat() if m["created_at"] else None,
            }
            for m in reversed(messages)  # Return oldest first for display
        ],
        "has_more": len(messages) == limit,
    }


@router.post("/to/{handle}/connect")
async def send_connection_request(
    handle: str,
    payload: ConnectionRequestCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Send a connection request to a user."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot connect with yourself")

    other_user_id = other_user["id"]

    # Check if already connected
    if await _is_connected(user_id, other_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already connected",
        )

    # Check if there's already a pending request from me
    if await _has_pending_connection_request(user_id, other_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a pending request",
        )

    # TODO: Add rate limiting (3/day per pair, 100/day global)

    # Insert connection request message
    result = await database.fetch_one(
        """
        INSERT INTO messages (kind, sender_id, receiver_id, content)
        VALUES ('connection_request', :sender_id, :receiver_id, :content)
        RETURNING id, created_at
        """,
        {"sender_id": user_id, "receiver_id": other_user_id, "content": payload.content},
    )

    # Notify receiver of new connection request
    await notify_user(other_user["handle"], "new_message")

    return {
        "id": result["id"],
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.post("/to/{handle}/confirm")
async def confirm_connection_request(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm a connection request from another user (creates connection)."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Check if there's a pending request from them
    if not await _has_pending_connection_request(other_user_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending request to confirm",
        )

    # Insert confirm message
    result = await database.fetch_one(
        """
        INSERT INTO messages (kind, sender_id, receiver_id, content)
        VALUES ('confirm', :sender_id, :receiver_id, NULL)
        RETURNING id, created_at
        """,
        {"sender_id": user_id, "receiver_id": other_user_id},
    )

    # Notify the other user that their request was confirmed
    await notify_user(other_user["handle"], "new_message")

    return {
        "id": result["id"],
        "is_connected": True,
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.post("/to/{handle}/message")
async def send_message(
    handle: str,
    payload: MessageCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Send a regular text message to a connected user."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot message yourself")

    other_user_id = other_user["id"]

    # Check if connected
    if not await _is_connected(user_id, other_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be connected to send messages",
        )

    # Insert message
    result = await database.fetch_one(
        """
        INSERT INTO messages (kind, sender_id, receiver_id, content, reply_to)
        VALUES ('text', :sender_id, :receiver_id, :content, :reply_to)
        RETURNING id, created_at
        """,
        {
            "sender_id": user_id,
            "receiver_id": other_user_id,
            "content": payload.content,
            "reply_to": payload.reply_to,
        },
    )

    # Notify receiver of new message
    await notify_user(other_user["handle"], "new_message")

    return {
        "id": result["id"],
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.delete("/with/{handle}")
async def delete_conversation(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Delete user's copy of the conversation (acts as ignore for pending claims).
    This soft-deletes all messages from the user's perspective.
    """
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Soft delete messages where user is sender
    await database.execute(
        """
        UPDATE messages
        SET sender_deleted = NOW()
        WHERE sender_id = :user_id AND receiver_id = :other_id AND sender_deleted IS NULL
        """,
        {"user_id": user_id, "other_id": other_user_id},
    )

    # Soft delete messages where user is receiver
    await database.execute(
        """
        UPDATE messages
        SET receiver_deleted = NOW()
        WHERE sender_id = :other_id AND receiver_id = :user_id AND receiver_deleted IS NULL
        """,
        {"user_id": user_id, "other_id": other_user_id},
    )

    return {"deleted": True}


@router.delete("/connection/{handle}")
async def remove_connection(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Remove connection with a user.
    This deletes all confirm messages between the users, reverting to non-connected state.
    Conversation history remains visible.
    """
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Check if actually connected
    if not await _is_connected(user_id, other_user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not connected",
        )

    # Delete all confirm messages between the users
    await database.execute(
        """
        DELETE FROM messages
        WHERE kind = 'confirm'
          AND ((sender_id = :user_id AND receiver_id = :other_id)
               OR (sender_id = :other_id AND receiver_id = :user_id))
        """,
        {"user_id": user_id, "other_id": other_user_id},
    )

    return {"removed": True, "is_connected": False}


@router.post("/with/{handle}/report")
async def report_conversation(
    handle: str,
    payload: AbuseReportCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Report a user for abuse."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot report yourself")

    other_user_id = other_user["id"]

    # TODO: Add rate limiting (1/day per user, 100/day global)

    # Insert abuse report
    await database.execute(
        """
        INSERT INTO abuse_reports (reporter_id, reported_user_id, reason)
        VALUES (:reporter_id, :reported_user_id, :reason)
        """,
        {"reporter_id": user_id, "reported_user_id": other_user_id, "reason": payload.reason},
    )

    return {"reported": True}
