"""AI assistant APIs (roadmap phase 6): چت با کش معنایی + منابع بازیابی‌شده."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models.assistant import AiConversation, AiMessage
from app.services import assistant as assistant_svc

router = APIRouter(prefix="/assistant", tags=["assistant"])


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


@router.post("/chat")
async def chat(
    body: ChatIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.message.strip():
        raise HTTPException(400, "پیام خالی است")
    result = await assistant_svc.chat(db, current.id, body.message.strip(), body.conversation_id)
    await db.commit()  # پیام‌ها + کش معنایی باید پایدار شوند
    return result


@router.get("/conversations")
async def conversations(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AiConversation)
            .where(AiConversation.student_user_id == current.id)
            .order_by(AiConversation.id.desc())
        )
    ).scalars().all()
    return {"conversations": [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in rows]}


@router.get("/conversations/{conversation_id}")
async def conversation_detail(
    conversation_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.get(AiConversation, conversation_id)
    if conv is None or conv.student_user_id != current.id:
        raise HTTPException(404, "گفت‌وگو یافت نشد")
    msgs = (
        await db.execute(select(AiMessage).where(AiMessage.conversation_id == conversation_id).order_by(AiMessage.id))
    ).scalars().all()
    return {
        "id": conv.id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "model_tier": m.model_tier,
                "sources": m.sources,
                "cached": bool(m.cached),
            }
            for m in msgs
        ],
    }
