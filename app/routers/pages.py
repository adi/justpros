from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

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
    return request.app.state.templates.TemplateResponse(
        request, "public_profile.html", {"handle": handle}
    )
