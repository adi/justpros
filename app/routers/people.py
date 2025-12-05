from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.db import database
from app.routers.messages import notify_user
from app.storage import get_avatar_url

router = APIRouter(prefix="/api/people", tags=["people"])


# --- Helper Functions ---


def _format_user_name(user: dict) -> str:
    """Format user's full name from first/middle/last."""
    first_name = user.get("first_name") or ""
    middle_name = user.get("middle_name")
    last_name = user.get("last_name") or ""
    if middle_name:
        return f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
    return f"{first_name} {last_name}".strip()


def _format_person(user: dict) -> dict:
    """Format user info for People API response."""
    avatar_path = user.get("avatar_path")
    return {
        "handle": user["handle"],
        "name": _format_user_name(user),
        "headline": user.get("headline"),
        "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
    }


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


async def _has_pending_request_from(from_user_id: int, to_user_id: int) -> bool:
    """Check if there's a pending connection request from from_user to to_user."""
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


# --- Endpoints ---


@router.get("/connections")
async def list_connections(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List all confirmed connections for current user."""
    user_id = current_user["id"]

    # Find all users where a confirm message exists between current user and them
    connections = await database.fetch_all(
        """
        WITH connected_users AS (
            SELECT DISTINCT
                CASE
                    WHEN sender_id = :user_id THEN receiver_id
                    ELSE sender_id
                END as other_user_id,
                MAX(created_at) as connected_at
            FROM messages
            WHERE kind = 'confirm'
              AND (sender_id = :user_id OR receiver_id = :user_id)
            GROUP BY other_user_id
        )
        SELECT
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path,
            cu.connected_at
        FROM connected_users cu
        JOIN users u ON u.id = cu.other_user_id
        ORDER BY cu.connected_at DESC
        """,
        {"user_id": user_id},
    )

    return [
        {
            **_format_person(dict(conn)),
            "connected_at": conn["connected_at"].isoformat() if conn["connected_at"] else None,
        }
        for conn in connections
    ]


@router.get("/pending-sent")
async def list_pending_sent(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List pending connection requests I have sent."""
    user_id = current_user["id"]

    # Find connection requests I sent that haven't been confirmed
    pending = await database.fetch_all(
        """
        SELECT DISTINCT ON (m.receiver_id)
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path,
            m.created_at as sent_at
        FROM messages m
        JOIN users u ON u.id = m.receiver_id
        WHERE m.kind = 'connection_request'
          AND m.sender_id = :user_id
          AND m.sender_deleted IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM messages m2
              WHERE m2.kind = 'confirm'
                AND m2.sender_id = m.receiver_id
                AND m2.receiver_id = :user_id
                AND m2.created_at > m.created_at
          )
        ORDER BY m.receiver_id, m.created_at DESC
        """,
        {"user_id": user_id},
    )

    return [
        {
            **_format_person(dict(p)),
            "sent_at": p["sent_at"].isoformat() if p["sent_at"] else None,
        }
        for p in pending
    ]


@router.get("/pending-received")
async def list_pending_received(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List pending connection requests awaiting my response."""
    user_id = current_user["id"]

    # Find connection requests sent to me that I haven't confirmed
    pending = await database.fetch_all(
        """
        SELECT DISTINCT ON (m.sender_id)
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path,
            m.created_at as received_at
        FROM messages m
        JOIN users u ON u.id = m.sender_id
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
        ORDER BY m.sender_id, m.created_at DESC
        """,
        {"user_id": user_id},
    )

    return [
        {
            **_format_person(dict(p)),
            "received_at": p["received_at"].isoformat() if p["received_at"] else None,
        }
        for p in pending
    ]


@router.get("/pending-received-count")
async def get_pending_received_count(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get count of pending connection requests for navbar badge."""
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


@router.post("/{handle}/connect")
async def send_connection_request(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Send a connection request to a user (no message content)."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot connect with yourself")

    other_user_id = other_user["id"]

    # Check if already connected
    if await _is_connected(user_id, other_user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already connected")

    # Check if there's already a pending request from me
    if await _has_pending_request_from(user_id, other_user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You already have a pending request")

    # Insert connection request message (no content)
    result = await database.fetch_one(
        """
        INSERT INTO messages (kind, sender_id, receiver_id, content)
        VALUES ('connection_request', :sender_id, :receiver_id, NULL)
        RETURNING id, created_at
        """,
        {"sender_id": user_id, "receiver_id": other_user_id},
    )

    # Notify receiver
    await notify_user(other_user["handle"], "new_connection_request")

    return {
        "sent": True,
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.post("/{handle}/confirm")
async def confirm_connection(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm a pending connection request."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Check if there's a pending request from them
    if not await _has_pending_request_from(other_user_id, user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending request to confirm")

    # Insert confirm message
    result = await database.fetch_one(
        """
        INSERT INTO messages (kind, sender_id, receiver_id, content)
        VALUES ('confirm', :sender_id, :receiver_id, NULL)
        RETURNING id, created_at
        """,
        {"sender_id": user_id, "receiver_id": other_user_id},
    )

    # Notify the other user
    await notify_user(other_user["handle"], "connection_confirmed")

    return {
        "confirmed": True,
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.post("/{handle}/ignore")
async def ignore_connection_request(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Ignore a pending connection request (soft-delete from my perspective)."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Check if there's a pending request from them
    if not await _has_pending_request_from(other_user_id, user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending request to ignore")

    # Soft-delete the connection request from receiver's perspective
    await database.execute(
        """
        UPDATE messages
        SET receiver_deleted = NOW()
        WHERE kind = 'connection_request'
          AND sender_id = :other_id
          AND receiver_id = :user_id
          AND receiver_deleted IS NULL
        """,
        {"user_id": user_id, "other_id": other_user_id},
    )

    return {"ignored": True}


@router.delete("/{handle}")
async def disconnect(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Disconnect from a user (removes connection)."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Check if connected
    if not await _is_connected(user_id, other_user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not connected")

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

    return {"disconnected": True}


@router.delete("/request/{handle}")
async def withdraw_connection_request(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Withdraw a pending connection request I sent."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]

    # Check if there's a pending request from me
    if not await _has_pending_request_from(user_id, other_user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending request to withdraw")

    # Soft-delete the connection request from sender's perspective
    await database.execute(
        """
        UPDATE messages
        SET sender_deleted = NOW()
        WHERE kind = 'connection_request'
          AND sender_id = :user_id
          AND receiver_id = :other_id
          AND sender_deleted IS NULL
        """,
        {"user_id": user_id, "other_id": other_user_id},
    )

    return {"withdrawn": True}


@router.get("/status/{handle}")
async def get_connection_status(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get connection status with a specific user."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if other_user["id"] == user_id:
        return {
            "is_self": True,
            "is_connected": False,
            "pending_from_me": False,
            "pending_from_them": False,
        }

    other_user_id = other_user["id"]

    connected = await _is_connected(user_id, other_user_id)
    pending_from_me = await _has_pending_request_from(user_id, other_user_id)
    pending_from_them = await _has_pending_request_from(other_user_id, user_id)

    return {
        "is_self": False,
        "is_connected": connected,
        "pending_from_me": pending_from_me,
        "pending_from_them": pending_from_them,
    }
