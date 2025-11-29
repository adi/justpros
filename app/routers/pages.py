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
