"""Agent Gateway：AI 对话统一入口。

POST /api/ai/chat            —— SSE 流式对话（鉴权）
GET  /api/ai/sessions        —— 当前用户会话列表
GET  /api/ai/sessions/{id}/messages —— 会话消息
DELETE /api/ai/sessions      —— 清空当前用户会话

模型不直连 DB：会话/消息持久化由后端经 crud 完成；后续工具均走 MCP。
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from config.ai_conf import settings
from config.db_conf import get_db, AsyncSessionLocal
from crud import ai_agent
from harness.agent import run_chat
from harness.evidence_detail_resolver import resolve_evidence_detail
from harness.intent import detect_intent
from models.users import User
from schemas.ai import ChatRequest
from utils.auth import get_current_user
from utils.response import success_response

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_assistant_evidence_pack(evidence: list, validation: dict) -> dict | None:
    evidence_pack = {"refs": evidence} if evidence else None
    if settings.answer_validation_store_metadata and validation.get("metadata"):
        if evidence_pack is None:
            evidence_pack = {"refs": []}
        evidence_pack["validation"] = validation["metadata"]
    if settings.session_summary_enabled and validation.get("context"):
        if evidence_pack is None:
            evidence_pack = {"refs": []}
        evidence_pack["context"] = validation["context"]
    for source_key, output_key in (
        ("anchor_resolution", "anchor_resolution"),
        ("confirmed_anchor", "confirmed_anchor"),
        ("agent_orchestration", "agent_orchestration"),
    ):
        if validation.get(source_key):
            if evidence_pack is None:
                evidence_pack = {"refs": []}
            evidence_pack[output_key] = validation[source_key]
    return evidence_pack


def _build_done_payload(session_id: int, evidence: list, validation: dict) -> dict:
    done_payload = {"event": "done", "sessionId": session_id, "evidence": evidence}
    if settings.answer_validation_done_field_enabled and validation.get("summary"):
        done_payload["validation"] = validation["summary"]
    if validation.get("anchor_resolution"):
        done_payload["anchorResolution"] = validation["anchor_resolution"]
    if validation.get("confirmed_anchor"):
        done_payload["confirmedAnchor"] = validation["confirmed_anchor"]
    if validation.get("agent_orchestration"):
        done_payload["agentOrchestration"] = validation["agent_orchestration"]
    return done_payload


@router.post("/chat")
async def chat(req: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 1. 取/建会话
    if req.session_id:
        session = await ai_agent.get_session(db, req.session_id, user.id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        session = await ai_agent.create_session(db, user.id)
    session_id = session.id

    # 2. 落库用户消息 + 组装上下文
    user_message = await ai_agent.add_message(db, session_id, "user", req.message)
    await ai_agent.update_session_intent(db, session_id, detect_intent(req.message))
    history = await ai_agent.get_recent_messages(db, session_id, limit=20)
    messages = [{"role": m.role, "content": m.content, "evidence": m.evidence}
                for m in history if m.role in ("system", "user", "assistant") and m.content]

    # 3. 流式生成 + 结束后落库助手消息
    async def event_stream():
        parts: list[str] = []
        evidence: list = []
        validation: dict = {}
        try:
            if settings.answer_thinking_event_enabled:
                yield _sse({"event": "thinking", "message": "正在整理证据并生成答案..."})
            async for token in run_chat(messages, db=db, audit_message_id=user_message.id,
                                        user_id=user.id, evidence_sink=evidence,
                                        validation_sink=validation):
                parts.append(token)
                yield _sse({"delta": token})
            answer = "".join(parts)
            evidence_pack = _build_assistant_evidence_pack(evidence, validation)
            async with AsyncSessionLocal() as s:
                await ai_agent.add_message(s, session_id, "assistant", answer, evidence=evidence_pack)
            done_payload = _build_done_payload(session_id, evidence, validation)
            yield _sse(done_payload)
            yield "data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001 —— 把错误以 SSE 事件返回，避免前端卡死
            yield _sse({"event": "error", "detail": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/evidence-detail")
async def get_evidence_detail(
        evidence_id: str = Query(..., description="Evidence ref, e.g. news:jjrb:... or [news:2726]"),
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
):
    _ = user
    detail = await resolve_evidence_detail(evidence_id, db=db)
    message = "获取证据详情成功" if detail.get("found") else "证据不存在"
    return success_response(message=message, data=detail)


@router.get("/sessions")
async def list_sessions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await ai_agent.list_sessions(db, user.id)
    data = [{"id": s.id, "title": s.title, "intent": s.intent,
             "updatedAt": s.updated_at} for s in rows]
    return success_response(message="获取会话列表成功", data=data)


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: int, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    session = await ai_agent.get_session(db, session_id, user.id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    rows = await ai_agent.get_recent_messages(db, session_id, limit=200)
    data = [{"id": m.id, "role": m.role, "content": m.content,
             "evidence": m.evidence, "createdAt": m.created_at} for m in rows]
    return success_response(message="获取会话消息成功", data=data)


@router.delete("/sessions")
async def clear_sessions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    count = await ai_agent.clear_sessions(db, user.id)
    return success_response(message=f"清空了{count}个会话")
