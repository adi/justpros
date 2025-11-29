import re

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.db import database
from app.ratelimit import rate_limit
from app.storage import delete_avatar, get_avatar_url, upload_avatar

router = APIRouter(prefix="/api", tags=["api"])

HANDLE_PATTERN = re.compile(r"^[a-z0-9_]+$")


class ProfileUpdate(BaseModel):
    handle: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
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
    avatar_path = current_user["avatar_path"]
    return {
        "id": current_user["id"],
        "handle": current_user["handle"],
        "email": current_user["email"],
        "first_name": current_user["first_name"],
        "middle_name": current_user["middle_name"],
        "last_name": current_user["last_name"],
        "headline": current_user["headline"],
        "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
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
    if payload.first_name is not None:
        updates["first_name"] = payload.first_name
    if payload.middle_name is not None:
        updates["middle_name"] = payload.middle_name if payload.middle_name else None
    if payload.last_name is not None:
        updates["last_name"] = payload.last_name
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
        SELECT handle, email, first_name, middle_name, last_name, headline, avatar_path, skills, created_at
        FROM users WHERE id = :id
        """,
        {"id": user_id},
    )

    # TODO: Add posts when that table exists
    # posts = await database.fetch_all(
    #     "SELECT content, created_at FROM posts WHERE user_id = :id ORDER BY created_at",
    #     {"id": user_id},
    # )

    avatar_path = user["avatar_path"]
    return {
        "profile": {
            "handle": user["handle"],
            "email": user["email"],
            "first_name": user["first_name"],
            "middle_name": user["middle_name"],
            "last_name": user["last_name"],
            "headline": user["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
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


@router.post("/me/avatar")
async def upload_my_avatar(
    file: UploadFile,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Upload avatar image."""
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only JPEG, PNG, or WebP allowed",
        )

    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large (max 2MB)",
        )

    old_avatar_path = current_user["avatar_path"]
    avatar_path = upload_avatar(current_user["id"], contents, file.content_type)

    # Delete old avatar only after successful upload
    if old_avatar_path:
        delete_avatar(old_avatar_path)

    await database.execute(
        "UPDATE users SET avatar_path = :path, updated_at = NOW() WHERE id = :id",
        {"path": avatar_path, "id": current_user["id"]},
    )

    return {"avatar_url": get_avatar_url(avatar_path)}


@router.delete("/me/avatar")
async def delete_my_avatar(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete avatar image."""
    if current_user["avatar_path"]:
        delete_avatar(current_user["avatar_path"])

    await database.execute(
        "UPDATE users SET avatar_path = NULL, updated_at = NOW() WHERE id = :id",
        {"id": current_user["id"]},
    )

    return {"message": "Avatar deleted"}
