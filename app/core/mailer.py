"""Resolve: outgoing email.


"""
import logging
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("resolve.mailer")


async def send_email(to: str, subject: str, body: str) -> None:
    if settings.email_backend == "console":
        logger.info("EMAIL (console backend, dev only)\nTo: %s\nSubject: %s\n\n%s", to, subject, body)
        return

    import aiosmtplib  # imported lazily so the console backend needs no SMTP lib

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    implicit_tls = settings.smtp_port == 465
    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=implicit_tls,
        start_tls=settings.smtp_starttls and not implicit_tls,
        timeout=30,
    )


async def send_verification_email(email: str, token: str) -> None:
    """Runs as a background task, so it must never raise: a mail outage
    should not turn a successful registration into a server error."""
    link = f"{settings.public_base_url.rstrip('/')}/auth/verify-email?token={token}"
    try:
        await send_email(
            email,
            "Verify your Resolve account",
            "Welcome to Resolve.\n\n"
            f"Confirm your email address to start filing complaints:\n{link}\n\n"
            f"This link expires in {settings.verify_token_hours} hours. "
            "If you didn't create an account, you can ignore this message.",
        )
    except Exception:
        logger.exception("Failed to send verification email to %s", email)
