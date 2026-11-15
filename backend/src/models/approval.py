from sqlalchemy import String, Double, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class ApprovalVote(Base):
    """一名负责人对某次分析结果的一票复核签署。

    每个 (分析任务, 用户) 只保留一行当前签署，重复签署只更新状态；
    结果指纹把票绑定到签署当时的结果版本，意见随票保存。
    """
    __tablename__ = 'approval_votes'
    __table_args__ = (UniqueConstraint('job_id', 'user_id', name='uq_approval_job_user'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    approver_name: Mapped[str] = mapped_column(String(80), default='')
    approver_email: Mapped[str] = mapped_column(String(150), default='')
    opinion: Mapped[str] = mapped_column(String(600), default='')
    result_hash: Mapped[str] = mapped_column(String(64), default='')
    state: Mapped[str] = mapped_column(String(20), default='active')
    signed_at: Mapped[float] = mapped_column(Double)
    revoked_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    revoke_reason: Mapped[str] = mapped_column(String(300), default='')


class ApprovalEvent(Base):
    """签署与撤签的只追加经过，用于结果页追溯。"""
    __tablename__ = 'approval_events'

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    vote_id: Mapped[int | None] = mapped_column(ForeignKey('approval_votes.id'), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(80), default='')
    actor_email: Mapped[str] = mapped_column(String(150), default='')
    action: Mapped[str] = mapped_column(String(20))
    opinion: Mapped[str] = mapped_column(String(600), default='')
    result_hash: Mapped[str] = mapped_column(String(64), default='')
    note: Mapped[str] = mapped_column(String(300), default='')
    at: Mapped[float] = mapped_column(Double)
