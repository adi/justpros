from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db import database
from app.storage import get_avatar_url, get_cover_url, get_post_media_url

router = APIRouter(tags=["pages"])


@router.api_route("/signup", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def signup_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "signup.html")


@router.api_route("/login", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "login.html")


@router.api_route("/forgot-password", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def forgot_password_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "forgot_password.html")


@router.api_route("/reset-password", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "reset_password.html", {"token": token}
    )


@router.api_route("/privacy", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def privacy_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "privacy.html")


@router.api_route("/terms", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def terms_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "terms.html")


@router.api_route("/settings", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "settings.html")


@router.api_route("/people", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def people_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "people.html")


@router.api_route("/messages", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def messages_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "messages.html")


@router.api_route("/messages/{handle}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def messages_conversation_page(request: Request, handle: str) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "messages.html", {"selected_handle": handle}
    )


@router.api_route("/facts/pending", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def facts_pending_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "facts_pending.html")


@router.api_route("/pages", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def pages_list_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "pages_list.html")


@router.api_route("/pages/new", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def pages_create_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "page_create.html")


@router.api_route("/p/{handle}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def page_profile_page(request: Request, handle: str) -> HTMLResponse:
    # Fetch page data for OG meta tags
    page = await database.fetch_one(
        """
        SELECT handle, name, kind, headline, icon_path, cover_path
        FROM pages WHERE handle = :handle
        """,
        {"handle": handle.lower()},
    )

    context = {"handle": handle}

    if page:
        context["name"] = page["name"]
        context["headline"] = page["headline"] or ""
        context["og_image"] = (
            get_avatar_url(page["icon_path"]) if page["icon_path"] else None
        )

    return request.app.state.templates.TemplateResponse(
        request, "page_profile.html", context
    )


@router.api_route("/p/{handle}/editors", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def page_editors_page(request: Request, handle: str) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "page_editors.html", {"handle": handle}
    )


@router.api_route("/post/{post_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def single_post_by_id(request: Request, post_id: int) -> HTMLResponse:
    """Single post view by ID only - simpler share URL."""
    # Fetch post and author data for OG meta tags
    post = await database.fetch_one(
        """
        SELECT p.content, p.page_id, u.handle, u.first_name, u.middle_name, u.last_name, u.avatar_path
        FROM posts p
        JOIN users u ON u.id = p.author_id
        WHERE p.id = :post_id AND p.reply_to_id IS NULL
        """,
        {"post_id": post_id},
    )

    if not post:
        # Post not found - show 404-like page
        context = {"handle": "", "post_id": post_id}
        return request.app.state.templates.TemplateResponse(
            request, "single_post.html", context
        )

    context = {"handle": post["handle"], "post_id": post_id}

    # Check if this is a page post
    if post["page_id"]:
        page = await database.fetch_one(
            "SELECT handle, name, icon_path FROM pages WHERE id = :page_id",
            {"page_id": post["page_id"]},
        )
        if page:
            context["author_name"] = page["name"]
            context["handle"] = page["handle"]
            # Use page icon for OG image if no media
            if page["icon_path"]:
                context["og_image"] = get_avatar_url(page["icon_path"])
    else:
        first_name = post["first_name"] or ""
        middle_name = post["middle_name"]
        last_name = post["last_name"] or ""
        full_name = (
            f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
            if middle_name
            else f"{first_name} {last_name}".strip()
        )
        context["author_name"] = full_name or post["handle"]
        # Use author avatar for OG image if no media
        if post["avatar_path"]:
            context["og_image"] = get_avatar_url(post["avatar_path"])

    # Truncate content for OG description
    content = post["content"] or ""
    context["og_description"] = content[:200] + "..." if len(content) > 200 else content

    # Check for post media (image/video) for OG image - overrides avatar/icon
    media = await database.fetch_one(
        """
        SELECT media_path, media_type FROM post_media
        WHERE post_id = :post_id
        ORDER BY display_order LIMIT 1
        """,
        {"post_id": post_id},
    )

    if media:
        context["og_image"] = get_post_media_url(media["media_path"])

    return request.app.state.templates.TemplateResponse(
        request, "single_post.html", context
    )


@router.api_route("/u/{handle}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def public_profile_page(request: Request, handle: str) -> HTMLResponse:
    # Fetch user data for OG meta tags
    user = await database.fetch_one(
        """
        SELECT handle, first_name, middle_name, last_name, headline, avatar_path, cover_path
        FROM users WHERE handle = :handle
        """,
        {"handle": handle.lower()},
    )

    context = {"handle": handle}

    if user:
        first_name = user["first_name"] or ""
        middle_name = user["middle_name"]
        last_name = user["last_name"] or ""
        full_name = (
            f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
            if middle_name
            else f"{first_name} {last_name}".strip()
        )
        context["name"] = full_name or handle
        context["headline"] = user["headline"] or ""
        context["og_image"] = (
            get_avatar_url(user["avatar_path"]) if user["avatar_path"] else None
        )

    return request.app.state.templates.TemplateResponse(
        request, "public_profile.html", context
    )
