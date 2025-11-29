from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "signup.html")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "login.html")


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "forgot_password.html")


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "reset_password.html", {"token": token}
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "privacy.html")


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "terms.html")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "settings.html")
