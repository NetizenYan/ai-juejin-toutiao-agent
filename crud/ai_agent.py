"""AI 会话存储的 CRUD（异步）。供 Gateway/Harness 持久化会话、消息、工具调用轨迹。"""
from typing import Optional

from sqlalchemy import select, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_agent import AiSession, AiMessage, AiToolCall


async def create_session(db: AsyncSession, user_id: int, title: Optional[str] = None,
                         intent: Optional[str] = None) -> AiSession:
    session = AiSession(user_id=user_id, title=title, intent=intent)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: int, user_id: int) -> Optional[AiSession]:
    stmt = select(AiSession).where(AiSession.id == session_id, AiSession.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_sessions(db: AsyncSession, user_id: int, limit: int = 50):
    stmt = select(AiSession).where(AiSession.user_id == user_id).order_by(desc(AiSession.updated_at)).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


async def update_session_intent(db: AsyncSession, session_id: int, intent: str) -> None:
    session = await db.get(AiSession, session_id)
    if session:
        session.intent = intent
        await db.commit()


async def add_message(db: AsyncSession, session_id: int, role: str, content: str = "",
                      evidence: Optional[dict] = None) -> AiMessage:
    message = AiMessage(session_id=session_id, role=role, content=content, evidence=evidence)
    db.add(message)
    # 触发会话 updated_at 刷新
    session = await db.get(AiSession, session_id)
    if session and not session.title and role == "user" and content:
        session.title = content[:30]
    await db.commit()
    await db.refresh(message)
    return message


async def get_recent_messages(db: AsyncSession, session_id: int, limit: int = 20):
    """取最近 N 条消息，按时间正序返回（供注入模型上下文）。"""
    stmt = select(AiMessage).where(AiMessage.session_id == session_id).order_by(desc(AiMessage.id)).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()
    return rows


async def add_tool_call(db: AsyncSession, message_id: int, tool_name: str,
                        arguments: Optional[dict] = None, result: Optional[dict] = None,
                        latency_ms: Optional[int] = None) -> AiToolCall:
    tool_call = AiToolCall(message_id=message_id, tool_name=tool_name, arguments=arguments,
                           result=result, latency_ms=latency_ms)
    db.add(tool_call)
    await db.commit()
    await db.refresh(tool_call)
    return tool_call


async def clear_sessions(db: AsyncSession, user_id: int) -> int:
    stmt = delete(AiSession).where(AiSession.user_id == user_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount
