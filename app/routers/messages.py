from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.db import database
from app.storage import get_avatar_url

router = APIRouter(prefix="/api/messages", tags=["messages"])


class MessageCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 2000:
            raise ValueError("Message must be 1-2000 characters")
        return v


def _format_user_name(user: dict) -> str:
    """Format user's full name from first/middle/last."""
    first_name = user.get("first_name") or ""
    middle_name = user.get("middle_name")
    last_name = user.get("last_name") or ""
    if middle_name:
        return f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
    return f"{first_name} {last_name}".strip()


async def _get_or_create_conversation(user1_id: int, user2_id: int) -> int:
    """Get existing conversation or create new one. Returns conversation ID."""
    # Ensure consistent ordering (user1_id < user2_id)
    if user1_id > user2_id:
        user1_id, user2_id = user2_id, user1_id

    # Try to get existing
    conv = await database.fetch_one(
        """
        SELECT id FROM conversations
        WHERE user1_id = :u1 AND user2_id = :u2
        """,
        {"u1": user1_id, "u2": user2_id},
    )

    if conv:
        return conv["id"]

    # Create new conversation
    result = await database.fetch_one(
        """
        INSERT INTO conversations (user1_id, user2_id)
        VALUES (:u1, :u2)
        RETURNING id
        """,
        {"u1": user1_id, "u2": user2_id},
    )
    return result["id"]


async def _can_message(from_user_id: int, to_user_id: int) -> tuple[bool, str]:
    """
    Check if user can message another user.
    Returns (allowed, reason).

    Rules:
    - Can always message if connected (confirmed connection)
    - Can send ONE message if connection is pending (as intro)
    - Cannot message if no connection exists
    """
    # Check for confirmed connection
    confirmed = await database.fetch_one(
        """
        SELECT id FROM connections
        WHERE status = 'confirmed'
          AND ((from_user_id = :from_id AND to_user_id = :to_id)
               OR (from_user_id = :to_id AND to_user_id = :from_id))
        """,
        {"from_id": from_user_id, "to_id": to_user_id},
    )

    if confirmed:
        return True, "connected"

    # Check for pending connection FROM current user
    pending_from_me = await database.fetch_one(
        """
        SELECT id FROM connections
        WHERE status = 'pending'
          AND from_user_id = :from_id AND to_user_id = :to_id
        """,
        {"from_id": from_user_id, "to_id": to_user_id},
    )

    if pending_from_me:
        # Check if already sent a message in this conversation
        # (only 1 intro message allowed while pending)
        conv_id = await _get_conversation_id(from_user_id, to_user_id)
        if conv_id:
            msg_count = await database.fetch_one(
                """
                SELECT COUNT(*) as count FROM messages
                WHERE conversation_id = :conv_id AND sender_id = :sender_id
                """,
                {"conv_id": conv_id, "sender_id": from_user_id},
            )
            if msg_count and msg_count["count"] > 0:
                return False, "already_sent_intro"
        return True, "pending_intro"

    # Check for pending connection TO current user (they can respond)
    pending_to_me = await database.fetch_one(
        """
        SELECT id FROM connections
        WHERE status = 'pending'
          AND from_user_id = :to_id AND to_user_id = :from_id
        """,
        {"from_id": from_user_id, "to_id": to_user_id},
    )

    if pending_to_me:
        return True, "can_respond"

    return False, "not_connected"


async def _get_conversation_id(user1_id: int, user2_id: int) -> int | None:
    """Get conversation ID if exists, None otherwise."""
    if user1_id > user2_id:
        user1_id, user2_id = user2_id, user1_id

    conv = await database.fetch_one(
        """
        SELECT id FROM conversations
        WHERE user1_id = :u1 AND user2_id = :u2
        """,
        {"u1": user1_id, "u2": user2_id},
    )
    return conv["id"] if conv else None


@router.get("")
async def list_conversations(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List all conversations for current user, newest first."""
    user_id = current_user["id"]

    conversations = await database.fetch_all(
        """
        SELECT
            c.id,
            c.last_message_at,
            CASE WHEN c.user1_id = :user_id THEN c.user2_id ELSE c.user1_id END as other_user_id,
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path,
            m.content as last_message,
            m.sender_id as last_sender_id,
            (
                SELECT COUNT(*) FROM messages
                WHERE conversation_id = c.id
                  AND sender_id != :user_id
                  AND read_at IS NULL
            ) as unread_count
        FROM conversations c
        JOIN users u ON u.id = CASE WHEN c.user1_id = :user_id THEN c.user2_id ELSE c.user1_id END
        LEFT JOIN LATERAL (
            SELECT content, sender_id FROM messages
            WHERE conversation_id = c.id
            ORDER BY created_at DESC
            LIMIT 1
        ) m ON true
        WHERE c.user1_id = :user_id OR c.user2_id = :user_id
        ORDER BY c.last_message_at DESC
        """,
        {"user_id": user_id},
    )

    results = []
    for conv in conversations:
        avatar_path = conv["avatar_path"]
        results.append({
            "id": conv["id"],
            "other_user": {
                "id": conv["other_user_id"],
                "handle": conv["handle"],
                "name": _format_user_name(dict(conv)),
                "headline": conv["headline"],
                "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
            },
            "last_message": conv["last_message"],
            "last_message_is_mine": conv["last_sender_id"] == user_id if conv["last_sender_id"] else False,
            "unread_count": conv["unread_count"],
            "last_message_at": conv["last_message_at"].isoformat() if conv["last_message_at"] else None,
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
        SELECT COUNT(*) as count FROM messages m
        JOIN conversations c ON m.conversation_id = c.id
        WHERE (c.user1_id = :user_id OR c.user2_id = :user_id)
          AND m.sender_id != :user_id
          AND m.read_at IS NULL
        """,
        {"user_id": user_id},
    )

    return {"count": result["count"] if result else 0}


@router.get("/pending-connections-count")
async def get_pending_connections_count(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get count of pending connection requests for navbar badge."""
    user_id = current_user["id"]

    result = await database.fetch_one(
        """
        SELECT COUNT(*) as count FROM connections
        WHERE to_user_id = :user_id AND status = 'pending'
        """,
        {"user_id": user_id},
    )

    return {"count": result["count"] if result else 0}


@router.get("/with/{handle}")
async def get_conversation_with_user(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get or check conversation with a specific user."""
    user_id = current_user["id"]

    # Get the other user
    other_user = await database.fetch_one(
        """
        SELECT id, handle, first_name, middle_name, last_name, headline, avatar_path
        FROM users WHERE handle = :handle
        """,
        {"handle": handle.lower()},
    )

    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot message yourself")

    other_user_id = other_user["id"]

    # Check if can message
    can_msg, reason = await _can_message(user_id, other_user_id)

    # Get existing conversation if any
    conv_id = await _get_conversation_id(user_id, other_user_id)

    avatar_path = other_user["avatar_path"]
    return {
        "conversation_id": conv_id,
        "can_message": can_msg,
        "reason": reason,
        "other_user": {
            "id": other_user_id,
            "handle": other_user["handle"],
            "name": _format_user_name(dict(other_user)),
            "headline": other_user["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
        },
    }


@router.get("/{conversation_id}")
async def get_messages(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    before_id: int | None = None,
    limit: int = 50,
) -> dict:
    """Get messages in a conversation."""
    user_id = current_user["id"]

    # Verify user is part of conversation
    conv = await database.fetch_one(
        """
        SELECT user1_id, user2_id FROM conversations
        WHERE id = :id AND (user1_id = :user_id OR user2_id = :user_id)
        """,
        {"id": conversation_id, "user_id": user_id},
    )

    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Get the other user
    other_user_id = conv["user2_id"] if conv["user1_id"] == user_id else conv["user1_id"]
    other_user = await database.fetch_one(
        """
        SELECT id, handle, first_name, middle_name, last_name, headline, avatar_path
        FROM users WHERE id = :id
        """,
        {"id": other_user_id},
    )

    # Build query for messages
    if before_id:
        messages = await database.fetch_all(
            """
            SELECT id, sender_id, content, read_at, created_at
            FROM messages
            WHERE conversation_id = :conv_id AND id < :before_id
            ORDER BY created_at DESC
            LIMIT :limit
            """,
            {"conv_id": conversation_id, "before_id": before_id, "limit": limit},
        )
    else:
        messages = await database.fetch_all(
            """
            SELECT id, sender_id, content, read_at, created_at
            FROM messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at DESC
            LIMIT :limit
            """,
            {"conv_id": conversation_id, "limit": limit},
        )

    # Mark messages as read
    await database.execute(
        """
        UPDATE messages
        SET read_at = NOW()
        WHERE conversation_id = :conv_id
          AND sender_id != :user_id
          AND read_at IS NULL
        """,
        {"conv_id": conversation_id, "user_id": user_id},
    )

    avatar_path = other_user["avatar_path"] if other_user else None
    return {
        "conversation_id": conversation_id,
        "other_user": {
            "id": other_user_id,
            "handle": other_user["handle"] if other_user else None,
            "name": _format_user_name(dict(other_user)) if other_user else None,
            "headline": other_user["headline"] if other_user else None,
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
        },
        "messages": [
            {
                "id": m["id"],
                "sender_id": m["sender_id"],
                "is_mine": m["sender_id"] == user_id,
                "content": m["content"],
                "created_at": m["created_at"].isoformat() if m["created_at"] else None,
            }
            for m in reversed(messages)  # Return oldest first for display
        ],
        "has_more": len(messages) == limit,
    }


@router.post("/to/{handle}")
async def send_message_to_user(
    handle: str,
    payload: MessageCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Send a message to a user by handle."""
    user_id = current_user["id"]

    # Get the other user
    other_user = await database.fetch_one(
        "SELECT id FROM users WHERE handle = :handle",
        {"handle": handle.lower()},
    )

    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot message yourself")

    other_user_id = other_user["id"]

    # Check if can message
    can_msg, reason = await _can_message(user_id, other_user_id)
    if not can_msg:
        if reason == "already_sent_intro":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only send one message until they respond or accept your connection",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be connected to message this user",
        )

    # Get or create conversation
    conv_id = await _get_or_create_conversation(user_id, other_user_id)

    # Insert message
    result = await database.fetch_one(
        """
        INSERT INTO messages (conversation_id, sender_id, content)
        VALUES (:conv_id, :sender_id, :content)
        RETURNING id, created_at
        """,
        {"conv_id": conv_id, "sender_id": user_id, "content": payload.content},
    )

    # Update conversation last_message_at
    await database.execute(
        """
        UPDATE conversations
        SET last_message_at = NOW()
        WHERE id = :id
        """,
        {"id": conv_id},
    )

    return {
        "id": result["id"],
        "conversation_id": conv_id,
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.post("/{conversation_id}")
async def send_message_to_conversation(
    conversation_id: int,
    payload: MessageCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Send a message to an existing conversation."""
    user_id = current_user["id"]

    # Verify user is part of conversation and get other user
    conv = await database.fetch_one(
        """
        SELECT user1_id, user2_id FROM conversations
        WHERE id = :id AND (user1_id = :user_id OR user2_id = :user_id)
        """,
        {"id": conversation_id, "user_id": user_id},
    )

    if conv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    other_user_id = conv["user2_id"] if conv["user1_id"] == user_id else conv["user1_id"]

    # Check if can message
    can_msg, reason = await _can_message(user_id, other_user_id)
    if not can_msg:
        if reason == "already_sent_intro":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only send one message until they respond or accept your connection",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be connected to message this user",
        )

    # Insert message
    result = await database.fetch_one(
        """
        INSERT INTO messages (conversation_id, sender_id, content)
        VALUES (:conv_id, :sender_id, :content)
        RETURNING id, created_at
        """,
        {"conv_id": conversation_id, "sender_id": user_id, "content": payload.content},
    )

    # Update conversation last_message_at
    await database.execute(
        """
        UPDATE conversations
        SET last_message_at = NOW()
        WHERE id = :id
        """,
        {"id": conversation_id},
    )

    return {
        "id": result["id"],
        "conversation_id": conversation_id,
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }
