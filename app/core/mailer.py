"""Resolve: outgoing email."""
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger("resolve.mailer")

# Default SendLiberty API endpoint
SENDLIBERTY_API_URL = "https://api.sendliberty.com/v1/send"


async def send_templated_email(to: str, template: str, data: dict) -> None:
    """Sends a templated email via API (bypasses Render SMTP blocks)."""
    if settings.email_backend == "console":
        logger.info("EMAIL TEMPLATE (console backend, dev only)\nTo: %s\nTemplate: %s\nData: %s", to, template, data)
        return

    if settings.email_backend == "api":
        if not settings.sendliberty_api_key:
            logger.error("SENDLIBERTY_API_KEY is missing from settings. Email not sent.")
            return

        headers = {
            "Authorization": f"Bearer {settings.sendliberty_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        # EXACT JSON PAYLOAD YOU REQUESTED
        payload = {
            "template": template,
            "to": to,
            "data": data
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    SENDLIBERTY_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=15.0
                )
                response.raise_for_status()
                logger.info(f"Templated email '{template}' successfully sent to {to}.")

        except httpx.HTTPStatusError as exc:
            logger.error(f"SendLiberty API Error {exc.response.status_code}: {exc.response.text}")
        except Exception as exc:
            logger.error(f"Network error while sending email via SendLiberty: {exc}")
        return

    # Fallback to standard SMTP
    import aiosmtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = f"Resolve Notification ({template})"
    # Basic fallback body if API fails
    msg.set_content(f"Template: {template}\nData: {data}")

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


async def send_verification_email(email: str, token: str, name: str = "User") -> None:
    """Runs as a background task to send the verification template."""
    link = f"{settings.public_base_url.rstrip('/')}/auth/verify-email?token={token}"

    try:
        await send_templated_email(
            to=email,
            template="verify-email",
            data={
                "name": name,
                "link": link
            }
        )
    except Exception:
        logger.exception("Failed to send verification email to %s", email)