import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, field_validator

from app.auth import get_current_user, get_optional_user
from app.db import database
from app.routers.messages import notify_user
from app.storage import (
    POST_MEDIA_EXTENSION_MAP,
    delete_post_media,
    generate_post_media_upload_url,
    get_avatar_url,
    get_media_type,
    get_post_media_url,
)

router = APIRouter(prefix="/api/posts", tags=["posts"])

# Regex to find @mentions (handles are lowercase letters, numbers, underscores)
MENTION_PATTERN = re.compile(r"@([a-z0-9_]{3,30})\b")


# --- Pydantic Models ---


class PostCreate(BaseModel):
    content: str
    visibility: str = "connections"

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 2000:
            raise ValueError("Post must be 1-2000 characters")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in ("public", "connections"):
            raise ValueError("Visibility must be 'public' or 'connections'")
        return v


class ReplyCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 2000:
            raise ValueError("Comment must be 1-2000 characters")
        return v


class VoteCreate(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: int) -> int:
        if v not in (-1, 1):
            raise ValueError("Vote must be -1 or 1")
        return v


class VisibilityUpdate(BaseModel):
    visibility: str

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in ("public", "connections"):
            raise ValueError("Visibility must be 'public' or 'connections'")
        return v


ALLOWED_MEDIA_TYPES = tuple(POST_MEDIA_EXTENSION_MAP.keys())
ALLOWED_EXTENSIONS = tuple(f".{ext}" for ext in POST_MEDIA_EXTENSION_MAP.values())


class MediaUploadUrlRequest(BaseModel):
    content_type: str

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in ALLOWED_MEDIA_TYPES:
            raise ValueError("Only JPEG, PNG, WebP images or MP4, WebM, MOV videos allowed")
        return v


class MediaConfirmRequest(BaseModel):
    content_type: str
    media_path: str

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in ALLOWED_MEDIA_TYPES:
            raise ValueError("Only JPEG, PNG, WebP images or MP4, WebM, MOV videos allowed")
        return v

    @field_validator("media_path")
    @classmethod
    def validate_media_path(cls, v: str) -> str:
        if not v.startswith("newsfeed/") or not any(v.endswith(ext) for ext in ALLOWED_EXTENSIONS):
            raise ValueError("Invalid media path")
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


async def get_connected_user_ids(user_id: int) -> list[int]:
    """Get IDs of all users connected to this user (mutual confirm exists)."""
    rows = await database.fetch_all(
        """
        SELECT DISTINCT
            CASE
                WHEN sender_id = :user_id THEN receiver_id
                ELSE sender_id
            END as other_user_id
        FROM messages
        WHERE kind = 'confirm'
          AND (sender_id = :user_id OR receiver_id = :user_id)
        """,
        {"user_id": user_id},
    )
    return [row["other_user_id"] for row in rows]


async def can_view_post(user_id: int | None, post: dict) -> bool:
    """Check if user can view a post based on visibility."""
    # Public posts are viewable by anyone
    if post["visibility"] == "public":
        return True

    # Not logged in can only see public posts
    if user_id is None:
        return False

    # Author can always see their own posts
    if post["author_id"] == user_id:
        return True

    # Check if viewer is connected to author
    connected_ids = await get_connected_user_ids(user_id)
    return post["author_id"] in connected_ids


async def get_post_by_id(post_id: int) -> dict | None:
    """Get a post by ID with author info."""
    return await database.fetch_one(
        """
        SELECT p.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
        FROM posts p
        JOIN users u ON u.id = p.author_id
        WHERE p.id = :post_id
        """,
        {"post_id": post_id},
    )


async def get_root_post(post: dict) -> dict:
    """Get the root post for a comment (or the post itself if it's top-level)."""
    if post["reply_to_id"] is None:
        return post
    if post["root_post_id"]:
        root = await get_post_by_id(post["root_post_id"])
        if root:
            return root
    return post


async def update_vote_counts(post_id: int) -> None:
    """Recalculate and update vote counts for a post."""
    await database.execute(
        """
        UPDATE posts SET
            upvote_count = (SELECT COUNT(*) FROM post_votes WHERE post_id = :post_id AND value = 1),
            downvote_count = (SELECT COUNT(*) FROM post_votes WHERE post_id = :post_id AND value = -1)
        WHERE id = :post_id
        """,
        {"post_id": post_id},
    )


async def update_comment_count(post_id: int) -> None:
    """Recalculate and update comment count for a post."""
    await database.execute(
        """
        UPDATE posts SET
            comment_count = (SELECT COUNT(*) FROM posts WHERE root_post_id = :post_id)
        WHERE id = :post_id
        """,
        {"post_id": post_id},
    )


async def process_mentions(content: str, author_id: int) -> None:
    """Parse @mentions and send notifications to mentioned users."""
    handles = MENTION_PATTERN.findall(content)
    if not handles:
        return

    # Get unique handles
    unique_handles = list(set(handles))

    # Find users with notify_mentions enabled
    placeholders = ", ".join(f":h{i}" for i in range(len(unique_handles)))
    params = {f"h{i}": h for i, h in enumerate(unique_handles)}

    users = await database.fetch_all(
        f"""
        SELECT id, handle FROM users
        WHERE handle IN ({placeholders})
          AND notify_mentions = true
          AND id != :author_id
        """,
        {**params, "author_id": author_id},
    )

    # Send notifications
    for user in users:
        await notify_user(user["handle"], "mention")


async def get_post_media(post_id: int) -> list[dict]:
    """Get media attached to a post."""
    rows = await database.fetch_all(
        """
        SELECT id, media_path, media_type, display_order
        FROM post_media
        WHERE post_id = :post_id
        ORDER BY display_order
        """,
        {"post_id": post_id},
    )
    return [
        {
            "id": row["id"],
            "url": get_post_media_url(row["media_path"]),
            "type": row["media_type"],
        }
        for row in rows
    ]


async def get_posts_media(post_ids: list[int]) -> dict[int, list[dict]]:
    """Get media for multiple posts at once."""
    if not post_ids:
        return {}

    placeholders = ", ".join(f":p{i}" for i in range(len(post_ids)))
    params = {f"p{i}": pid for i, pid in enumerate(post_ids)}

    rows = await database.fetch_all(
        f"""
        SELECT id, post_id, media_path, media_type, display_order
        FROM post_media
        WHERE post_id IN ({placeholders})
        ORDER BY post_id, display_order
        """,
        params,
    )

    result: dict[int, list[dict]] = {pid: [] for pid in post_ids}
    for row in rows:
        result[row["post_id"]].append({
            "id": row["id"],
            "url": get_post_media_url(row["media_path"]),
            "type": row["media_type"],
        })
    return result


def format_post_response(
    post: dict, user_id: int | None, user_vote: int | None = None, media: list[dict] | None = None
) -> dict:
    """Format a post for API response."""
    return {
        "id": post["id"],
        "author": _format_author(dict(post)),
        "content": post["content"],
        "visibility": post["visibility"],
        "reply_to_id": post["reply_to_id"],
        "root_post_id": post["root_post_id"],
        "upvote_count": post["upvote_count"],
        "downvote_count": post["downvote_count"],
        "comment_count": post["comment_count"],
        "user_vote": user_vote,
        "is_mine": user_id is not None and post["author_id"] == user_id,
        "created_at": post["created_at"].isoformat() if post["created_at"] else None,
        "media": media or [],
    }


# --- Endpoints ---


@router.get("")
async def list_posts(
    current_user: dict | None = Depends(get_optional_user),
    filter: str = "all",
    before_id: int | None = None,
    limit: int = 20,
) -> dict:
    """
    List feed posts (top-level posts only).

    Filters:
    - all: Public + own + connections' posts (default)
    - mine: Only own posts
    """
    if limit > 50:
        limit = 50

    user_id = current_user["id"] if current_user else None

    # Build base query
    params: dict = {"limit": limit}

    if filter == "mine":
        if user_id is None:
            return {"posts": [], "has_more": False}
        base_query = """
            SELECT p.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
            FROM posts p
            JOIN users u ON u.id = p.author_id
            WHERE p.reply_to_id IS NULL
              AND p.author_id = :user_id
        """
        params["user_id"] = user_id
    elif user_id is None:
        # Not logged in: public posts only
        base_query = """
            SELECT p.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
            FROM posts p
            JOIN users u ON u.id = p.author_id
            WHERE p.reply_to_id IS NULL
              AND p.visibility = 'public'
        """
    else:
        # Logged in: public + own + connections
        connected_ids = await get_connected_user_ids(user_id)

        if connected_ids:
            placeholders = ", ".join(f":c{i}" for i in range(len(connected_ids)))
            for i, cid in enumerate(connected_ids):
                params[f"c{i}"] = cid

            base_query = f"""
                SELECT p.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
                FROM posts p
                JOIN users u ON u.id = p.author_id
                WHERE p.reply_to_id IS NULL
                  AND (
                      p.visibility = 'public'
                      OR p.author_id = :user_id
                      OR (p.visibility = 'connections' AND p.author_id IN ({placeholders}))
                  )
            """
        else:
            base_query = """
                SELECT p.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
                FROM posts p
                JOIN users u ON u.id = p.author_id
                WHERE p.reply_to_id IS NULL
                  AND (p.visibility = 'public' OR p.author_id = :user_id)
            """
        params["user_id"] = user_id

    # Add pagination
    if before_id:
        base_query += " AND p.id < :before_id"
        params["before_id"] = before_id

    base_query += " ORDER BY p.created_at DESC LIMIT :limit"

    posts = await database.fetch_all(base_query, params)

    # Get user votes and media for these posts
    user_votes: dict[int, int] = {}
    posts_media: dict[int, list[dict]] = {}
    if posts:
        post_ids = [p["id"] for p in posts]

        # Get media for all posts
        posts_media = await get_posts_media(post_ids)

        # Get user votes if logged in
        if user_id:
            placeholders = ", ".join(f":p{i}" for i in range(len(post_ids)))
            vote_params = {f"p{i}": pid for i, pid in enumerate(post_ids)}
            vote_params["user_id"] = user_id

            votes = await database.fetch_all(
                f"""
                SELECT post_id, value FROM post_votes
                WHERE user_id = :user_id AND post_id IN ({placeholders})
                """,
                vote_params,
            )
            user_votes = {v["post_id"]: v["value"] for v in votes}

    return {
        "posts": [
            format_post_response(
                dict(p), user_id, user_votes.get(p["id"]), posts_media.get(p["id"], [])
            )
            for p in posts
        ],
        "has_more": len(posts) == limit,
    }


@router.get("/{post_id}")
async def get_post(
    post_id: int,
    current_user: dict | None = Depends(get_optional_user),
) -> dict:
    """Get a single post with its comments."""
    user_id = current_user["id"] if current_user else None

    post = await get_post_by_id(post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Check visibility
    root_post = await get_root_post(dict(post))
    if not await can_view_post(user_id, root_post):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view this post")

    # Get user's vote on this post
    user_vote = None
    if user_id:
        vote = await database.fetch_one(
            "SELECT value FROM post_votes WHERE post_id = :post_id AND user_id = :user_id",
            {"post_id": post_id, "user_id": user_id},
        )
        if vote:
            user_vote = vote["value"]

    # Get all comments in thread (including nested replies)
    comments = await database.fetch_all(
        """
        SELECT p.*, u.handle, u.first_name, u.middle_name, u.last_name, u.headline, u.avatar_path
        FROM posts p
        JOIN users u ON u.id = p.author_id
        WHERE p.root_post_id = :post_id
        ORDER BY p.created_at ASC
        """,
        {"post_id": post_id},
    )

    # Get user votes for comments
    comment_votes: dict[int, int] = {}
    if user_id and comments:
        comment_ids = [c["id"] for c in comments]
        placeholders = ", ".join(f":c{i}" for i in range(len(comment_ids)))
        vote_params = {f"c{i}": cid for i, cid in enumerate(comment_ids)}
        vote_params["user_id"] = user_id

        votes = await database.fetch_all(
            f"""
            SELECT post_id, value FROM post_votes
            WHERE user_id = :user_id AND post_id IN ({placeholders})
            """,
            vote_params,
        )
        comment_votes = {v["post_id"]: v["value"] for v in votes}

    # Get media for the post
    post_media = await get_post_media(post_id)

    return {
        "post": format_post_response(dict(post), user_id, user_vote, post_media),
        "comments": [
            format_post_response(dict(c), user_id, comment_votes.get(c["id"]))
            for c in comments
        ],
    }


@router.post("")
async def create_post(
    payload: PostCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a new top-level post."""
    user_id = current_user["id"]

    result = await database.fetch_one(
        """
        INSERT INTO posts (author_id, content, visibility)
        VALUES (:author_id, :content, :visibility)
        RETURNING id, created_at
        """,
        {
            "author_id": user_id,
            "content": payload.content,
            "visibility": payload.visibility,
        },
    )

    # Process @mentions
    await process_mentions(payload.content, user_id)

    return {
        "id": result["id"],
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.post("/{post_id}/media/upload-url")
async def get_media_upload_url(
    post_id: int,
    payload: MediaUploadUrlRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Generate presigned URL for direct R2 upload."""
    user_id = current_user["id"]

    # Check post exists and user is author
    post = await database.fetch_one(
        "SELECT id, author_id, reply_to_id FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["author_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only add media to your own posts")

    # Only allow media on top-level posts (not comments)
    if post["reply_to_id"] is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add media to comments",
        )

    # Check media count (max 1 media per post)
    media_count = await database.fetch_one(
        "SELECT COUNT(*) as count FROM post_media WHERE post_id = :post_id",
        {"post_id": post_id},
    )
    if media_count["count"] >= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 1 media per post",
        )

    # Generate presigned URL
    result = generate_post_media_upload_url(post_id, media_count["count"], payload.content_type)
    return result


@router.post("/{post_id}/media/confirm")
async def confirm_media_upload(
    post_id: int,
    payload: MediaConfirmRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Confirm media was uploaded and record in database."""
    user_id = current_user["id"]

    # Check post exists and user is author
    post = await database.fetch_one(
        "SELECT id, author_id, reply_to_id FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["author_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only add media to your own posts")

    # Only allow media on top-level posts (not comments)
    if post["reply_to_id"] is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add media to comments",
        )

    # Check media count (max 1 media per post)
    media_count = await database.fetch_one(
        "SELECT COUNT(*) as count FROM post_media WHERE post_id = :post_id",
        {"post_id": post_id},
    )
    if media_count["count"] >= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 1 media per post",
        )

    # Determine media type from content type
    media_type = get_media_type(payload.content_type)

    # Store in database
    result = await database.fetch_one(
        """
        INSERT INTO post_media (post_id, media_path, media_type, display_order)
        VALUES (:post_id, :media_path, :media_type, :display_order)
        RETURNING id
        """,
        {
            "post_id": post_id,
            "media_path": payload.media_path,
            "media_type": media_type,
            "display_order": media_count["count"],
        },
    )

    return {
        "id": result["id"],
        "url": get_post_media_url(payload.media_path),
        "type": media_type,
    }


@router.delete("/{post_id}/media/{media_id}")
async def delete_media(
    post_id: int,
    media_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete media from a post."""
    user_id = current_user["id"]

    # Check post exists and user is author
    post = await database.fetch_one(
        "SELECT author_id FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["author_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only delete media from your own posts")

    # Get media info
    media = await database.fetch_one(
        "SELECT media_path FROM post_media WHERE id = :media_id AND post_id = :post_id",
        {"media_id": media_id, "post_id": post_id},
    )

    if media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    # Delete from storage
    delete_post_media(media["media_path"])

    # Delete from database
    await database.execute(
        "DELETE FROM post_media WHERE id = :media_id",
        {"media_id": media_id},
    )

    return {"deleted": True}


@router.post("/{post_id}/reply")
async def create_reply(
    post_id: int,
    payload: ReplyCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a reply (comment) to a post."""
    user_id = current_user["id"]

    # Get parent post
    parent = await get_post_by_id(post_id)
    if parent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Check if user can view the parent post (and thus reply to it)
    root_post = await get_root_post(dict(parent))
    if not await can_view_post(user_id, root_post):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot reply to this post")

    # Determine root_post_id
    if parent["reply_to_id"] is None:
        # Parent is top-level, so parent becomes root
        root_post_id = parent["id"]
    else:
        # Parent is already a comment, inherit its root
        root_post_id = parent["root_post_id"]

    # Inherit visibility from root post
    visibility = root_post["visibility"]

    result = await database.fetch_one(
        """
        INSERT INTO posts (author_id, content, visibility, reply_to_id, root_post_id)
        VALUES (:author_id, :content, :visibility, :reply_to_id, :root_post_id)
        RETURNING id, created_at
        """,
        {
            "author_id": user_id,
            "content": payload.content,
            "visibility": visibility,
            "reply_to_id": post_id,
            "root_post_id": root_post_id,
        },
    )

    # Update comment count on parent
    await update_comment_count(post_id)

    # Process @mentions
    await process_mentions(payload.content, user_id)

    return {
        "id": result["id"],
        "created_at": result["created_at"].isoformat() if result["created_at"] else None,
    }


@router.delete("/{post_id}")
async def delete_post(
    post_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete a post (and all its children via cascade)."""
    user_id = current_user["id"]

    post = await database.fetch_one(
        "SELECT id, author_id, reply_to_id FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["author_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only delete your own posts")

    parent_id = post["reply_to_id"]

    # Delete media from storage before database cascade deletes them
    media_paths = await database.fetch_all(
        "SELECT media_path FROM post_media WHERE post_id = :post_id",
        {"post_id": post_id},
    )
    for media in media_paths:
        delete_post_media(media["media_path"])

    # Delete the post (cascade will handle children and post_media records)
    await database.execute("DELETE FROM posts WHERE id = :post_id", {"post_id": post_id})

    # Update parent's comment count if this was a reply
    if parent_id:
        await update_comment_count(parent_id)

    return {"deleted": True}


@router.post("/{post_id}/vote")
async def vote_on_post(
    post_id: int,
    payload: VoteCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Vote on a post (+1 or -1)."""
    user_id = current_user["id"]

    post = await get_post_by_id(post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Can't vote on own posts
    if post["author_id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot vote on your own post")

    # Check visibility
    root_post = await get_root_post(dict(post))
    if not await can_view_post(user_id, root_post):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot vote on this post")

    # Upsert vote
    await database.execute(
        """
        INSERT INTO post_votes (post_id, user_id, value)
        VALUES (:post_id, :user_id, :value)
        ON CONFLICT (post_id, user_id)
        DO UPDATE SET value = :value, created_at = NOW()
        """,
        {"post_id": post_id, "user_id": user_id, "value": payload.value},
    )

    # Update cached counts
    await update_vote_counts(post_id)

    # Get updated counts
    updated = await database.fetch_one(
        "SELECT upvote_count, downvote_count FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    return {
        "upvote_count": updated["upvote_count"],
        "downvote_count": updated["downvote_count"],
        "user_vote": payload.value,
    }


@router.delete("/{post_id}/vote")
async def remove_vote(
    post_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Remove vote from a post."""
    user_id = current_user["id"]

    post = await database.fetch_one(
        "SELECT id FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Delete the vote
    await database.execute(
        "DELETE FROM post_votes WHERE post_id = :post_id AND user_id = :user_id",
        {"post_id": post_id, "user_id": user_id},
    )

    # Update cached counts
    await update_vote_counts(post_id)

    # Get updated counts
    updated = await database.fetch_one(
        "SELECT upvote_count, downvote_count FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    return {
        "upvote_count": updated["upvote_count"],
        "downvote_count": updated["downvote_count"],
        "user_vote": None,
    }


@router.patch("/{post_id}/visibility")
async def change_visibility(
    post_id: int,
    payload: VisibilityUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Change visibility of a top-level post."""
    user_id = current_user["id"]

    post = await database.fetch_one(
        "SELECT id, author_id, reply_to_id FROM posts WHERE id = :post_id",
        {"post_id": post_id},
    )

    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["author_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only change your own posts")

    if post["reply_to_id"] is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change visibility of a comment",
        )

    await database.execute(
        "UPDATE posts SET visibility = :visibility WHERE id = :post_id",
        {"post_id": post_id, "visibility": payload.visibility},
    )

    return {"visibility": payload.visibility}


@router.post("/{post_id}/report")
async def report_post(
    post_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Report a post for abuse."""
    user_id = current_user["id"]

    post = await get_post_by_id(post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Can't report own posts
    if post["author_id"] == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot report your own post")

    # Check if already reported by this user
    existing = await database.fetch_one(
        "SELECT id FROM abuse_reports WHERE post_id = :post_id AND reporter_id = :reporter_id",
        {"post_id": post_id, "reporter_id": user_id},
    )

    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already reported this post")

    # Create report
    await database.execute(
        "INSERT INTO abuse_reports (post_id, reporter_id) VALUES (:post_id, :reporter_id)",
        {"post_id": post_id, "reporter_id": user_id},
    )

    return {"reported": True}
