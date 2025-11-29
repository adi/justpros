from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db import database
from app.storage import get_avatar_url, get_cover_url

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


@router.api_route("/profile", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def profile_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "profile.html")


@router.api_route("/settings", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "settings.html")


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
            get_cover_url(user["cover_path"])
            if user["cover_path"]
            else get_avatar_url(user["avatar_path"])
            if user["avatar_path"]
            else None
        )

    return request.app.state.templates.TemplateResponse(
        request, "public_profile.html", context
    )
