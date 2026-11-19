from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from textblob import TextBlob
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ticket import Ticket
from app.models.enums import TicketPriority, TicketStatus

def analyze_sentiment(text: str) -> float:
    """Returns a score from -1.0 (very negative) to 1.0 (very positive)."""
    return TextBlob(text).sentiment.polarity

def calculate_sla(priority: TicketPriority) -> datetime:
    """Sets SLA deadline based on priority."""
    now = datetime.now(timezone.utc)
    if priority == TicketPriority.HIGH:
        return now + timedelta(hours=4)
    elif priority == TicketPriority.MEDIUM:
        return now + timedelta(hours=24)
    return now + timedelta(hours=72) # Low priority

async def find_similar_open_ticket(db: AsyncSession, description: str) -> Ticket | None:
    """Simple duplicate detection using text similarity."""
    stmt = select(Ticket).where(Ticket.status.in_([TicketStatus.SUBMITTED, TicketStatus.TRIAGED])).limit(50)
    result = await db.execute(stmt)
    recent_tickets = result.scalars().all()

    for ticket in recent_tickets:
        similarity = SequenceMatcher(None, ticket.description.lower(), description.lower()).ratio()
        if similarity > 0.85: # 85% similar
            return ticket
    return None