import httpx
import hashlib
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.ticket import Ticket, TicketEvent
from app.models.webhook import Webhook


async def fire_webhook(db: AsyncSession, event_type: str, payload: dict):
    """Sends HTTP POST to external systems (Slack, Teams, etc.)"""
    stmt = select(Webhook).where(Webhook.event_type == event_type, Webhook.is_active == True)
    hooks = (await db.execute(stmt)).scalars().all()

    async with httpx.AsyncClient() as client:
        for hook in hooks:
            try:
                await client.post(hook.url, json={"event": event_type, "data": payload}, timeout=5.0)
            except Exception:
                pass  # Don't crash the app if a webhook fails


async def create_audit_event(db: AsyncSession, ticket_id: int, actor_id: int, event_type: str, from_val: str,
                             to_val: str):
    """Creates an immutable, hashed audit log (Blockchain-style)"""
    # Get previous hash
    stmt = select(TicketEvent).where(TicketEvent.ticket_id == ticket_id).order_by(TicketEvent.id.desc()).limit(1)
    prev_event = (await db.execute(stmt)).scalar_one_or_none()
    prev_hash = prev_event.hash if prev_event else "GENESIS"

    # Create payload and hash it
    payload_str = f"{prev_hash}-{ticket_id}-{actor_id}-{event_type}-{from_val}-{to_val}"
    new_hash = hashlib.sha256(payload_str.encode()).hexdigest()

    event = TicketEvent(
        ticket_id=ticket_id, actor_id=actor_id, event_type=event_type,
        from_value=from_val, to_value=to_val, prev_hash=prev_hash, hash=new_hash
    )
    db.add(event)
    await db.commit()