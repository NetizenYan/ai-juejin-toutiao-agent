"""
AI Agent 会话存储模型（Session Store）。

四张表（方案 B，见技术方案 §三·五），模型不直连：
  ai_session     一个会话
  ai_message     会话内每条消息（role: system/user/assistant/tool；evidence 存 Evidence Pack）
  ai_tool_call   每次工具调用轨迹（可回放/审计）
  ai_user_memory 用户长期记忆（偏好/关注领域，带原话出处；不存新闻事实）

注：与 backend/app/models/news.py、models/users.py 各自的 Base 隔离；FK 用字符串引用 user.id，
在数据库层生效，不依赖跨 Base 的 Python 元数据。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AiSession(Base):
    __tablename__ = "ai_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="会话ID")
    # 注：user 表属于另一个 DeclarativeBase，这里不在 ORM 层声明跨 Base 外键
    # （会导致 unit-of-work 解析失败）；DB 级外键已由 backend/sql/ai_tables.sql 建立。
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户ID")
    title: Mapped[Optional[str]] = mapped_column(String(255), comment="会话标题")
    intent: Mapped[Optional[str]] = mapped_column(
        String(32), comment="意图: news_qa / news_lookup / recommendation / web_research / general_chat"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class AiMessage(Base):
    __tablename__ = "ai_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="消息ID")
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_session.id", ondelete="CASCADE"), nullable=False, index=True, comment="会话ID"
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="system/user/assistant/tool")
    content: Mapped[str] = mapped_column(Text, default="", comment="消息内容")
    evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="Evidence Pack 引用来源")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")


class AiToolCall(Base):
    __tablename__ = "ai_tool_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="工具调用ID")
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_message.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属消息ID"
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="工具名")
    arguments: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="调用参数")
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="返回结果")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="耗时(ms)")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")


class AiUserMemory(Base):
    __tablename__ = "ai_user_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="记忆ID")
    # 同 AiSession：跨 Base 外键只在数据库层建立（scripts/ai_tables.sql）。
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户ID")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, comment="preference/interest")
    mem_key: Mapped[str] = mapped_column(String(64), nullable=False, comment="偏好维度或关注话题")
    value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="偏好取值")
    cue: Mapped[str] = mapped_column(String(64), default="", comment="适用情形")
    evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="来源会话/轮次与用户原话")
    hits: Mapped[int] = mapped_column(Integer, default=0, comment="被使用次数")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最近使用时间")
