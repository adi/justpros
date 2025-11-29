import os

import resend

resend.api_key = os.environ["RESEND_API_KEY"]

BASE_URL = os.environ["BASE_URL"]


def send_verification_email(to: str, token: str) -> None:
    verify_url = f"{BASE_URL}/auth/verify?token={token}"
    resend.Emails.send({
        "from": "JustPros <noreply@mail.justpros.org>",
        "to": to,
        "subject": "Verify your JustPros account",
        "html": f"""
        <h2>Welcome to JustPros!</h2>
        <p>Click the link below to verify your email:</p>
        <p><a href="{verify_url}">Verify my email</a></p>
        <p>This link expires in 24 hours.</p>
        """,
    })


def send_password_reset_email(to: str, token: str) -> None:
    reset_url = f"{BASE_URL}/reset-password?token={token}"
    resend.Emails.send({
        "from": "JustPros <noreply@mail.justpros.org>",
        "to": to,
        "subject": "Reset your JustPros password",
        "html": f"""
        <h2>Password Reset</h2>
        <p>Click the link below to reset your password:</p>
        <p><a href="{reset_url}">Reset my password</a></p>
        <p>This link expires in 1 hour. If you didn't request this, ignore this email.</p>
        """,
    })
