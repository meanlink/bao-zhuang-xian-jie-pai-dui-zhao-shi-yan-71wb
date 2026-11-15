"""双人复核签署：票绑定结果指纹、发起人回避、撤签退回待复核并暂停计划。"""
import time
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.models import Job, Report, ApprovalVote, ApprovalEvent
from src.services.audit import record
from src.utils.serialization import checksum

REQUIRED_SIGNATURES = 2


def result_hash(job):
    """结果指纹：参数 + 计算结果共同决定，票只对签署当时的结果有效。"""
    return checksum({'params': job.params or {}, 'result': job.result or {}})


def ensure_result_hash(job):
    if not job.result_hash:
        job.result_hash = result_hash(job)
    return job.result_hash


def current_hash(job):
    """当前结果指纹始终按现存参数与结果实时计算，缓存字段只用于展示/迁移。"""
    return result_hash(job)


def _lock_job(db, job_id):
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, '分析任务不存在')
    return job


def _lock_user_vote(db, job_id, user_id):
    """锁顺序固定为 任务 → 票；InnoDB 下行锁先加再查，避免并发双签丢更新。"""
    return db.scalar(select(ApprovalVote).where(
        ApprovalVote.job_id == job_id, ApprovalVote.user_id == user_id).with_for_update())


def active_votes(db, job, locking=False):
    """与当前结果指纹一致、仍有效的签署票，按 (用户) 去重由唯一约束保证。

    locking=True 用于发布前校验：MySQL REPEATABLE READ 下普通 SELECT 读事务快照，
    锁定读才拿得到最新已提交的票与撤签结果。
    """
    stamp = current_hash(job)
    stmt = (select(ApprovalVote)
            .where(ApprovalVote.job_id == job.id,
                   ApprovalVote.state == 'active',
                   ApprovalVote.result_hash == stamp)
            .order_by(ApprovalVote.signed_at, ApprovalVote.id))
    if locking:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(stmt))


def refresh_status(db, job):
    votes = active_votes(db, job)
    if job.status == 'completed' and len(votes) >= REQUIRED_SIGNATURES:
        job.approved = True
        job.approval_status = 'approved'
    else:
        job.approved = False
        job.approval_status = 'pending'
    return job


def _add_event(db, job, user, action, vote=None, opinion='', note='', stamp=None):
    ev = ApprovalEvent(
        job_id=job.id,
        vote_id=vote.id if vote else None,
        user_id=user.id,
        actor_name=getattr(user, 'name', '') or '',
        actor_email=getattr(user, 'email', '') or '',
        action=action,
        opinion=opinion or '',
        result_hash=stamp or result_hash(job),
        note=note or '',
        at=time.time(),
    )
    db.add(ev)
    db.flush()
    return ev


def _same_vote_open(vote, job):
    """该负责人在当前结果版本上已有有效票，则视为重复签署。"""
    return bool(vote and vote.state == 'active' and vote.result_hash == current_hash(job))


def sign(db, job_id, user, opinion=''):
    """一名负责人签署。重复签署不重复计票，撤签后可重新签署。"""
    if getattr(user, 'role', None) != 'admin':
        raise HTTPException(403, '只有业务负责人可以复核签署')
    job = _lock_job(db, job_id)
    if job.created_by == user.id:
        raise HTTPException(403, '分析发起人必须回避，不能批准本人的分析结论')
    if job.status != 'completed':
        raise HTTPException(409, '仅已完成的分析结果可以复核签署')
    ensure_result_hash(job)
    opinion = (opinion or '').strip()
    if len(opinion) > 600:
        raise HTTPException(422, '复核意见不能超过 600 字')

    vote = _lock_user_vote(db, job.id, user.id)
    if _same_vote_open(vote, job):
        # 同一负责人重复提交：保持原票，不重复计票，也不再追加签署经过。
        refresh_status(db, job)
        return job
    stamp = current_hash(job)
    if vote:
        vote.state = 'active'
        vote.result_hash = stamp
        vote.opinion = opinion
        vote.signed_at = time.time()
        vote.revoked_at = None
        vote.revoke_reason = ''
        db.flush()
    else:
        try:
            with db.begin_nested():
                vote = ApprovalVote(
                    job_id=job.id, user_id=user.id,
                    approver_name=getattr(user, 'name', '') or '',
                    approver_email=getattr(user, 'email', '') or '',
                    opinion=opinion, result_hash=stamp, state='active',
                    signed_at=time.time(),
                )
                db.add(vote)
                db.flush()
        except IntegrityError:
            # 并发重复提交由 (job_id, user_id) 唯一约束兜底：读回已落库的票，
            # 当作重复签署处理，不重复计票，也不再追加签署经过。
            db.expire_all()
            vote = _lock_user_vote(db, job.id, user.id)
            if not vote:
                raise
            refresh_status(db, job)
            return job
    # 签署即确认当前结果版本；历史上针对旧结果的票自然失效。
    job.result_hash = stamp
    _add_event(db, job, user, 'approval.sign', vote=vote, opinion=vote.opinion, stamp=stamp)
    refresh_status(db, job)
    record(db, user.email, 'job.approve', {
        'id': job.id, 'vote': vote.id, 'result_hash': job.result_hash,
        'approval_status': job.approval_status})
    db.flush()
    return job


def revoke(db, job_id, user, reason=''):
    """签署人撤签：分析退回待复核，关联计划暂停，历史归档保留原签署依据。"""
    if getattr(user, 'role', None) != 'admin':
        raise HTTPException(403, '只有业务负责人可以撤回签署')
    job = _lock_job(db, job_id)
    db.refresh(job)
    vote = _lock_user_vote(db, job.id, user.id)
    if not vote or vote.state != 'active':
        raise HTTPException(409, '没有可撤回的有效签署')
    reason = (reason or '').strip()
    if len(reason) > 300:
        raise HTTPException(422, '撤签说明不能超过 300 字')
    now = time.time()
    stamp = current_hash(job)
    vote.state = 'revoked'
    vote.revoked_at = now
    vote.revoke_reason = reason
    db.flush()
    _add_event(db, job, user, 'approval.revoke', vote=vote, opinion=vote.opinion,
               note=reason, stamp=stamp)
    refresh_status(db, job)
    # 撤签生效：此后该分析的所有分发计划暂停，等待重新凑齐有效签署后人工恢复。
    for r in db.scalars(select(Report).where(Report.job_id == job.id).with_for_update()):
        if r.enabled:
            r.enabled = False
            r.paused_reason = 'approval_revoked'
            r.paused_at = now
    record(db, user.email, 'job.revoke', {
        'id': job.id, 'vote': vote.id, 'reason': reason,
        'approval_status': job.approval_status})
    db.flush()
    return job


def effective_status(db, job):
    """按当前有效票实时推导状态，避免结果变化后仍显示旧批准。"""
    if job.status != 'completed':
        return 'pending'
    return 'approved' if len(active_votes(db, job)) >= REQUIRED_SIGNATURES else 'pending'


def detail(db, job):
    votes = list(db.scalars(select(ApprovalVote).where(
        ApprovalVote.job_id == job.id).order_by(ApprovalVote.signed_at, ApprovalVote.id)))
    events = list(db.scalars(select(ApprovalEvent).where(
        ApprovalEvent.job_id == job.id).order_by(ApprovalEvent.at, ApprovalEvent.id)))
    stamp = current_hash(job)
    active = [v for v in votes if v.state == 'active' and v.result_hash == stamp]
    return {
        'status': effective_status(db, job),
        'approved': len(active) >= REQUIRED_SIGNATURES,
        'required': REQUIRED_SIGNATURES,
        'received': len(active),
        'result_hash': stamp,
        'created_by': job.created_by,
        'votes': [{
            'id': v.id, 'user_id': v.user_id, 'approver_name': v.approver_name,
            'approver_email': v.approver_email, 'opinion': v.opinion,
            'result_hash': v.result_hash, 'state': v.state,
            'current_result': v.result_hash == stamp,
            'signed_at': v.signed_at, 'revoked_at': v.revoked_at,
            'revoke_reason': v.revoke_reason,
        } for v in votes],
        'events': [{
            'id': e.id, 'vote_id': e.vote_id, 'user_id': e.user_id,
            'actor_name': e.actor_name, 'actor_email': e.actor_email,
            'action': e.action, 'opinion': e.opinion,
            'result_hash': e.result_hash, 'note': e.note, 'at': e.at,
        } for e in events],
    }


def approval_snapshot(db, job, generated_at=None, locking=False):
    """归档时冻结当时的有效签署，撤签不改变已发归档的依据。"""
    votes = active_votes(db, job, locking=locking)
    stamp = current_hash(job)
    return {
        'job_id': job.id,
        'job_name': job.name,
        'result_hash': stamp,
        'approval_status': 'approved' if len(votes) >= REQUIRED_SIGNATURES else 'pending',
        'required': REQUIRED_SIGNATURES,
        'generated_at': generated_at or time.time(),
        'signatures': [{
            'vote_id': v.id,
            'approver_name': v.approver_name,
            'approver_email': v.approver_email,
            'opinion': v.opinion,
            'result_hash': v.result_hash,
            'signed_at': v.signed_at,
        } for v in votes],
    }
