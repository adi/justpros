import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user, get_optional_user
from app.db import database
from app.routers.posts import get_connected_user_ids
from app.routers.page_api import is_page_editor
from app.storage import get_avatar_url

router = APIRouter(prefix="/api/facts", tags=["facts"])


# --- Templates ---

FACT_TEMPLATES = {
    # For company pages
    "worked_at": {
        "subject_types": ["company"],
        "label": "I worked at",
        "format": "I worked at {subject} from {from_date} to {to_date}",
        "fields": ["from_date", "to_date"],
    },
    "cofounded": {
        "subject_types": ["company"],
        "label": "I co-founded",
        "format": "I co-founded {subject}",
        "fields": [],
    },
    # For education pages
    "studied_at": {
        "subject_types": ["education"],
        "label": "I studied at",
        "format": "I studied at {subject} from {from_date} to {to_date}",
        "fields": ["from_date", "to_date"],
    },
    "graduated_from": {
        "subject_types": ["education"],
        "label": "I graduated from",
        "format": "I graduated from {subject} in {year}",
        "fields": ["year"],
    },
    # For users
    "worked_with": {
        "subject_types": ["user"],
        "label": "I worked with",
        "format": "I worked with {subject}",
        "fields": [],
    },
    "reported_to": {
        "subject_types": ["user"],
        "label": "I reported to",
        "format": "I reported to {subject} at {page}",
        "fields": ["page"],
    },
    "managed": {
        "subject_types": ["user"],
        "label": "Managed by me",
        "format": "{subject} reported to me at {page}",
        "fields": ["page"],
    },
    # Freeform (discouraged)
    "freeform": {
        "subject_types": ["company", "education", "user", "event", "product", "community", "virtual"],
        "label": "Custom (not recommended)",
        "format": "{content}",
        "fields": ["content"],
    },
}


# --- Pydantic Models ---


class FactCreate(BaseModel):
    template_id: str
    subject_user_handle: str | None = None
    subject_page_handle: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    year: str | None = None
    page_handle: str | None = None  # For "reported_to" / "managed" templates
    content: str | None = None  # For freeform

    @field_validator("template_id")
    @classmethod
    def validate_template(cls, v: str) -> str:
        if v not in FACT_TEMPLATES:
            raise ValueError(f"Invalid template: {v}")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) < 1 or len(v) > 500:
                raise ValueError("Content must be 1-500 characters")
        return v


class VoteCreate(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: int) -> int:
        if v < -3 or v > 3:
            raise ValueError("Vote must be between -3 and 3")
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


def _format_author(user: dict) -> dict:
    """Format author info for API response."""
    avatar_path = user.get("avatar_path")
    return {
        "id": user["id"],
        "handle": user["handle"],
        "name": _format_user_name(user),
        "headline": user.get("headline"),
        "avatar_url": get_avatar_url(avatar_path) if avatar_path else None,
    }


async def render_fact_content(
    template_id: str,
    payload: FactCreate,
    subject_handle: str,
    subject_name: str,
    page_handle: str | None = None,
    page_name: str | None = None,
) -> tuple[str, dict[str, dict]]:
    """Render fact content from template and payload.

    Returns tuple of (content, mentions) where mentions is a dict of handle -> {type, name}.
    Content uses @handle format for mentions that can be linked in frontend.
    """
    mentions: dict[str, dict] = {}
    template = FACT_TEMPLATES.get(template_id)

    if not template:
        return payload.content or "", mentions

    if template_id == "freeform":
        return payload.content or "", mentions

    format_str = template["format"]

    # Replace {subject} with name and track mention for linking
    if "{subject}" in format_str:
        # Determine subject type based on template
        subject_type = "user" if "user" in template["subject_types"] else "page"
        result = format_str.replace("{subject}", subject_name)
        mentions[subject_handle] = {"type": subject_type, "name": subject_name}
    else:
        result = format_str

    if payload.from_date:
        result = result.replace("{from_date}", payload.from_date)
    if payload.to_date:
        result = result.replace("{to_date}", payload.to_date)
    if payload.year:
        result = result.replace("{year}", payload.year)

    # Replace {page} with name and track mention for linking
    if page_handle and page_name and "{page}" in result:
        result = result.replace("{page}", page_name)
        mentions[page_handle] = {"type": "page", "name": page_name}

    return result, mentions


async def update_fact_vote_stats(fact_id: int) -> None:
    """Recalculate and update vote stats for a fact."""
    await database.execute(
        """
        UPDATE facts SET
            vote_sum = COALESCE((SELECT SUM(value) FROM fact_votes WHERE fact_id = :fact_id), 0),
            vote_count = (SELECT COUNT(*) FROM fact_votes WHERE fact_id = :fact_id)
        WHERE id = :fact_id
        """,
        {"fact_id": fact_id},
    )


async def can_view_fact(viewer_id: int | None, fact: dict) -> bool:
    """Check if viewer can see a fact based on state and relationship."""
    # Vetoed facts are hidden from everyone except author and subject
    if fact["vetoed_at"]:
        if viewer_id is None:
            return False
        # Author can always see their own vetoed facts
        if fact["author_id"] == viewer_id:
            return True
        # Subject user can see vetoed facts about them
        if fact["subject_user_id"] and fact["subject_user_id"] == viewer_id:
            return True
        # Page editors can see vetoed facts about their pages
        if fact["subject_page_id"]:
            return await is_page_editor(fact["subject_page_id"], viewer_id)
        return False

    # Check if fact is public (approved or past cooldown)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    public_at = fact["public_at"]
    if public_at.tzinfo is None:
        public_at = public_at.replace(tzinfo=timezone.utc)

    is_approved = fact.get("approved_at") is not None
    is_past_cooldown = now >= public_at
    is_public = is_approved or is_past_cooldown

    if not is_public:
        # During cooldown and not approved - only author and subject can see
        if viewer_id is None:
            return False
        # Author can see during cooldown
        if fact["author_id"] == viewer_id:
            return True
        # Subject user can see during cooldown
        if fact["subject_user_id"] and fact["subject_user_id"] == viewer_id:
            return True
        # Page editors can see during cooldown
        if fact["subject_page_id"]:
            return await is_page_editor(fact["subject_page_id"], viewer_id)
        return False

    # Public facts: visible to author's connections
    if viewer_id is None:
        return False

    # Author can always see their own facts
    if fact["author_id"] == viewer_id:
        return True

    # Subject can always see facts about them
    if fact["subject_user_id"] and fact["subject_user_id"] == viewer_id:
        return True

    # Page editors can see facts about their pages
    if fact["subject_page_id"]:
        if await is_page_editor(fact["subject_page_id"], viewer_id):
            return True

    # Otherwise, viewer must be connected to author
    connected_ids = await get_connected_user_ids(viewer_id)
    return fact["author_id"] in connected_ids


def format_fact_response(fact: dict, user_vote: int | None = None) -> dict:
    """Format a fact for API response."""
    vote_sum = fact["vote_sum"]
    vote_count = fact["vote_count"]
    average = vote_sum / vote_count if vote_count > 0 else 0

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    public_at = fact["public_at"]
    if public_at.tzinfo is None:
        public_at = public_at.replace(tzinfo=timezone.utc)

    is_approved = fact.get("approved_at") is not None
    is_past_cooldown = now >= public_at
    is_public = fact["vetoed_at"] is None and (is_approved or is_past_cooldown)
    is_vetoed = fact["vetoed_at"] is not None

    # Parse mentions from JSON if present
    mentions = fact.get("mentions")
    if isinstance(mentions, str):
        mentions = json.loads(mentions)
    elif mentions is None:
        mentions = {}

    return {
        "id": fact["id"],
        "author": _format_author(fact) if "handle" in fact else None,
        "template_id": fact["template_id"],
        "content": fact["content"],
        "mentions": mentions,
        "subject_user_id": fact["subject_user_id"],
        "subject_page_id": fact["subject_page_id"],
        "vote_sum": vote_sum,
        "vote_count": vote_count,
        "average": average,
        "display_level": round(average),
        "user_vote": user_vote,
        "is_public": is_public,
        "is_vetoed": is_vetoed,
        "created_at": fact["created_at"].isoformat() if fact["created_at"] else None,
        "public_at": fact["public_at"].isoformat() if fact["public_at"] else None,
    }


# --- Endpoints ---


@router.get("/templates")
async def get_templates(
    subject_type: str | None = None,
) -> list[dict]:
    """Get available fact templates, optionally filtered by subject type."""
    result = []
    for template_id, template in FACT_TEMPLATES.items():
        if subject_type and subject_type not in template["subject_types"]:
            continue
        result.append({
            "id": template_id,
            "label": template["label"],
            "format": template["format"],
            "fields": template["fields"],
            "subject_types": template["subject_types"],
        })
    return result


@router.post("")
async def create_fact(
    payload: FactCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a new fact about a user or page."""
    author_id = current_user["id"]
    template = FACT_TEMPLATES.get(payload.template_id)

    if not template:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid template")

    # Determine subject
    subject_user_id = None
    subject_page_id = None
    subject_handle = ""
    subject_name = ""

    if payload.subject_user_handle:
        # User subject
        if "user" not in template["subject_types"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template not valid for user subjects")

        user = await database.fetch_one(
            "SELECT id, handle, first_name, middle_name, last_name FROM users WHERE handle = :handle",
            {"handle": payload.subject_user_handle},
        )
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if user["id"] == author_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot create fact about yourself")

        # Check author is connected to subject user
        connected_ids = await get_connected_user_ids(author_id)
        if user["id"] not in connected_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be connected to create facts about this user")

        subject_user_id = user["id"]
        subject_handle = user["handle"]
        subject_name = _format_user_name(dict(user))

    elif payload.subject_page_handle:
        # Page subject
        page = await database.fetch_one(
            "SELECT id, handle, name, kind FROM pages WHERE handle = :handle",
            {"handle": payload.subject_page_handle},
        )
        if not page:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

        if page["kind"] not in template["subject_types"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Template not valid for {page['kind']} pages"
            )

        # Check author follows the page or is an editor
        following = await database.fetch_one(
            "SELECT 1 FROM page_follows WHERE user_id = :user_id AND page_id = :page_id",
            {"user_id": author_id, "page_id": page["id"]},
        )
        is_editor = await is_page_editor(page["id"], author_id)
        if not following and not is_editor:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must follow page or be an editor to create facts about it")

        subject_page_id = page["id"]
        subject_handle = page["handle"]
        subject_name = page["name"]

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must specify subject_user_handle or subject_page_handle")

    # Handle page reference for "reported_to" / "managed" templates
    ref_page_handle = None
    ref_page_name = None
    if payload.page_handle and payload.template_id in ("reported_to", "managed"):
        ref_page = await database.fetch_one(
            "SELECT handle, name FROM pages WHERE handle = :handle",
            {"handle": payload.page_handle},
        )
        if ref_page:
            ref_page_handle = ref_page["handle"]
            ref_page_name = ref_page["name"]

    # Render content with mentions
    content, mentions = await render_fact_content(
        payload.template_id, payload, subject_handle, subject_name, ref_page_handle, ref_page_name
    )

    # Auto-approve if author is editor of subject page
    auto_approve = subject_page_id is not None and await is_page_editor(subject_page_id, author_id)

    # Serialize mentions to JSON
    mentions_json = json.dumps(mentions)

    # Create fact
    if auto_approve:
        result = await database.fetch_one(
            """
            INSERT INTO facts (author_id, subject_user_id, subject_page_id, template_id, content, mentions, approved_at)
            VALUES (:author_id, :subject_user_id, :subject_page_id, :template_id, :content, :mentions, NOW())
            RETURNING id, created_at, public_at, approved_at
            """,
            {
                "author_id": author_id,
                "subject_user_id": subject_user_id,
                "subject_page_id": subject_page_id,
                "template_id": payload.template_id,
                "content": content,
                "mentions": mentions_json,
            },
        )
    else:
        result = await database.fetch_one(
            """
            INSERT INTO facts (author_id, subject_user_id, subject_page_id, template_id, content, mentions)
            VALUES (:author_id, :subject_user_id, :subject_page_id, :template_id, :content, :mentions)
            RETURNING id, created_at, public_at, approved_at
            """,
            {
                "author_id": author_id,
                "subject_user_id": subject_user_id,
                "subject_page_id": subject_page_id,
                "template_id": payload.template_id,
                "content": content,
                "mentions": mentions_json,
            },
        )

    return {
        "id": result["id"],
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
        "public_at": result["public_at"].isoformat() if result["public_at"] else None,
        "approved_at": result["approved_at"].isoformat() if result["approved_at"] else None,
    }


@router.get("/pending-veto")
async def list_pending_veto(
    current_user: dict = Depends(get_current_user),
) -> list[dict]:
    """List facts about the current user or their pages that can be vetoed."""
    user_id = current_user["id"]

    # Get pages where user is editor
    editor_pages = await database.fetch_all(
        "SELECT page_id FROM page_editors WHERE user_id = :user_id",
        {"user_id": user_id},
    )
    page_ids = [p["page_id"] for p in editor_pages]

    # Build query for facts about user or their pages
    params: dict = {"user_id": user_id}
    conditions = ["f.subject_user_id = :user_id"]

    if page_ids:
        placeholders = ", ".join(f":p{i}" for i in range(len(page_ids)))
        for i, pid in enumerate(page_ids):
            params[f"p{i}"] = pid
        conditions.append(f"f.subject_page_id IN ({placeholders})")

    query = f"""
        SELECT f.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
        FROM facts f
        JOIN users u ON u.id = f.author_id
        WHERE ({' OR '.join(conditions)})
          AND f.vetoed_at IS NULL
          AND f.author_id != :user_id
        ORDER BY f.created_at DESC
    """

    facts = await database.fetch_all(query, params)
    return [format_fact_response(dict(f)) for f in facts]


@router.get("/pending-veto/count")
async def count_pending_veto(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Count facts awaiting potential veto (for navbar badge)."""
    user_id = current_user["id"]

    # Get pages where user is editor
    editor_pages = await database.fetch_all(
        "SELECT page_id FROM page_editors WHERE user_id = :user_id",
        {"user_id": user_id},
    )
    page_ids = [p["page_id"] for p in editor_pages]

    params: dict = {"user_id": user_id}
    conditions = ["subject_user_id = :user_id"]

    if page_ids:
        placeholders = ", ".join(f":p{i}" for i in range(len(page_ids)))
        for i, pid in enumerate(page_ids):
            params[f"p{i}"] = pid
        conditions.append(f"subject_page_id IN ({placeholders})")

    query = f"""
        SELECT COUNT(*) as count FROM facts
        WHERE ({' OR '.join(conditions)})
          AND vetoed_at IS NULL
          AND author_id != :user_id
    """

    result = await database.fetch_one(query, params)
    return {"count": result["count"]}


@router.delete("/{fact_id}")
async def delete_or_veto_fact(
    fact_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a fact (if author) or veto it (if subject)."""
    user_id = current_user["id"]

    fact = await database.fetch_one(
        "SELECT * FROM facts WHERE id = :fact_id",
        {"fact_id": fact_id},
    )

    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")

    # Author can delete
    if fact["author_id"] == user_id:
        await database.execute("DELETE FROM facts WHERE id = :fact_id", {"fact_id": fact_id})
        return {"deleted": True}

    # Subject user can veto
    if fact["subject_user_id"] and fact["subject_user_id"] == user_id:
        await database.execute(
            "UPDATE facts SET vetoed_at = NOW() WHERE id = :fact_id",
            {"fact_id": fact_id},
        )
        return {"vetoed": True}

    # Page editors can veto
    if fact["subject_page_id"]:
        if await is_page_editor(fact["subject_page_id"], user_id):
            await database.execute(
                "UPDATE facts SET vetoed_at = NOW() WHERE id = :fact_id",
                {"fact_id": fact_id},
            )
            return {"vetoed": True}

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


@router.post("/{fact_id}/approve")
async def approve_fact(
    fact_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Approve a fact early (if subject). Makes it public immediately."""
    user_id = current_user["id"]

    fact = await database.fetch_one(
        "SELECT * FROM facts WHERE id = :fact_id",
        {"fact_id": fact_id},
    )

    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")

    # Can't approve vetoed facts
    if fact["vetoed_at"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot approve a vetoed fact")

    # Already approved
    if fact["approved_at"]:
        return {"approved": True, "already_approved": True}

    # Subject user can approve
    if fact["subject_user_id"] and fact["subject_user_id"] == user_id:
        await database.execute(
            "UPDATE facts SET approved_at = NOW() WHERE id = :fact_id",
            {"fact_id": fact_id},
        )
        return {"approved": True}

    # Page editors can approve
    if fact["subject_page_id"]:
        if await is_page_editor(fact["subject_page_id"], user_id):
            await database.execute(
                "UPDATE facts SET approved_at = NOW() WHERE id = :fact_id",
                {"fact_id": fact_id},
            )
            return {"approved": True}

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


@router.post("/{fact_id}/vote")
async def vote_on_fact(
    fact_id: int,
    payload: VoteCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Vote on a fact (-3 to +3 scale)."""
    user_id = current_user["id"]

    fact = await database.fetch_one(
        "SELECT * FROM facts WHERE id = :fact_id",
        {"fact_id": fact_id},
    )

    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")

    # Can't vote on own facts
    if fact["author_id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot vote on your own fact")

    # Check if fact is public and not vetoed
    if not await can_view_fact(user_id, dict(fact)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot vote on this fact")

    # Must be connected to author to vote
    connected_ids = await get_connected_user_ids(user_id)
    if fact["author_id"] not in connected_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Must be connected to author to vote")

    # Check if same vote value (toggle off)
    existing_vote = await database.fetch_one(
        "SELECT value FROM fact_votes WHERE fact_id = :fact_id AND user_id = :user_id",
        {"fact_id": fact_id, "user_id": user_id},
    )

    if existing_vote and existing_vote["value"] == payload.value:
        # Remove vote
        await database.execute(
            "DELETE FROM fact_votes WHERE fact_id = :fact_id AND user_id = :user_id",
            {"fact_id": fact_id, "user_id": user_id},
        )
        user_vote = None
    else:
        # Upsert vote
        await database.execute(
            """
            INSERT INTO fact_votes (fact_id, user_id, value)
            VALUES (:fact_id, :user_id, :value)
            ON CONFLICT (fact_id, user_id)
            DO UPDATE SET value = :value, created_at = NOW()
            """,
            {"fact_id": fact_id, "user_id": user_id, "value": payload.value},
        )
        user_vote = payload.value

    # Update cached stats
    await update_fact_vote_stats(fact_id)

    # Get updated stats
    updated = await database.fetch_one(
        "SELECT vote_sum, vote_count FROM facts WHERE id = :fact_id",
        {"fact_id": fact_id},
    )

    vote_sum = updated["vote_sum"]
    vote_count = updated["vote_count"]
    average = vote_sum / vote_count if vote_count > 0 else 0

    return {
        "vote_sum": vote_sum,
        "vote_count": vote_count,
        "average": average,
        "display_level": round(average),
        "user_vote": user_vote,
    }


@router.delete("/{fact_id}/vote")
async def remove_vote(
    fact_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Remove vote from a fact."""
    user_id = current_user["id"]

    fact = await database.fetch_one(
        "SELECT id FROM facts WHERE id = :fact_id",
        {"fact_id": fact_id},
    )

    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")

    await database.execute(
        "DELETE FROM fact_votes WHERE fact_id = :fact_id AND user_id = :user_id",
        {"fact_id": fact_id, "user_id": user_id},
    )

    await update_fact_vote_stats(fact_id)

    updated = await database.fetch_one(
        "SELECT vote_sum, vote_count FROM facts WHERE id = :fact_id",
        {"fact_id": fact_id},
    )

    vote_sum = updated["vote_sum"]
    vote_count = updated["vote_count"]
    average = vote_sum / vote_count if vote_count > 0 else 0

    return {
        "vote_sum": vote_sum,
        "vote_count": vote_count,
        "average": average,
        "display_level": round(average),
        "user_vote": None,
    }


@router.get("/user/{handle}")
async def get_user_facts(
    handle: str,
    current_user: dict | None = Depends(get_optional_user),
) -> list[dict]:
    """Get public facts authored by a user (for their profile)."""
    viewer_id = current_user["id"] if current_user else None

    # Get the user
    user = await database.fetch_one(
        "SELECT id FROM users WHERE handle = :handle",
        {"handle": handle},
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    author_id = user["id"]

    # Get facts authored by this user
    facts = await database.fetch_all(
        """
        SELECT f.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
        FROM facts f
        JOIN users u ON u.id = f.author_id
        WHERE f.author_id = :author_id
        ORDER BY f.created_at DESC
        """,
        {"author_id": author_id},
    )

    # Filter by visibility
    visible_facts = []
    for fact in facts:
        if await can_view_fact(viewer_id, dict(fact)):
            visible_facts.append(fact)

    # Get user votes if logged in
    user_votes: dict[int, int] = {}
    if viewer_id and visible_facts:
        fact_ids = [f["id"] for f in visible_facts]
        placeholders = ", ".join(f":f{i}" for i in range(len(fact_ids)))
        vote_params = {f"f{i}": fid for i, fid in enumerate(fact_ids)}
        vote_params["user_id"] = viewer_id

        votes = await database.fetch_all(
            f"""
            SELECT fact_id, value FROM fact_votes
            WHERE user_id = :user_id AND fact_id IN ({placeholders})
            """,
            vote_params,
        )
        user_votes = {v["fact_id"]: v["value"] for v in votes}

    return [
        format_fact_response(dict(f), user_votes.get(f["id"]))
        for f in visible_facts
    ]
