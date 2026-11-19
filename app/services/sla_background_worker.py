import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from app.core.database import SessionLocal
from app.models.ticket import Ticket
from app.models.enums import TicketStatus, TicketPriority

# Import the webhook function from our event system
# (Make sure you created app/services/event_system.py from the previous step!)
try:
    from app.services.event_system import fire_webhook
except ImportError:
    async def fire_webhook(db, event, payload):
        pass  # Fallback if event system isn't set up yet


async def run_sla_worker():
    """Checks for breached SLAs and predictive warnings every 15 minutes."""
    while True:
        try:
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                warning_time = now + timedelta(hours=1)

                # ---------------------------------------------------------
                # 1. PREDICTIVE SLA WARNING (Deadline is within the next hour)
                # ---------------------------------------------------------
                stmt_warning = select(Ticket).where(
                    Ticket.sla_deadline <= warning_time,
                    Ticket.sla_deadline > now,
                    Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED, TicketStatus.ESCALATED])
                )
                warning_tickets = (await db.execute(stmt_warning)).scalars().all()

                for t in warning_tickets:
                    # Fire a webhook to alert the agent (e.g., Slack/Teams)
                    await fire_webhook(db, "ticket.sla_warning", {
                        "ticket_id": t.id,
                        "title": t.title,
                        "deadline": t.sla_deadline.isoformat()
                    })

                # ---------------------------------------------------------
                # 2. MULTI-LEVEL ESCALATION (SLA has been breached)
                # ---------------------------------------------------------
                stmt_breach = (
                    update(Ticket)
                    .where(
                        Ticket.sla_deadline < now,
                        Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED, TicketStatus.ESCALATED])
                    )
                    .values(status=TicketStatus.ESCALATED, priority=TicketPriority.HIGH)
                    .returning(Ticket.id)
                )

                # Execute and get the IDs of the tickets that were just escalated
                breached_ids = (await db.execute(stmt_breach)).scalars().all()

                for b_id in breached_ids:
                    await fire_webhook(db, "ticket.escalated", {
                        "ticket_id": b_id,
                        "reason": "SLA Breached"
                    })

                await db.commit()

                if breached_ids or warning_tickets:
                    print(f"[SLA Worker] Escalated {len(breached_ids)} tickets. Warned {len(warning_tickets)} tickets.")

        except Exception as e:
            print(f"SLA Worker Error: {e}")

        # Sleep for 15 minutes
        await asyncio.sleep(900)


async def run_auto_close_worker():
    """Automatically closes resolved tickets that have been inactive for 72 hours."""
    while True:
        try:
            async with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                cut_off = now - timedelta(hours=72)

                # Find tickets that were resolved more than 72 hours ago
                stmt = (
                    update(Ticket)
                    .where(
                        Ticket.status == TicketStatus.RESOLVED,
                        Ticket.updated_at <= cut_off
                    )
                    .values(status=TicketStatus.CLOSED)
                    .returning(Ticket.id)
                )

                closed_ids = (await db.execute(stmt)).scalars().all()

                for c_id in closed_ids:
                    await fire_webhook(db, "ticket.auto_closed", {"ticket_id": c_id})

                await db.commit()

                if closed_ids:
                    print(f"[Auto-Close Worker] Closed {len(closed_ids)} inactive tickets.")

        except Exception as e:
            print(f"Auto-Close Worker Error: {e}")

        # Sleep for 1 hour
        await asyncio.sleep(3600)