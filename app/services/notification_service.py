"""Resolve: sends queued notifications (the "outbox").

Services never send email inside a request. They write a row to `notifications` in the
same transaction as the change; this dispatcher (run by the worker) sends it. So a
mail outage cannot slow a request, and a crash cannot lose a message.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import mailer
from app.core.config import settings
from app.repositories import  UserRepository
from app.repositories.security import  NotificationRepository

@dataclass
class DispatchResult:
    sent: int = 0
    retry: int = 0
    failed: int = 0
    skipped: int = 0


async def dispatch_pending(session: AsyncSession, limit: int = 50) -> DispatchResult:
    repo, users = NotificationRepository(session), UserRepository(session)
    result = DispatchResult()
    for n in await repo.claim_pending(limit, settings.notification_max_attempts):
        user = await users.get(n.user_id)
        if user is None or not user.is_active:
            n.status, n.last_error = "failed", "recipient is missing or inactive"
            result.failed += 1
            continue
        if n.kind != "security_alert" and not user.email_notifications:
            n.status = "skipped"  # the user turned notifications off (security alerts always go)
            result.skipped += 1
            continue
        try:
            await mailer.send_email(user.email, n.subject, n.body)
        except Exception as exc:
            n.attempts += 1
            n.last_error = str(exc)[:500]
            if n.attempts >= settings.notification_max_attempts:
                n.status = "failed"
                result.failed += 1
            else:
                result.retry += 1
            continue
        n.status, n.sent_at, n.attempts = "sent", datetime.now(timezone.utc), n.attempts + 1
        result.sent += 1
    await session.commit()
    return result