import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.db import database
from app.ratelimit import rate_limit

router = APIRouter(prefix="/api", tags=["api"])

HANDLE_PATTERN = re.compile(r"^[a-z0-9_]+$")


class ProfileUpdate(BaseModel):
    handle: str | None = None
    name: str | None = None
    headline: str | None = None
    skills: list[str] | None = None

    @field_validator("handle")
    @classmethod
    def validate_handle(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.lower()
        if len(v) < 3 or len(v) > 30:
            raise ValueError("Handle must be 3-30 characters")
        if not HANDLE_PATTERN.match(v):
            raise ValueError("Handle can only contain lowercase letters, numbers, and underscores")
        return v


@router.get("/handle/check")
@rate_limit(max_requests=10, window_seconds=60)
async def check_handle_availability(
    request: Request,
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Check if a handle is available."""
    handle = handle.lower()

    if len(handle) < 3 or len(handle) > 30:
        return {"available": False, "reason": "Handle must be 3-30 characters"}

    if not HANDLE_PATTERN.match(handle):
        return {"available": False, "reason": "Invalid characters"}

    existing = await database.fetch_one(
        "SELECT id FROM users WHERE handle = :handle",
        {"handle": handle},
    )

    if existing and existing["id"] != current_user["id"]:
        return {"available": False}

    return {"available": True}


@router.get("/me")
async def get_my_profile(current_user: dict = Depends(get_current_user)) -> dict:
    """Get current user profile."""
    return {
        "id": current_user["id"],
        "handle": current_user["handle"],
        "email": current_user["email"],
        "name": current_user["name"],
        "headline": current_user["headline"],
        "avatar_url": current_user["avatar_url"],
        "skills": current_user["skills"],
    }


@router.patch("/me")
async def update_my_profile(
    payload: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update current user profile."""
    user_id = current_user["id"]

    updates = {}
    if payload.handle is not None and payload.handle != current_user["handle"]:
        # Check if handle is taken
        existing = await database.fetch_one(
            "SELECT id FROM users WHERE handle = :handle AND id != :id",
            {"handle": payload.handle, "id": user_id},
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Handle already taken",
            )
        updates["handle"] = payload.handle
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.headline is not None:
        updates["headline"] = payload.headline
    if payload.skills is not None:
        updates["skills"] = payload.skills

    if updates:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = user_id
        await database.execute(
            f"UPDATE users SET {set_clause}, updated_at = NOW() WHERE id = :id",
            updates,
        )

    return {"message": "Profile updated"}


@router.get("/me/export")
async def export_my_data(current_user: dict = Depends(get_current_user)) -> dict:
    """Export all user data as JSON."""
    user_id = current_user["id"]

    # Get full user profile
    user = await database.fetch_one(
        """
        SELECT handle, email, name, headline, avatar_url, skills, created_at
        FROM users WHERE id = :id
        """,
        {"id": user_id},
    )

    # TODO: Add posts when that table exists
    # posts = await database.fetch_all(
    #     "SELECT content, created_at FROM posts WHERE user_id = :id ORDER BY created_at",
    #     {"id": user_id},
    # )

    return {
        "profile": {
            "handle": user["handle"],
            "email": user["email"],
            "name": user["name"],
            "headline": user["headline"],
            "avatar_url": user["avatar_url"],
            "skills": user["skills"],
            "created_at": user["created_at"].isoformat() if user["created_at"] else None,
        },
        # "posts": [{"content": p["content"], "created_at": p["created_at"].isoformat()} for p in posts],
    }


@router.delete("/me")
async def delete_my_account(current_user: dict = Depends(get_current_user)) -> dict:
    """Permanently delete user account and all associated data."""
    user_id = current_user["id"]

    # TODO: Delete posts when that table exists
    # await database.execute("DELETE FROM posts WHERE user_id = :id", {"id": user_id})

    await database.execute("DELETE FROM users WHERE id = :id", {"id": user_id})

    return {"message": "Account deleted"}
