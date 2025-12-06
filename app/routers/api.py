import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user, hash_password, verify_password
from app.db import database
from app.ratelimit import rate_limit
from app.storage import (
    delete_avatar,
    delete_cover,
    generate_avatar_upload_url,
    generate_cover_upload_url,
    get_avatar_url,
    get_cover_url,
)

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


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class NotificationSettings(BaseModel):
    notify_mentions: bool


class AvatarUploadUrlRequest(BaseModel):
    content_type: str

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in ("image/jpeg", "image/png", "image/webp"):
            raise ValueError("Only JPEG, PNG, or WebP allowed")
        return v


class AvatarConfirmRequest(BaseModel):
    media_path: str

    @field_validator("media_path")
    @classmethod
    def validate_media_path(cls, v: str) -> str:
        if not v.startswith("avatars/") or not any(v.endswith(ext) for ext in (".jpg", ".png", ".webp")):
            raise ValueError("Invalid media path")
        return v


class CoverUploadUrlRequest(BaseModel):
    content_type: str

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in ("image/jpeg", "image/png", "image/webp"):
            raise ValueError("Only JPEG, PNG, or WebP allowed")
        return v


class CoverConfirmRequest(BaseModel):
    media_path: str

    @field_validator("media_path")
    @classmethod
    def validate_media_path(cls, v: str) -> str:
        if not v.startswith("covers/") or not any(v.endswith(ext) for ext in (".jpg", ".png", ".webp")):
            raise ValueError("Invalid media path")
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
    cover_path = current_user["cover_path"]
    return {
        "id": current_user["id"],
        "handle": current_user["handle"],
        "email": current_user["email"],
        "first_name": current_user["first_name"],
        "middle_name": current_user["middle_name"],
        "last_name": current_user["last_name"],
        "headline": current_user["headline"],
        "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
        "cover_url": get_cover_url(cover_path) if cover_path else None,
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
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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


@router.post("/me/avatar/upload-url")
async def get_avatar_upload_url(
    payload: AvatarUploadUrlRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get presigned URL for direct avatar upload to R2."""
    result = generate_avatar_upload_url(current_user["id"], payload.content_type)
    return {"upload_url": result["upload_url"], "media_path": result["media_path"]}


@router.post("/me/avatar/confirm")
async def confirm_avatar_upload(
    payload: AvatarConfirmRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm avatar upload after direct R2 upload."""
    old_avatar_path = current_user["avatar_path"]

    # Delete old avatar only after confirming new one
    if old_avatar_path:
        delete_avatar(old_avatar_path)

    await database.execute(
        "UPDATE users SET avatar_path = :path, updated_at = NOW() WHERE id = :id",
        {"path": payload.media_path, "id": current_user["id"]},
    )

    return {"avatar_url": get_avatar_url(payload.media_path)}


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


@router.post("/me/password")
async def change_my_password(
    payload: PasswordChange,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Change user password."""
    user_id = current_user["id"]

    # Get current password hash
    user = await database.fetch_one(
        "SELECT password_hash FROM users WHERE id = :id",
        {"id": user_id},
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Verify current password
    if not verify_password(payload.current_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    new_hash = hash_password(payload.new_password)
    await database.execute(
        "UPDATE users SET password_hash = :hash, updated_at = NOW() WHERE id = :id",
        {"hash": new_hash, "id": user_id},
    )

    return {"message": "Password changed"}


@router.post("/me/cover/upload-url")
async def get_cover_upload_url(
    payload: CoverUploadUrlRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get presigned URL for direct cover upload to R2."""
    result = generate_cover_upload_url(current_user["id"], payload.content_type)
    return {"upload_url": result["upload_url"], "media_path": result["media_path"]}


@router.post("/me/cover/confirm")
async def confirm_cover_upload(
    payload: CoverConfirmRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm cover upload after direct R2 upload."""
    old_cover_path = current_user["cover_path"]

    # Delete old cover only after confirming new one
    if old_cover_path:
        delete_cover(old_cover_path)

    await database.execute(
        "UPDATE users SET cover_path = :path, updated_at = NOW() WHERE id = :id",
        {"path": payload.media_path, "id": current_user["id"]},
    )

    return {"cover_url": get_cover_url(payload.media_path)}


@router.delete("/me/cover")
async def delete_my_cover(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete cover image."""
    if current_user["cover_path"]:
        delete_cover(current_user["cover_path"])

    await database.execute(
        "UPDATE users SET cover_path = NULL, updated_at = NOW() WHERE id = :id",
        {"id": current_user["id"]},
    )

    return {"message": "Cover deleted"}


@router.get("/me/notifications")
async def get_notification_settings(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get notification settings."""
    user_id = current_user["id"]

    user = await database.fetch_one(
        "SELECT notify_mentions FROM users WHERE id = :id",
        {"id": user_id},
    )

    return {
        "notify_mentions": user["notify_mentions"] if user else False,
    }


@router.patch("/me/notifications")
async def update_notification_settings(
    payload: NotificationSettings,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update notification settings."""
    user_id = current_user["id"]

    await database.execute(
        "UPDATE users SET notify_mentions = :notify_mentions, updated_at = NOW() WHERE id = :id",
        {"notify_mentions": payload.notify_mentions, "id": user_id},
    )

    return {"notify_mentions": payload.notify_mentions}


@router.get("/search")
async def search_users(
    q: str,
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """Search users and pages by name, handle, or headline."""
    if len(q) < 2:
        return []

    q_lower = q.lower()

    # Search users
    users = await database.fetch_all(
        """
        SELECT handle, first_name, middle_name, last_name, headline, avatar_path
        FROM users
        WHERE verified = TRUE
          AND (
            handle ILIKE '%' || :q || '%'
            OR first_name ILIKE '%' || :q || '%'
            OR last_name ILIKE '%' || :q || '%'
            OR headline ILIKE '%' || :q || '%'
            OR :q_lower = ANY(SELECT LOWER(unnest(skills)))
          )
        LIMIT 8
        """,
        {"q": q, "q_lower": q_lower},
    )

    # Search pages
    pages = await database.fetch_all(
        """
        SELECT handle, name, kind, headline, icon_path
        FROM pages
        WHERE handle ILIKE '%' || :q || '%'
           OR name ILIKE '%' || :q || '%'
           OR headline ILIKE '%' || :q || '%'
        LIMIT 5
        """,
        {"q": q},
    )

    results = []

    # Add user results
    for user in users:
        first_name = user["first_name"] or ""
        middle_name = user["middle_name"]
        last_name = user["last_name"] or ""
        full_name = (
            f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
            if middle_name
            else f"{first_name} {last_name}".strip()
        )
        avatar_path = user["avatar_path"]
        results.append({
            "type": "user",
            "handle": user["handle"],
            "name": full_name,
            "headline": user["headline"],
            "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
        })

    # Add page results
    for page in pages:
        icon_path = page["icon_path"]
        results.append({
            "type": "page",
            "handle": page["handle"],
            "name": page["name"],
            "kind": page["kind"],
            "headline": page["headline"],
            "icon_url": get_avatar_url(icon_path) if icon_path else None,
        })

    return results


@router.get("/u/{handle}")
async def get_public_profile(handle: str) -> dict:
    """Get public profile by handle."""
    user = await database.fetch_one(
        """
        SELECT handle, first_name, middle_name, last_name, headline, avatar_path, cover_path, skills
        FROM users WHERE handle = :handle
        """,
        {"handle": handle.lower()},
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    avatar_path = user["avatar_path"]
    cover_path = user["cover_path"]
    first_name = user["first_name"] or ""
    middle_name = user["middle_name"]
    last_name = user["last_name"] or ""
    full_name = f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip() if middle_name else f"{first_name} {last_name}".strip()

    return {
        "handle": user["handle"],
        "name": full_name,
        "headline": user["headline"],
        "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
        "cover_url": get_cover_url(cover_path) if cover_path else None,
        "skills": user["skills"],
    }
