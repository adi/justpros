import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user
from app.db import database
from app.routers.messages import notify_user
from app.storage import (
    delete_page_cover,
    delete_page_icon,
    generate_page_cover_upload_url,
    generate_page_icon_upload_url,
    get_avatar_url,
)

router = APIRouter(prefix="/api/pages", tags=["page_api"])

# Valid page kinds
PAGE_KINDS = ("company", "event", "product", "community", "virtual")


# --- Pydantic Models ---


class PageCreate(BaseModel):
    handle: str
    name: str
    kind: str = "company"
    headline: str | None = None

    @field_validator("handle")
    @classmethod
    def validate_handle(cls, v: str) -> str:
        v = v.lower().strip()
        if not re.match(r"^[a-z0-9_]+$", v):
            raise ValueError("Handle can only contain lowercase letters, numbers, and underscores")
        if len(v) < 3 or len(v) > 30:
            raise ValueError("Handle must be 3-30 characters")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 100:
            raise ValueError("Name must be 1-100 characters")
        return v

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in PAGE_KINDS:
            raise ValueError(f"Kind must be one of: {', '.join(PAGE_KINDS)}")
        return v

    @field_validator("headline")
    @classmethod
    def validate_headline(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Headline must be at most 200 characters")
        return v if v else None


class PageUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    headline: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) < 1 or len(v) > 100:
            raise ValueError("Name must be 1-100 characters")
        return v

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.lower().strip()
        if v not in PAGE_KINDS:
            raise ValueError(f"Kind must be one of: {', '.join(PAGE_KINDS)}")
        return v

    @field_validator("headline")
    @classmethod
    def validate_headline(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Headline must be at most 200 characters")
        return v if v else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 5000:
            raise ValueError("Description must be at most 5000 characters")
        return v if v else None


class PageIconUploadUrlRequest(BaseModel):
    content_type: str


class PageIconConfirmRequest(BaseModel):
    media_path: str


class PageCoverUploadUrlRequest(BaseModel):
    content_type: str


class PageCoverConfirmRequest(BaseModel):
    media_path: str


# --- Helper Functions ---


async def _get_page_by_handle(handle: str) -> dict | None:
    """Get page by handle."""
    return await database.fetch_one(
        """
        SELECT id, handle, name, kind, headline, description, icon_path, cover_path,
               owner_id, created_at, updated_at
        FROM pages WHERE handle = :handle
        """,
        {"handle": handle.lower()},
    )


async def _get_page_by_id(page_id: int) -> dict | None:
    """Get page by ID."""
    return await database.fetch_one(
        """
        SELECT id, handle, name, kind, headline, description, icon_path, cover_path,
               owner_id, created_at, updated_at
        FROM pages WHERE id = :page_id
        """,
        {"page_id": page_id},
    )


async def is_page_editor(page_id: int, user_id: int) -> bool:
    """Check if user is owner or accepted editor of the page."""
    result = await database.fetch_one(
        """
        SELECT 1 FROM pages WHERE id = :page_id AND owner_id = :user_id
        UNION
        SELECT 1 FROM page_editors WHERE page_id = :page_id AND user_id = :user_id AND accepted_at IS NOT NULL
        LIMIT 1
        """,
        {"page_id": page_id, "user_id": user_id},
    )
    return result is not None


async def _is_page_owner(page_id: int, user_id: int) -> bool:
    """Check if user is owner of the page."""
    result = await database.fetch_one(
        """SELECT 1 FROM pages WHERE id = :page_id AND owner_id = :user_id""",
        {"page_id": page_id, "user_id": user_id},
    )
    return result is not None


async def _get_user_by_handle(handle: str) -> dict | None:
    """Get user by handle."""
    return await database.fetch_one(
        """SELECT id, handle, first_name, middle_name, last_name, headline, avatar_path FROM users WHERE handle = :handle""",
        {"handle": handle.lower()},
    )


def _format_user_name(user: dict) -> str:
    """Format user's full name from first/middle/last."""
    first_name = user.get("first_name") or ""
    middle_name = user.get("middle_name")
    last_name = user.get("last_name") or ""
    if middle_name:
        return f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
    return f"{first_name} {last_name}".strip()


def _format_page(page: dict) -> dict:
    """Format page for API response."""
    icon_path = page.get("icon_path")
    cover_path = page.get("cover_path")
    return {
        "id": page["id"],
        "handle": page["handle"],
        "name": page["name"],
        "kind": page["kind"],
        "headline": page.get("headline"),
        "description": page.get("description"),
        "icon_url": get_avatar_url(icon_path) if icon_path else None,
        "cover_url": get_avatar_url(cover_path) if cover_path else None,
        "created_at": page["created_at"].isoformat() if page.get("created_at") else None,
    }


def _format_person(user: dict) -> dict:
    """Format user info for API response."""
    avatar_path = user.get("avatar_path")
    return {
        "handle": user["handle"],
        "name": _format_user_name(user),
        "headline": user.get("headline"),
        "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
    }


# --- Page CRUD Endpoints ---


@router.post("")
async def create_page(
    payload: PageCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a new Page."""
    user_id = current_user["id"]

    # Check if handle is already taken (by page or user)
    existing_page = await _get_page_by_handle(payload.handle)
    if existing_page:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Handle already taken")

    existing_user = await _get_user_by_handle(payload.handle)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Handle already taken")

    # Create the page
    result = await database.fetch_one(
        """
        INSERT INTO pages (handle, name, kind, headline, owner_id)
        VALUES (:handle, :name, :kind, :headline, :owner_id)
        RETURNING id, handle, name, kind, headline, owner_id, created_at
        """,
        {
            "handle": payload.handle,
            "name": payload.name,
            "kind": payload.kind,
            "headline": payload.headline,
            "owner_id": user_id,
        },
    )

    return _format_page(dict(result))


@router.get("/my")
async def list_my_pages(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List pages I own or edit."""
    user_id = current_user["id"]

    pages = await database.fetch_all(
        """
        SELECT p.id, p.handle, p.name, p.kind, p.headline, p.icon_path, p.cover_path,
               p.owner_id, p.created_at,
               CASE WHEN p.owner_id = :user_id THEN 'owner' ELSE 'editor' END as role
        FROM pages p
        LEFT JOIN page_editors pe ON pe.page_id = p.id AND pe.user_id = :user_id AND pe.accepted_at IS NOT NULL
        WHERE p.owner_id = :user_id OR pe.user_id IS NOT NULL
        ORDER BY p.name
        """,
        {"user_id": user_id},
    )

    return [
        {**_format_page(dict(p)), "role": p["role"]}
        for p in pages
    ]


@router.get("/invitations")
async def list_invitations(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List pending editor invitations for current user."""
    user_id = current_user["id"]

    invitations = await database.fetch_all(
        """
        SELECT p.id, p.handle, p.name, p.kind, p.headline, p.icon_path,
               pe.invited_at,
               u.handle as inviter_handle, u.first_name as inviter_first_name,
               u.middle_name as inviter_middle_name, u.last_name as inviter_last_name
        FROM page_editors pe
        JOIN pages p ON p.id = pe.page_id
        JOIN users u ON u.id = pe.invited_by
        WHERE pe.user_id = :user_id AND pe.accepted_at IS NULL
        ORDER BY pe.invited_at DESC
        """,
        {"user_id": user_id},
    )

    return [
        {
            "page": {
                "id": inv["id"],
                "handle": inv["handle"],
                "name": inv["name"],
                "kind": inv["kind"],
                "headline": inv["headline"],
                "icon_url": get_avatar_url(inv["icon_path"]) if inv["icon_path"] else None,
            },
            "inviter": {
                "handle": inv["inviter_handle"],
                "name": _format_user_name({
                    "first_name": inv["inviter_first_name"],
                    "middle_name": inv["inviter_middle_name"],
                    "last_name": inv["inviter_last_name"],
                }),
            },
            "invited_at": inv["invited_at"].isoformat() if inv["invited_at"] else None,
        }
        for inv in invitations
    ]


@router.get("/invitations/count")
async def get_invitations_count(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get count of pending editor invitations for navbar badge."""
    user_id = current_user["id"]

    result = await database.fetch_one(
        """
        SELECT COUNT(*) as count
        FROM page_editors
        WHERE user_id = :user_id AND accepted_at IS NULL
        """,
        {"user_id": user_id},
    )

    return {"count": result["count"] if result else 0}


@router.post("/invitations/{page_handle}/accept")
async def accept_invitation(
    page_handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Accept an editor invitation."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(page_handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    # Check for pending invitation
    invitation = await database.fetch_one(
        """
        SELECT 1 FROM page_editors
        WHERE page_id = :page_id AND user_id = :user_id AND accepted_at IS NULL
        """,
        {"page_id": page["id"], "user_id": user_id},
    )

    if not invitation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending invitation")

    # Accept the invitation
    await database.execute(
        """
        UPDATE page_editors
        SET accepted_at = NOW()
        WHERE page_id = :page_id AND user_id = :user_id
        """,
        {"page_id": page["id"], "user_id": user_id},
    )

    return {"accepted": True}


@router.post("/invitations/{page_handle}/decline")
async def decline_invitation(
    page_handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Decline an editor invitation."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(page_handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    # Delete the invitation
    await database.execute(
        """
        DELETE FROM page_editors
        WHERE page_id = :page_id AND user_id = :user_id AND accepted_at IS NULL
        """,
        {"page_id": page["id"], "user_id": user_id},
    )

    return {"declined": True}


@router.get("/following")
async def list_following(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List pages the current user is following."""
    user_id = current_user["id"]

    pages = await database.fetch_all(
        """
        SELECT p.id, p.handle, p.name, p.kind, p.headline, p.icon_path, p.cover_path,
               p.created_at, pf.created_at as followed_at
        FROM page_follows pf
        JOIN pages p ON p.id = pf.page_id
        WHERE pf.user_id = :user_id
        ORDER BY pf.created_at DESC
        """,
        {"user_id": user_id},
    )

    return [_format_page(dict(p)) for p in pages]


@router.get("/{handle}")
async def get_page(handle: str) -> dict:
    """Get page by handle (public)."""
    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    # Get follower count
    follower_count = await database.fetch_one(
        """SELECT COUNT(*) as count FROM page_follows WHERE page_id = :page_id""",
        {"page_id": page["id"]},
    )

    # Get owner info
    owner = await database.fetch_one(
        """SELECT handle, first_name, middle_name, last_name, avatar_path FROM users WHERE id = :owner_id""",
        {"owner_id": page["owner_id"]},
    )

    return {
        **_format_page(dict(page)),
        "owner": _format_person(dict(owner)) if owner else None,
        "follower_count": follower_count["count"] if follower_count else 0,
    }


@router.put("/{handle}")
async def update_page(
    handle: str,
    payload: PageUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update page (owner or editor only)."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Build update query
    updates = []
    params = {"page_id": page["id"]}

    if payload.name is not None:
        updates.append("name = :name")
        params["name"] = payload.name
    if payload.kind is not None:
        updates.append("kind = :kind")
        params["kind"] = payload.kind
    if payload.headline is not None:
        updates.append("headline = :headline")
        params["headline"] = payload.headline
    if payload.description is not None:
        updates.append("description = :description")
        params["description"] = payload.description

    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    updates.append("updated_at = NOW()")

    await database.execute(
        f"""UPDATE pages SET {', '.join(updates)} WHERE id = :page_id""",
        params,
    )

    # Return updated page
    updated_page = await _get_page_by_id(page["id"])
    return _format_page(dict(updated_page))


@router.delete("/{handle}")
async def delete_page(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete page (owner only)."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await _is_page_owner(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can delete the page")

    await database.execute(
        """DELETE FROM pages WHERE id = :page_id""",
        {"page_id": page["id"]},
    )

    return {"deleted": True}


# --- Editor Management Endpoints ---


@router.get("/{handle}/editors")
async def list_editors(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """List page editors (owner and accepted editors)."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    # Check if user can view editors (must be owner or editor)
    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Get owner
    owner = await database.fetch_one(
        """SELECT id, handle, first_name, middle_name, last_name, headline, avatar_path FROM users WHERE id = :owner_id""",
        {"owner_id": page["owner_id"]},
    )

    # Get accepted editors
    editors = await database.fetch_all(
        """
        SELECT u.id, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path,
               pe.accepted_at
        FROM page_editors pe
        JOIN users u ON u.id = pe.user_id
        WHERE pe.page_id = :page_id AND pe.accepted_at IS NOT NULL
        ORDER BY pe.accepted_at
        """,
        {"page_id": page["id"]},
    )

    # Get pending invitations (owner only)
    pending = []
    if page["owner_id"] == user_id:
        pending = await database.fetch_all(
            """
            SELECT u.id, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path,
                   pe.invited_at
            FROM page_editors pe
            JOIN users u ON u.id = pe.user_id
            WHERE pe.page_id = :page_id AND pe.accepted_at IS NULL
            ORDER BY pe.invited_at DESC
            """,
            {"page_id": page["id"]},
        )

    return {
        "owner": {**_format_person(dict(owner)), "id": owner["id"]},
        "editors": [
            {**_format_person(dict(e)), "id": e["id"], "accepted_at": e["accepted_at"].isoformat() if e["accepted_at"] else None}
            for e in editors
        ],
        "pending": [
            {**_format_person(dict(p)), "id": p["id"], "invited_at": p["invited_at"].isoformat() if p["invited_at"] else None}
            for p in pending
        ],
        "is_owner": page["owner_id"] == user_id,
    }


@router.post("/{handle}/editors/{user_handle}")
async def invite_editor(
    handle: str,
    user_handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Invite a user to be an editor (owner only)."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await _is_page_owner(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can invite editors")

    target_user = await _get_user_by_handle(user_handle)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target_user["id"] == page["owner_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Owner is already an editor")

    # Check if already an editor or has pending invitation
    existing = await database.fetch_one(
        """SELECT accepted_at FROM page_editors WHERE page_id = :page_id AND user_id = :user_id""",
        {"page_id": page["id"], "user_id": target_user["id"]},
    )

    if existing:
        if existing["accepted_at"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already an editor")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already has a pending invitation")

    # Create invitation
    await database.execute(
        """
        INSERT INTO page_editors (page_id, user_id, invited_by)
        VALUES (:page_id, :user_id, :invited_by)
        """,
        {"page_id": page["id"], "user_id": target_user["id"], "invited_by": user_id},
    )

    # Notify the invited user
    await notify_user(target_user["handle"], "page_editor_invitation")

    return {"invited": True}


@router.delete("/{handle}/editors/{user_handle}")
async def remove_editor(
    handle: str,
    user_handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Remove an editor or cancel invitation (owner only, or self-removal)."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    target_user = await _get_user_by_handle(user_handle)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    is_owner = await _is_page_owner(page["id"], user_id)
    is_self = target_user["id"] == user_id

    # Only owner can remove others; anyone can remove themselves
    if not is_owner and not is_self:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Cannot remove the owner
    if target_user["id"] == page["owner_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the owner")

    # Delete from editors
    await database.execute(
        """DELETE FROM page_editors WHERE page_id = :page_id AND user_id = :user_id""",
        {"page_id": page["id"], "user_id": target_user["id"]},
    )

    return {"removed": True}


@router.post("/{handle}/transfer/{user_handle}")
async def transfer_ownership(
    handle: str,
    user_handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Transfer page ownership to an accepted editor (owner only)."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await _is_page_owner(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can transfer ownership")

    target_user = await _get_user_by_handle(user_handle)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target_user["id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already the owner")

    # Check target is an accepted editor
    editor = await database.fetch_one(
        """SELECT 1 FROM page_editors WHERE page_id = :page_id AND user_id = :user_id AND accepted_at IS NOT NULL""",
        {"page_id": page["id"], "user_id": target_user["id"]},
    )

    if not editor:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User must be an accepted editor to transfer ownership")

    # Transfer ownership: update page owner and remove new owner from editors, add old owner as editor
    await database.execute(
        """UPDATE pages SET owner_id = :new_owner_id, updated_at = NOW() WHERE id = :page_id""",
        {"page_id": page["id"], "new_owner_id": target_user["id"]},
    )

    # Remove new owner from editors table
    await database.execute(
        """DELETE FROM page_editors WHERE page_id = :page_id AND user_id = :user_id""",
        {"page_id": page["id"], "user_id": target_user["id"]},
    )

    # Add old owner as editor
    await database.execute(
        """
        INSERT INTO page_editors (page_id, user_id, invited_by, accepted_at)
        VALUES (:page_id, :user_id, :invited_by, NOW())
        """,
        {"page_id": page["id"], "user_id": user_id, "invited_by": target_user["id"]},
    )

    # Notify new owner
    await notify_user(target_user["handle"], "page_ownership_transferred")

    return {"transferred": True}


# --- Following Endpoints ---


@router.post("/{handle}/follow")
async def follow_page(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Follow a page."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    # Insert or ignore if already following
    await database.execute(
        """
        INSERT INTO page_follows (page_id, user_id)
        VALUES (:page_id, :user_id)
        ON CONFLICT (page_id, user_id) DO NOTHING
        """,
        {"page_id": page["id"], "user_id": user_id},
    )

    return {"following": True}


@router.delete("/{handle}/follow")
async def unfollow_page(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Unfollow a page."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    await database.execute(
        """DELETE FROM page_follows WHERE page_id = :page_id AND user_id = :user_id""",
        {"page_id": page["id"], "user_id": user_id},
    )

    return {"unfollowed": True}


@router.get("/{handle}/followers")
async def list_followers(
    handle: str,
    limit: int = 50,
) -> list[dict]:
    """List page followers (public)."""
    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    followers = await database.fetch_all(
        """
        SELECT u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path,
               pf.created_at as followed_at
        FROM page_follows pf
        JOIN users u ON u.id = pf.user_id
        WHERE pf.page_id = :page_id
        ORDER BY pf.created_at DESC
        LIMIT :limit
        """,
        {"page_id": page["id"], "limit": limit},
    )

    return [
        {
            **_format_person(dict(f)),
            "followed_at": f["followed_at"].isoformat() if f["followed_at"] else None,
        }
        for f in followers
    ]


@router.get("/{handle}/status")
async def get_follow_status(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get current user's relationship with the page."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    is_following = await database.fetch_one(
        """SELECT 1 FROM page_follows WHERE page_id = :page_id AND user_id = :user_id""",
        {"page_id": page["id"], "user_id": user_id},
    )

    is_owner = page["owner_id"] == user_id

    is_editor = False
    has_pending_invitation = False
    if not is_owner:
        editor_status = await database.fetch_one(
            """SELECT accepted_at FROM page_editors WHERE page_id = :page_id AND user_id = :user_id""",
            {"page_id": page["id"], "user_id": user_id},
        )
        if editor_status:
            is_editor = editor_status["accepted_at"] is not None
            has_pending_invitation = editor_status["accepted_at"] is None

    return {
        "is_following": is_following is not None,
        "is_owner": is_owner,
        "is_editor": is_editor or is_owner,
        "has_pending_invitation": has_pending_invitation,
    }


# --- Image Upload Endpoints ---


@router.post("/{handle}/icon/upload-url")
async def get_page_icon_upload_url(
    handle: str,
    payload: PageIconUploadUrlRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get presigned URL for direct page icon upload."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    try:
        result = generate_page_icon_upload_url(page["id"], payload.content_type)
        return {"upload_url": result["upload_url"], "media_path": result["media_path"]}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{handle}/icon/confirm")
async def confirm_page_icon_upload(
    handle: str,
    payload: PageIconConfirmRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm page icon upload after direct R2 upload."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    old_icon_path = page["icon_path"]

    # Delete old icon only after confirming new one
    if old_icon_path:
        delete_page_icon(old_icon_path)

    await database.execute(
        "UPDATE pages SET icon_path = :path, updated_at = NOW() WHERE id = :id",
        {"path": payload.media_path, "id": page["id"]},
    )

    return {"icon_url": get_avatar_url(payload.media_path)}


@router.delete("/{handle}/icon")
async def delete_page_icon_endpoint(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete page icon."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if page["icon_path"]:
        delete_page_icon(page["icon_path"])
        await database.execute(
            "UPDATE pages SET icon_path = NULL, updated_at = NOW() WHERE id = :id",
            {"id": page["id"]},
        )

    return {"deleted": True}


@router.post("/{handle}/cover/upload-url")
async def get_page_cover_upload_url(
    handle: str,
    payload: PageCoverUploadUrlRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get presigned URL for direct page cover upload."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    try:
        result = generate_page_cover_upload_url(page["id"], payload.content_type)
        return {"upload_url": result["upload_url"], "media_path": result["media_path"]}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{handle}/cover/confirm")
async def confirm_page_cover_upload(
    handle: str,
    payload: PageCoverConfirmRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm page cover upload after direct R2 upload."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    old_cover_path = page["cover_path"]

    # Delete old cover only after confirming new one
    if old_cover_path:
        delete_page_cover(old_cover_path)

    await database.execute(
        "UPDATE pages SET cover_path = :path, updated_at = NOW() WHERE id = :id",
        {"path": payload.media_path, "id": page["id"]},
    )

    return {"cover_url": get_avatar_url(payload.media_path)}


@router.delete("/{handle}/cover")
async def delete_page_cover_endpoint(
    handle: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete page cover."""
    user_id = current_user["id"]

    page = await _get_page_by_handle(handle)
    if not page:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

    if not await is_page_editor(page["id"], user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if page["cover_path"]:
        delete_page_cover(page["cover_path"])
        await database.execute(
            "UPDATE pages SET cover_path = NULL, updated_at = NOW() WHERE id = :id",
            {"id": page["id"]},
        )

    return {"deleted": True}
