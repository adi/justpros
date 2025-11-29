from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr

from app.auth import (
    create_access_token,
    generate_handle,
    generate_token,
    hash_password,
    verify_password,
)
from app.db import database
from app.email import send_password_reset_email, send_verification_email
from app.ratelimit import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])

VERIFICATION_TOKEN_EXPIRY_HOURS = 24
RESET_TOKEN_EXPIRY_HOURS = 1
MAX_PASSWORD_BYTES = 72


def validate_password(password: str) -> None:
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password too long (max 72 bytes)",
        )


@router.post("/signup", response_class=HTMLResponse)
@rate_limit(max_requests=5, window_seconds=60)
async def signup(
    request: Request,
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form()],
    first_name: Annotated[str, Form()],
    last_name: Annotated[str, Form()],
    middle_name: Annotated[str | None, Form()] = None,
) -> str:
    validate_password(password)

    existing = await database.fetch_one(
        "SELECT id FROM users WHERE email = :email",
        {"email": email},
    )
    if existing:
        return '<p class="text-red-600">Email already registered</p>'

    handle = generate_handle(email)
    password_hash = hash_password(password)
    verification_token = generate_token()
    verification_expires = datetime.now(timezone.utc) + timedelta(
        hours=VERIFICATION_TOKEN_EXPIRY_HOURS
    )

    await database.execute(
        """
        INSERT INTO users (handle, email, password_hash, first_name, middle_name, last_name, verification_token, verification_token_expires)
        VALUES (:handle, :email, :password_hash, :first_name, :middle_name, :last_name, :verification_token, :verification_token_expires)
        """,
        {
            "handle": handle,
            "email": email,
            "password_hash": password_hash,
            "first_name": first_name,
            "middle_name": middle_name or None,
            "last_name": last_name,
            "verification_token": verification_token,
            "verification_token_expires": verification_expires,
        },
    )

    send_verification_email(email, verification_token, first_name)

    return '<p class="text-green-600">Check your email to verify your account</p>'


@router.get("/verify", response_class=HTMLResponse)
async def verify_email(request: Request, token: str) -> HTMLResponse:
    user = await database.fetch_one(
        """
        SELECT id, verified, verification_token_expires
        FROM users
        WHERE verification_token = :token
        """,
        {"token": token},
    )

    if not user:
        return request.app.state.templates.TemplateResponse(
            request, "verify_result.html", {"success": False, "message": "Invalid verification token"}
        )

    if user["verified"]:
        return request.app.state.templates.TemplateResponse(
            request, "verify_result.html", {"success": True, "message": "Email already verified"}
        )

    if user["verification_token_expires"] < datetime.now(timezone.utc):
        return request.app.state.templates.TemplateResponse(
            request, "verify_result.html", {"success": False, "message": "Verification token expired"}
        )

    await database.execute(
        """
        UPDATE users
        SET verified = TRUE, verification_token = NULL, verification_token_expires = NULL
        WHERE id = :id
        """,
        {"id": user["id"]},
    )

    return request.app.state.templates.TemplateResponse(
        request, "verify_result.html", {"success": True, "message": "Email verified successfully!"}
    )


@router.post("/login", response_class=HTMLResponse)
@rate_limit(max_requests=10, window_seconds=60)
async def login(
    request: Request,
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form()],
) -> str:
    validate_password(password)

    user = await database.fetch_one(
        "SELECT id, password_hash, verified FROM users WHERE email = :email",
        {"email": email},
    )

    if not user or not verify_password(password, user["password_hash"]):
        return '<p class="text-red-600">Invalid email or password</p>'

    if not user["verified"]:
        return '<p class="text-red-600">Please verify your email first</p>'

    access_token = create_access_token(user["id"])
    # Return token in a way the frontend can store it
    return f'''
    <p class="text-green-600">Login successful!</p>
    <script>
        localStorage.setItem('token', '{access_token}');
        window.location.href = '/';
    </script>
    '''


@router.post("/forgot-password", response_class=HTMLResponse)
@rate_limit(max_requests=3, window_seconds=60)
async def forgot_password(
    request: Request,
    email: Annotated[EmailStr, Form()],
) -> str:
    user = await database.fetch_one(
        "SELECT id, email, first_name FROM users WHERE email = :email",
        {"email": email},
    )

    if user:
        reset_token = generate_token()
        reset_expires = datetime.now(timezone.utc) + timedelta(
            hours=RESET_TOKEN_EXPIRY_HOURS
        )

        await database.execute(
            """
            UPDATE users
            SET reset_token = :reset_token, reset_token_expires = :reset_token_expires
            WHERE id = :id
            """,
            {
                "reset_token": reset_token,
                "reset_token_expires": reset_expires,
                "id": user["id"],
            },
        )

        send_password_reset_email(user["email"], reset_token, user["first_name"])

    # Always return success to prevent email enumeration
    return '<p class="text-green-600">If that email exists, we sent a reset link</p>'


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password(
    token: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> str:
    validate_password(password)

    user = await database.fetch_one(
        """
        SELECT id, reset_token_expires
        FROM users
        WHERE reset_token = :token
        """,
        {"token": token},
    )

    if not user:
        return '<p class="text-red-600">Invalid reset token</p>'

    if user["reset_token_expires"] < datetime.now(timezone.utc):
        return '<p class="text-red-600">Reset token expired</p>'

    password_hash = hash_password(password)

    await database.execute(
        """
        UPDATE users
        SET password_hash = :password_hash, reset_token = NULL, reset_token_expires = NULL
        WHERE id = :id
        """,
        {"password_hash": password_hash, "id": user["id"]},
    )

    return '<p class="text-green-600">Password reset! <a href="/login" class="underline">Log in</a></p>'
