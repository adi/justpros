from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.db import database
from app.ratelimit import rate_limit
from app.storage import get_avatar_url

router = APIRouter(prefix="/api/connections", tags=["connections"])

# Time decay constant: exp(-lambda * days) where lambda = ln(2) / half_life_days
# 3 year half-life = 1095 days -> lambda = 0.000633
# We use this as a SQL literal since parameter binding has type issues


class ConnectionCreate(BaseModel):
    to_handle: str
    subject: str
    body: str | None = None

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3 or len(v) > 100:
            raise ValueError("Subject must be 3-100 characters")
        return v

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 2000:
            raise ValueError("Body must be at most 2000 characters")
        return v if v else None


class ConnectionVote(BaseModel):
    vote: int

    @field_validator("vote")
    @classmethod
    def validate_vote(cls, v: int) -> int:
        if v not in (1, -1):
            raise ValueError("Vote must be 1 or -1")
        return v


class AbuseReport(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10 or len(v) > 500:
            raise ValueError("Reason must be 10-500 characters")
        return v


def _format_user_name(user: dict) -> str:
    """Format user's full name from first/middle/last."""
    first_name = user.get("first_name") or ""
    middle_name = user.get("middle_name")
    last_name = user.get("last_name") or ""
    if middle_name:
        return f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
    return f"{first_name} {last_name}".strip()


async def _check_rate_limits(from_user_id: int, to_user_id: int) -> None:
    """Check per-pair and global rate limits for connection claims."""
    # Check per-pair limit (3/day)
    pair_count = await database.fetch_one(
        """
        SELECT COUNT(*) as count FROM connection_claims_log
        WHERE from_user_id = :from_id AND to_user_id = :to_id
          AND created_at > NOW() - INTERVAL '1 day'
        """,
        {"from_id": from_user_id, "to_id": to_user_id},
    )
    if pair_count and pair_count["count"] >= 3:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many connection attempts to this user today",
        )

    # Check global limit (100/day)
    global_count = await database.fetch_one(
        """
        SELECT COUNT(*) as count FROM connection_claims_log
        WHERE from_user_id = :from_id
          AND created_at > NOW() - INTERVAL '1 day'
        """,
        {"from_id": from_user_id},
    )
    if global_count and global_count["count"] >= 100:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily connection limit reached",
        )


async def _log_claim_attempt(from_user_id: int, to_user_id: int) -> None:
    """Log a claim attempt for rate limiting."""
    await database.execute(
        """
        INSERT INTO connection_claims_log (from_user_id, to_user_id)
        VALUES (:from_id, :to_id)
        """,
        {"from_id": from_user_id, "to_id": to_user_id},
    )


async def _check_karma(user_id: int) -> None:
    """Check if user has enough karma to create connections."""
    user = await database.fetch_one(
        "SELECT karma_points, karma_last_regen FROM users WHERE id = :id",
        {"id": user_id},
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Regenerate karma if needed (1 point per month, max 15)
    await database.execute(
        """
        UPDATE users
        SET karma_points = LEAST(15, karma_points +
            FLOOR(EXTRACT(EPOCH FROM (NOW() - karma_last_regen)) / 2592000)::INTEGER),
            karma_last_regen = NOW()
        WHERE id = :id
          AND karma_last_regen < NOW() - INTERVAL '30 days'
        """,
        {"id": user_id},
    )

    # Re-fetch after potential update
    user = await database.fetch_one(
        "SELECT karma_points FROM users WHERE id = :id",
        {"id": user_id},
    )
    if user and user["karma_points"] <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account restricted due to low karma",
        )


@router.post("")
@rate_limit(max_requests=30, window_seconds=60)
async def create_connection(
    request: Request,
    payload: ConnectionCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a connection claim to another user."""
    from_user_id = current_user["id"]

    # Check karma
    await _check_karma(from_user_id)

    # Get target user
    target_user = await database.fetch_one(
        "SELECT id FROM users WHERE handle = :handle",
        {"handle": payload.to_handle.lower()},
    )
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    to_user_id = target_user["id"]

    if from_user_id == to_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot connect to yourself",
        )

    # Check rate limits (3/day per pair, 100/day global)
    await _check_rate_limits(from_user_id, to_user_id)

    # Log the attempt for rate limiting
    await _log_claim_attempt(from_user_id, to_user_id)

    # Create the connection
    result = await database.fetch_one(
        """
        INSERT INTO connections (from_user_id, to_user_id, subject, body)
        VALUES (:from_id, :to_id, :subject, :body)
        RETURNING id
        """,
        {
            "from_id": from_user_id,
            "to_id": to_user_id,
            "subject": payload.subject,
            "body": payload.body,
        },
    )

    return {"id": result["id"], "message": "Connection request sent"}


@router.get("")
async def list_my_connections(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List current user's confirmed connections, ordered by power."""
    user_id = current_user["id"]

    connections = await database.fetch_all(
        """
        SELECT
            c.id,
            c.from_user_id,
            c.to_user_id,
            c.subject,
            c.body,
            c.created_at,
            u_from.handle as from_handle,
            u_from.first_name as from_first_name,
            u_from.middle_name as from_middle_name,
            u_from.last_name as from_last_name,
            u_from.headline as from_headline,
            u_from.avatar_path as from_avatar_path,
            u_to.handle as to_handle,
            u_to.first_name as to_first_name,
            u_to.middle_name as to_middle_name,
            u_to.last_name as to_last_name,
            u_to.headline as to_headline,
            u_to.avatar_path as to_avatar_path,
            (
                EXP(-0.000633 * EXTRACT(EPOCH FROM (NOW() - c.created_at)) / 86400.0)
                * (1.0 + COALESCE(v.vote_sum, 0)::REAL * 0.1)
                * (u_from.trustworthiness + u_to.trustworthiness) / 2.0
            ) AS power
        FROM connections c
        JOIN users u_from ON c.from_user_id = u_from.id
        JOIN users u_to ON c.to_user_id = u_to.id
        LEFT JOIN (
            SELECT connection_id, SUM(vote) AS vote_sum
            FROM connection_votes
            GROUP BY connection_id
        ) v ON v.connection_id = c.id
        WHERE c.status = 'confirmed'
          AND (c.from_user_id = :user_id OR c.to_user_id = :user_id)
        ORDER BY power DESC
        """,
        {"user_id": user_id},
    )

    results = []
    for conn in connections:
        # Determine which user is "the other person"
        if conn["from_user_id"] == user_id:
            other = {
                "handle": conn["to_handle"],
                "first_name": conn["to_first_name"],
                "middle_name": conn["to_middle_name"],
                "last_name": conn["to_last_name"],
                "headline": conn["to_headline"],
                "avatar_path": conn["to_avatar_path"],
            }
        else:
            other = {
                "handle": conn["from_handle"],
                "first_name": conn["from_first_name"],
                "middle_name": conn["from_middle_name"],
                "last_name": conn["from_last_name"],
                "headline": conn["from_headline"],
                "avatar_path": conn["from_avatar_path"],
            }

        avatar_path = other["avatar_path"]
        results.append({
            "id": conn["id"],
            "handle": other["handle"],
            "name": _format_user_name(other),
            "headline": other["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
            "subject": conn["subject"],
            "body": conn["body"],
            "created_at": conn["created_at"].isoformat() if conn["created_at"] else None,
        })

    return results


@router.get("/pending")
async def list_pending_connections(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List connection claims awaiting current user's confirmation."""
    user_id = current_user["id"]

    # First, auto-ignore stale claims older than 30 days
    await database.execute(
        """
        UPDATE connections
        SET status = 'ignored', ignored_at = NOW()
        WHERE status = 'pending'
          AND to_user_id = :user_id
          AND created_at < NOW() - INTERVAL '30 days'
        """,
        {"user_id": user_id},
    )

    connections = await database.fetch_all(
        """
        SELECT
            c.id,
            c.subject,
            c.body,
            c.created_at,
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path
        FROM connections c
        JOIN users u ON c.from_user_id = u.id
        WHERE c.to_user_id = :user_id
          AND c.status = 'pending'
        ORDER BY c.created_at DESC
        """,
        {"user_id": user_id},
    )

    results = []
    for conn in connections:
        avatar_path = conn["avatar_path"]
        results.append({
            "id": conn["id"],
            "handle": conn["handle"],
            "name": _format_user_name(dict(conn)),
            "headline": conn["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
            "subject": conn["subject"],
            "body": conn["body"],
            "created_at": conn["created_at"].isoformat() if conn["created_at"] else None,
        })

    return results


@router.get("/ignored")
async def list_ignored_connections(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List ignored connection claims for review/late confirmation."""
    user_id = current_user["id"]

    connections = await database.fetch_all(
        """
        SELECT
            c.id,
            c.subject,
            c.body,
            c.created_at,
            c.ignored_at,
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path
        FROM connections c
        JOIN users u ON c.from_user_id = u.id
        WHERE c.to_user_id = :user_id
          AND c.status = 'ignored'
        ORDER BY c.ignored_at DESC
        """,
        {"user_id": user_id},
    )

    results = []
    for conn in connections:
        avatar_path = conn["avatar_path"]
        results.append({
            "id": conn["id"],
            "handle": conn["handle"],
            "name": _format_user_name(dict(conn)),
            "headline": conn["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
            "subject": conn["subject"],
            "body": conn["body"],
            "created_at": conn["created_at"].isoformat() if conn["created_at"] else None,
            "ignored_at": conn["ignored_at"].isoformat() if conn["ignored_at"] else None,
        })

    return results


@router.get("/confirmed-received")
async def list_confirmed_received_connections(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List claims I've confirmed (where I was the receiver)."""
    user_id = current_user["id"]

    connections = await database.fetch_all(
        """
        SELECT
            c.id,
            c.subject,
            c.body,
            c.created_at,
            c.confirmed_at,
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path
        FROM connections c
        JOIN users u ON c.from_user_id = u.id
        WHERE c.to_user_id = :user_id
          AND c.status = 'confirmed'
        ORDER BY c.confirmed_at DESC
        """,
        {"user_id": user_id},
    )

    results = []
    for conn in connections:
        avatar_path = conn["avatar_path"]
        results.append({
            "id": conn["id"],
            "handle": conn["handle"],
            "name": _format_user_name(dict(conn)),
            "headline": conn["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
            "subject": conn["subject"],
            "body": conn["body"],
            "created_at": conn["created_at"].isoformat() if conn["created_at"] else None,
            "confirmed_at": conn["confirmed_at"].isoformat() if conn["confirmed_at"] else None,
        })

    return results


@router.get("/sent")
async def list_sent_connections(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List connection claims sent by current user."""
    user_id = current_user["id"]

    connections = await database.fetch_all(
        """
        SELECT
            c.id,
            c.subject,
            c.body,
            c.status,
            c.created_at,
            u.handle,
            u.first_name,
            u.middle_name,
            u.last_name,
            u.headline,
            u.avatar_path
        FROM connections c
        JOIN users u ON c.to_user_id = u.id
        WHERE c.from_user_id = :user_id
        ORDER BY c.created_at DESC
        """,
        {"user_id": user_id},
    )

    results = []
    for conn in connections:
        avatar_path = conn["avatar_path"]
        results.append({
            "id": conn["id"],
            "handle": conn["handle"],
            "name": _format_user_name(dict(conn)),
            "headline": conn["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
            "subject": conn["subject"],
            "body": conn["body"],
            "status": conn["status"],
            "created_at": conn["created_at"].isoformat() if conn["created_at"] else None,
        })

    return results


@router.post("/{connection_id}/confirm")
async def confirm_connection(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm a pending or ignored connection claim."""
    user_id = current_user["id"]

    conn = await database.fetch_one(
        """
        SELECT id, to_user_id, status FROM connections
        WHERE id = :id
        """,
        {"id": connection_id},
    )

    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    if conn["to_user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the target user can confirm",
        )

    if conn["status"] == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection already confirmed",
        )

    await database.execute(
        """
        UPDATE connections
        SET status = 'confirmed', confirmed_at = NOW(), ignored_at = NULL
        WHERE id = :id
        """,
        {"id": connection_id},
    )

    return {"message": "Connection confirmed"}


@router.post("/{connection_id}/ignore")
async def ignore_connection(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Ignore a pending or confirmed connection claim."""
    user_id = current_user["id"]

    conn = await database.fetch_one(
        """
        SELECT id, to_user_id, status FROM connections
        WHERE id = :id
        """,
        {"id": connection_id},
    )

    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    if conn["to_user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the target user can ignore",
        )

    if conn["status"] == "ignored":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection already ignored",
        )

    await database.execute(
        """
        UPDATE connections
        SET status = 'ignored', ignored_at = NOW(), confirmed_at = NULL
        WHERE id = :id
        """,
        {"id": connection_id},
    )

    return {"message": "Connection ignored"}


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a connection I created."""
    user_id = current_user["id"]

    conn = await database.fetch_one(
        """
        SELECT id, from_user_id, to_user_id FROM connections
        WHERE id = :id
        """,
        {"id": connection_id},
    )

    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    if conn["from_user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator can delete",
        )

    # Delete the connection
    await database.execute(
        "DELETE FROM connections WHERE id = :id",
        {"id": connection_id},
    )

    # Also remove one rate limit log entry so user can send again
    await database.execute(
        """
        DELETE FROM connection_claims_log
        WHERE id = (
            SELECT id FROM connection_claims_log
            WHERE from_user_id = :from_id AND to_user_id = :to_id
            ORDER BY created_at DESC
            LIMIT 1
        )
        """,
        {"from_id": user_id, "to_id": conn["to_user_id"]},
    )

    return {"message": "Connection deleted"}


@router.get("/u/{handle}")
async def get_user_connections(handle: str) -> list[dict]:
    """
    Get public connections for a user by handle.
    Returns connections grouped by other user, with all confirmed claims.
    """
    user = await database.fetch_one(
        "SELECT id FROM users WHERE handle = :handle",
        {"handle": handle.lower()},
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user_id = user["id"]

    connections = await database.fetch_all(
        """
        SELECT
            c.id,
            c.from_user_id,
            c.to_user_id,
            c.subject,
            c.body,
            c.created_at,
            u_from.handle as from_handle,
            u_from.first_name as from_first_name,
            u_from.middle_name as from_middle_name,
            u_from.last_name as from_last_name,
            u_from.headline as from_headline,
            u_from.avatar_path as from_avatar_path,
            u_to.handle as to_handle,
            u_to.first_name as to_first_name,
            u_to.middle_name as to_middle_name,
            u_to.last_name as to_last_name,
            u_to.headline as to_headline,
            u_to.avatar_path as to_avatar_path,
            (
                EXP(-0.000633 * EXTRACT(EPOCH FROM (NOW() - c.created_at)) / 86400.0)
                * (1.0 + COALESCE(v.vote_sum, 0)::REAL * 0.1)
                * (u_from.trustworthiness + u_to.trustworthiness) / 2.0
            ) AS power
        FROM connections c
        JOIN users u_from ON c.from_user_id = u_from.id
        JOIN users u_to ON c.to_user_id = u_to.id
        LEFT JOIN (
            SELECT connection_id, SUM(vote) AS vote_sum
            FROM connection_votes
            GROUP BY connection_id
        ) v ON v.connection_id = c.id
        WHERE c.status = 'confirmed'
          AND (c.from_user_id = :user_id OR c.to_user_id = :user_id)
        ORDER BY power DESC
        """,
        {"user_id": user_id},
    )

    # Group claims by the other user
    grouped: dict[str, dict] = {}
    for conn in connections:
        # Determine which user is "the other person"
        if conn["from_user_id"] == user_id:
            other_handle = conn["to_handle"]
            other = {
                "handle": conn["to_handle"],
                "first_name": conn["to_first_name"],
                "middle_name": conn["to_middle_name"],
                "last_name": conn["to_last_name"],
                "headline": conn["to_headline"],
                "avatar_path": conn["to_avatar_path"],
            }
            from_me = True
        else:
            other_handle = conn["from_handle"]
            other = {
                "handle": conn["from_handle"],
                "first_name": conn["from_first_name"],
                "middle_name": conn["from_middle_name"],
                "last_name": conn["from_last_name"],
                "headline": conn["from_headline"],
                "avatar_path": conn["from_avatar_path"],
            }
            from_me = False

        # Create entry for this user if not exists
        if other_handle not in grouped:
            avatar_path = other["avatar_path"]
            grouped[other_handle] = {
                "handle": other_handle,
                "name": _format_user_name(other),
                "headline": other["headline"],
                "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
                "claims": [],
                "max_power": conn["power"],  # Track highest power for sorting
            }

        # Add this claim
        grouped[other_handle]["claims"].append({
            "id": conn["id"],
            "subject": conn["subject"],
            "body": conn["body"],
            "from_me": from_me,
            "created_at": conn["created_at"].isoformat() if conn["created_at"] else None,
        })

    # Convert to list, sorted by max_power (highest first)
    results = sorted(grouped.values(), key=lambda x: x["max_power"], reverse=True)

    # Remove max_power from output (internal only)
    for r in results:
        del r["max_power"]

    return results


async def _can_vote_on_connection(voter_id: int, from_user_id: int, to_user_id: int) -> bool:
    """Check if voter has confirmed connections with both parties."""
    result = await database.fetch_one(
        """
        SELECT
            EXISTS (
                SELECT 1 FROM connections
                WHERE status = 'confirmed'
                  AND ((from_user_id = :voter_id AND to_user_id = :from_user_id)
                       OR (from_user_id = :from_user_id AND to_user_id = :voter_id))
            ) AND EXISTS (
                SELECT 1 FROM connections
                WHERE status = 'confirmed'
                  AND ((from_user_id = :voter_id AND to_user_id = :to_user_id)
                       OR (from_user_id = :to_user_id AND to_user_id = :voter_id))
            ) AS can_vote
        """,
        {"voter_id": voter_id, "from_user_id": from_user_id, "to_user_id": to_user_id},
    )
    return bool(result and result["can_vote"])


@router.post("/{connection_id}/vote")
async def vote_on_connection(
    connection_id: int,
    payload: ConnectionVote,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Vote on a connection's credibility (must be mutual connection of both parties)."""
    voter_id = current_user["id"]

    conn = await database.fetch_one(
        """
        SELECT id, from_user_id, to_user_id, status FROM connections
        WHERE id = :id
        """,
        {"id": connection_id},
    )

    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    if conn["status"] != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only vote on confirmed connections",
        )

    # Can't vote on your own connection
    if voter_id in (conn["from_user_id"], conn["to_user_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot vote on your own connection",
        )

    # Check vote eligibility
    can_vote = await _can_vote_on_connection(voter_id, conn["from_user_id"], conn["to_user_id"])
    if not can_vote:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be connected to both parties to vote",
        )

    # Upsert the vote
    await database.execute(
        """
        INSERT INTO connection_votes (connection_id, voter_id, vote)
        VALUES (:connection_id, :voter_id, :vote)
        ON CONFLICT (connection_id, voter_id)
        DO UPDATE SET vote = :vote, created_at = NOW()
        """,
        {"connection_id": connection_id, "voter_id": voter_id, "vote": payload.vote},
    )

    # Update trustworthiness of the claimant (from_user_id)
    await database.execute(
        """
        UPDATE users
        SET trustworthiness = LEAST(2.0, GREATEST(0.1, trustworthiness + :delta))
        WHERE id = :user_id
        """,
        {"user_id": conn["from_user_id"], "delta": 0.01 * payload.vote},
    )

    return {"message": "Vote recorded"}


@router.delete("/{connection_id}/vote")
async def remove_vote(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Remove vote on a connection."""
    voter_id = current_user["id"]

    # Get current vote to reverse trustworthiness effect
    vote = await database.fetch_one(
        """
        SELECT vote FROM connection_votes
        WHERE connection_id = :connection_id AND voter_id = :voter_id
        """,
        {"connection_id": connection_id, "voter_id": voter_id},
    )

    if vote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vote not found")

    # Get the connection to reverse trustworthiness
    conn = await database.fetch_one(
        "SELECT from_user_id FROM connections WHERE id = :id",
        {"id": connection_id},
    )

    # Reverse the trustworthiness effect
    if conn:
        await database.execute(
            """
            UPDATE users
            SET trustworthiness = LEAST(2.0, GREATEST(0.1, trustworthiness - :delta))
            WHERE id = :user_id
            """,
            {"user_id": conn["from_user_id"], "delta": 0.01 * vote["vote"]},
        )

    # Delete the vote
    await database.execute(
        """
        DELETE FROM connection_votes
        WHERE connection_id = :connection_id AND voter_id = :voter_id
        """,
        {"connection_id": connection_id, "voter_id": voter_id},
    )

    return {"message": "Vote removed"}


@router.post("/{connection_id}/report")
@rate_limit(max_requests=10, window_seconds=86400)  # 10 reports per day
async def report_connection(
    request: Request,
    connection_id: int,
    payload: AbuseReport,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Report a connection for abuse (triggers async LLM evaluation)."""
    reporter_id = current_user["id"]

    conn = await database.fetch_one(
        """
        SELECT id, from_user_id, status FROM connections
        WHERE id = :id
        """,
        {"id": connection_id},
    )

    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    # Check if already reported by this user
    existing = await database.fetch_one(
        """
        SELECT id FROM abuse_reports
        WHERE reporter_id = :reporter_id AND connection_id = :connection_id
          AND status = 'pending'
        """,
        {"reporter_id": reporter_id, "connection_id": connection_id},
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already reported this connection",
        )

    # Create the report
    await database.execute(
        """
        INSERT INTO abuse_reports (reporter_id, reported_user_id, connection_id, reason)
        VALUES (:reporter_id, :reported_user_id, :connection_id, :reason)
        """,
        {
            "reporter_id": reporter_id,
            "reported_user_id": conn["from_user_id"],
            "connection_id": connection_id,
            "reason": payload.reason,
        },
    )

    # TODO: Trigger async LLM evaluation here
    # For now, reports are created but not automatically evaluated

    return {"message": "Report submitted"}


@router.get("/status/{handle}")
async def get_connection_status(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Get aggregate connection status between current user and another user.
    Supports multiple claims per pair.
    """
    user_id = current_user["id"]

    target = await database.fetch_one(
        "SELECT id FROM users WHERE handle = :handle",
        {"handle": handle.lower()},
    )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    target_id = target["id"]

    if user_id == target_id:
        return {"status": "self"}

    # Get all claims between these users (both directions)
    all_claims = await database.fetch_all(
        """
        SELECT id, from_user_id, to_user_id, subject, body, status, created_at
        FROM connections
        WHERE (from_user_id = :user_id AND to_user_id = :target_id)
           OR (from_user_id = :target_id AND to_user_id = :user_id)
        ORDER BY created_at DESC
        """,
        {"user_id": user_id, "target_id": target_id},
    )

    # Check if connected (any confirmed claim in either direction)
    is_connected = any(c["status"] == "confirmed" for c in all_claims)

    # Count claims I sent
    my_claims = [c for c in all_claims if c["from_user_id"] == user_id]
    pending_sent_count = sum(1 for c in my_claims if c["status"] in ("pending", "ignored"))
    confirmed_sent_count = sum(1 for c in my_claims if c["status"] == "confirmed")

    # Get claims they sent me that are pending (not ignored - those are hidden)
    pending_received = [
        {
            "id": c["id"],
            "subject": c["subject"],
            "body": c["body"],
            "created_at": c["created_at"].isoformat() if c["created_at"] else None,
        }
        for c in all_claims
        if c["from_user_id"] == target_id and c["status"] == "pending"
    ]

    # Check rate limit (claims today to this target)
    claims_today_result = await database.fetch_one(
        """
        SELECT COUNT(*) as count FROM connection_claims_log
        WHERE from_user_id = :from_id AND to_user_id = :to_id
          AND created_at > NOW() - INTERVAL '1 day'
        """,
        {"from_id": user_id, "to_id": target_id},
    )
    claims_today = claims_today_result["count"] if claims_today_result else 0
    can_send_more = claims_today < 3

    return {
        "is_connected": is_connected,
        "pending_sent_count": pending_sent_count,
        "confirmed_sent_count": confirmed_sent_count,
        "claims_today": claims_today,
        "can_send_more": can_send_more,
        "pending_received": pending_received,
    }
