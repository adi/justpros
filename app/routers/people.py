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


def _order_user_ids(id1: int, id2: int) -> tuple[int, int]:
    """Return IDs in consistent order for unique constraint (user1_id < user2_id)."""
    return (min(id1, id2), max(id1, id2))


async def _get_connection(user1_id: int, user2_id: int) -> dict | None:
    """Get connection record between two users."""
    u1, u2 = _order_user_ids(user1_id, user2_id)
    return await database.fetch_one(
        """SELECT * FROM connections WHERE user1_id = :u1 AND user2_id = :u2""",
        {"u1": u1, "u2": u2},
    )


async def _is_connected(user1_id: int, user2_id: int) -> bool:
    """O(1) check if two users are connected."""
    conn = await _get_connection(user1_id, user2_id)
    return conn is not None and conn["status"] == "confirmed"


async def _has_pending_request_from(from_user_id: int, to_user_id: int) -> bool:
    """Check if there's a pending connection request from from_user to to_user."""
    u1, u2 = _order_user_ids(from_user_id, to_user_id)
    conn = await database.fetch_one(
        """
        SELECT 1 FROM connections
        WHERE user1_id = :u1 AND user2_id = :u2
          AND status = 'pending'
          AND requested_by = :from_id
        """,
        {"u1": u1, "u2": u2, "from_id": from_user_id},
    )
    return conn is not None


# --- Endpoints ---


@router.get("/connections")
async def list_connections(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List all confirmed connections for current user."""
    user_id = current_user["id"]

    connections = await database.fetch_all(
        """
        SELECT
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path,
            c.responded_at as connected_at
        FROM connections c
        JOIN users u ON u.id = CASE
            WHEN c.user1_id = :user_id THEN c.user2_id
            ELSE c.user1_id
        END
        WHERE (c.user1_id = :user_id OR c.user2_id = :user_id)
          AND c.status = 'confirmed'
        ORDER BY c.responded_at DESC
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

    pending = await database.fetch_all(
        """
        SELECT
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path,
            c.requested_at as sent_at
        FROM connections c
        JOIN users u ON u.id = CASE
            WHEN c.user1_id = :user_id THEN c.user2_id
            ELSE c.user1_id
        END
        WHERE (c.user1_id = :user_id OR c.user2_id = :user_id)
          AND c.status = 'pending'
          AND c.requested_by = :user_id
        ORDER BY c.requested_at DESC
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

    pending = await database.fetch_all(
        """
        SELECT
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path,
            c.requested_at as received_at
        FROM connections c
        JOIN users u ON u.id = c.requested_by
        WHERE (c.user1_id = :user_id OR c.user2_id = :user_id)
          AND c.status = 'pending'
          AND c.requested_by != :user_id
        ORDER BY c.requested_at DESC
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
        SELECT COUNT(*) as count
        FROM connections
        WHERE (user1_id = :user_id OR user2_id = :user_id)
          AND status = 'pending'
          AND requested_by != :user_id
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
    u1, u2 = _order_user_ids(user_id, other_user_id)

    # Check existing connection
    existing = await _get_connection(user_id, other_user_id)

    if existing:
        if existing["status"] == "confirmed":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already connected")
        if existing["status"] == "pending" and existing["requested_by"] == user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You already have a pending request")
        if existing["status"] == "pending" and existing["requested_by"] != user_id:
            # They already sent us a request - auto-confirm
            await database.execute(
                """
                UPDATE connections
                SET status = 'confirmed', responded_at = NOW()
                WHERE user1_id = :u1 AND user2_id = :u2
                """,
                {"u1": u1, "u2": u2},
            )
            await notify_user(other_user["handle"], "connection_confirmed")
            return {"sent": True, "auto_confirmed": True}
        if existing["status"] == "ignored":
            # Update to pending with new requester
            await database.execute(
                """
                UPDATE connections
                SET status = 'pending', requested_by = :requester, requested_at = NOW(), responded_at = NULL
                WHERE user1_id = :u1 AND user2_id = :u2
                """,
                {"u1": u1, "u2": u2, "requester": user_id},
            )
            await notify_user(other_user["handle"], "new_connection_request")
            return {"sent": True}

    # Insert new connection request
    result = await database.fetch_one(
        """
        INSERT INTO connections (user1_id, user2_id, status, requested_by, requested_at)
        VALUES (:u1, :u2, 'pending', :requester, NOW())
        RETURNING requested_at
        """,
        {"u1": u1, "u2": u2, "requester": user_id},
    )

    await notify_user(other_user["handle"], "new_connection_request")

    return {
        "sent": True,
        "created_at": result["requested_at"].isoformat() if result["requested_at"] else None,
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
    u1, u2 = _order_user_ids(user_id, other_user_id)

    # Check for pending request from them
    existing = await _get_connection(user_id, other_user_id)

    if not existing or existing["status"] != "pending" or existing["requested_by"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending request to confirm")

    # Update to confirmed
    result = await database.fetch_one(
        """
        UPDATE connections
        SET status = 'confirmed', responded_at = NOW()
        WHERE user1_id = :u1 AND user2_id = :u2
        RETURNING responded_at
        """,
        {"u1": u1, "u2": u2},
    )

    await notify_user(other_user["handle"], "connection_confirmed")

    return {
        "confirmed": True,
        "created_at": result["responded_at"].isoformat() if result["responded_at"] else None,
    }


@router.post("/{handle}/ignore")
async def ignore_connection_request(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Ignore a pending connection request."""
    user_id = current_user["id"]

    other_user = await _get_user_by_handle(handle)
    if other_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    other_user_id = other_user["id"]
    u1, u2 = _order_user_ids(user_id, other_user_id)

    # Check for pending request from them
    existing = await _get_connection(user_id, other_user_id)

    if not existing or existing["status"] != "pending" or existing["requested_by"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending request to ignore")

    # Update to ignored
    await database.execute(
        """
        UPDATE connections
        SET status = 'ignored', responded_at = NOW()
        WHERE user1_id = :u1 AND user2_id = :u2
        """,
        {"u1": u1, "u2": u2},
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
    u1, u2 = _order_user_ids(user_id, other_user_id)

    # Check if connected
    existing = await _get_connection(user_id, other_user_id)

    if not existing or existing["status"] != "confirmed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not connected")

    # Delete the connection entirely
    await database.execute(
        """
        DELETE FROM connections
        WHERE user1_id = :u1 AND user2_id = :u2
        """,
        {"u1": u1, "u2": u2},
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
    u1, u2 = _order_user_ids(user_id, other_user_id)

    # Check for pending request from me
    existing = await _get_connection(user_id, other_user_id)

    if not existing or existing["status"] != "pending" or existing["requested_by"] != user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending request to withdraw")

    # Delete the pending request
    await database.execute(
        """
        DELETE FROM connections
        WHERE user1_id = :u1 AND user2_id = :u2
        """,
        {"u1": u1, "u2": u2},
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

    conn = await _get_connection(user_id, other_user_id)

    if not conn:
        return {
            "is_self": False,
            "is_connected": False,
            "pending_from_me": False,
            "pending_from_them": False,
        }

    return {
        "is_self": False,
        "is_connected": conn["status"] == "confirmed",
        "pending_from_me": conn["status"] == "pending" and conn["requested_by"] == user_id,
        "pending_from_them": conn["status"] == "pending" and conn["requested_by"] != user_id,
    }
