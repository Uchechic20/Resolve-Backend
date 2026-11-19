from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.ticket import Ticket
from app.models.user import User
from app.models.department import Category
from app.models.enums import TicketPriority, TicketStatus
from difflib import SequenceMatcher
import re


# 1. AI-Powered Complaint Classification (Keyword matching for local AI)
def classify_category(text: str) -> str:
    text = text.lower()
    if re.search(r'bank|money|debit|credit|transfer|loan', text): return "Banking Issue"
    if re.search(r'login|password|bug|error|crash|app', text): return "Technical Support"
    if re.search(r'agent|rude|staff|manager|behavior', text): return "Customer Service"
    return "General"


# 2. Intelligent Priority and Severity Scoring
def calculate_severity(text: str, sentiment_score: float) -> tuple[str, str]:
    text = text.lower()
    is_urgent = any(word in text for word in ["urgent", "immediately", "fraud", "stolen", "lost", "emergency"])

    if sentiment_score < -0.6 or is_urgent:
        return TicketPriority.HIGH, "critical"
    elif sentiment_score < -0.2:
        return TicketPriority.MEDIUM, "high"
    return TicketPriority.LOW, "medium"


# 3. Automated Complaint Assignment (Load Balancing)
async def auto_assign_agent(db: AsyncSession, department_id: int) -> int | None:
    # Find the agent in this department with the least active tickets
    stmt = (
        select(User.id, func.count(Ticket.id).label("active_tickets"))
        .outerjoin(Ticket, (Ticket.assignee_id == User.id) & (Ticket.status != TicketStatus.RESOLVED))
        .where(User.role == "agent", User.is_active == True)
        .group_by(User.id)
        .order_by(func.count(Ticket.id).asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.first()
    return row[0] if row else None


# 4. Duplicate Detection
async def check_duplicates(db: AsyncSession, new_title: str, new_desc: str) -> Ticket | None:
    stmt = select(Ticket).where(Ticket.status != TicketStatus.RESOLVED).limit(100)
    result = await db.execute(stmt)
    open_tickets = result.scalars().all()

    for t in open_tickets:
        title_ratio = SequenceMatcher(None, t.title.lower(), new_title.lower()).ratio()
        if title_ratio > 0.85:
            return t  # Returns the duplicate ticket
    return None


# 5. Recurring Complaint Detection
async def is_recurring_complaint(db: AsyncSession, user_id: int, category_id: int) -> bool:
    # If user submitted more than 3 tickets in the same category in the last 7 days
    stmt = (
        select(func.count(Ticket.id))
        .where(Ticket.complainant_id == user_id)
        .where(Ticket.category_id == category_id)
        .where(Ticket.created_at >= func.now() - func.make_interval(0, 0, 0, 7))  # Last 7 days
    )
    count = await db.scalar(stmt)
    return count >= 3