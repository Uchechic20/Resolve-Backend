"""Resolve: Analytics and Dashboard metrics router."""
from fastapi import APIRouter
from sqlalchemy import select, func
from datetime import datetime, timezone, timedelta

from app.dependencies import DbSession, AdminUser
from app.models.ticket import Ticket
from app.models.enums import TicketStatus, TicketPriority

router = APIRouter(prefix="/admin/metrics", tags=["Analytics"])

@router.get("/overview")
async def get_dashboard_metrics(
    db: DbSession,
    admin: AdminUser
):
    """
    Get high-level ticket metrics for the admin dashboard.
    Requires Admin privileges.
    """
    # 1. Total Tickets
    total_tickets = await db.scalar(select(func.count(Ticket.id))) or 0

    # 2. Unassigned Tickets
    unassigned = await db.scalar(
        select(func.count(Ticket.id)).where(Ticket.assignee_id.is_(None))
    ) or 0

    # 3. Average CSAT (Satisfaction Rating)
    avg_csat = await db.scalar(
        select(func.avg(Ticket.satisfaction_rating))
    )
    # Convert Decimal to float for JSON serialization
    avg_csat_float = round(float(avg_csat), 2) if avg_csat is not None else None

    # 4. Tickets Breached SLA
    now = datetime.now(timezone.utc)
    breached_sla = await db.scalar(
        select(func.count(Ticket.id))
        .where(Ticket.sla_deadline < now)
        .where(Ticket.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]))
    ) or 0

    # 5. Tickets by Status (for charting)
    status_counts_stmt = select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status)
    status_result = await db.execute(status_counts_stmt)
    status_counts = {status.value: count for status, count in status_result.all()}

    return {
        "total_tickets": total_tickets,
        "unassigned_tickets": unassigned,
        "breached_sla": breached_sla,
        "average_satisfaction": avg_csat_float,
        "tickets_by_status": status_counts
    }