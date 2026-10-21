from sqlalchemy.orm import Mapped, mapped_column,DeclarativeBase
from sqlalchemy import Integer, DateTime, ForeignKey, Index, UniqueConstraint
from datetime import datetime
from .users import User
from .news import News


class Base(DeclarativeBase):
    pass


class History(Base):
    """
    浏览历史表ORM模型
    """
    __tablename__ = 'history'

    # 创建索引
    __table_args__ = (
        # 每个用户每条新闻只有一条历史，add/delete 都按 (user_id, news_id) 定位
        UniqueConstraint('user_id', 'news_id', name='user_news_history_unique'),
        Index('fk_history_user_idx', 'user_id'),
        Index('fk_history_news_idx', 'news_id'),
        Index('idx_view_time', 'view_time'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="历史ID")
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey(User.id), nullable=False, comment="用户ID")
    news_id: Mapped[int] = mapped_column(Integer, ForeignKey(News.id), nullable=False, comment="新闻ID")
    view_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False, comment="浏览时间")


    def __repr__(self):
        return f"<History(id={self.id}, user_id={self.user_id}, news_id={self.news_id}, view_time={self.view_time})>"
