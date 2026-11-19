"""Resolve: Knowledge Base router."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, or_
from pydantic import BaseModel

from app.dependencies import DbSession, AdminUser
from app.models.knowledge_base import KBArticle

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])

class KBCreate(BaseModel):
    title: str
    content: str
    tags: str | None = None

@router.get("/search")
async def search_kb(q: str, db: DbSession):
    """Search KB articles by title or content."""
    stmt = select(KBArticle).where(
        or_(
            KBArticle.title.ilike(f"%{q}%"),
            KBArticle.content.ilike(f"%{q}%")
        )
    )
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/")
async def create_kb(article: KBCreate, db: DbSession, admin: AdminUser):
    """Create a new KB article. Requires Admin."""
    new_article = KBArticle(**article.model_dump())
    db.add(new_article)
    await db.commit()
    await db.refresh(new_article)
    return new_article