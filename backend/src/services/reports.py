import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from src.models import Job, Report, Delivery, ApprovalEvent
from src.config.settings import ARTIFACT_DIR
from src.services import approvals


class DeliveryBlocked(Exception):
    """分发在发布前被拦住；reason 用于决定是否暂停计划。"""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _approval_valid(db, job, started_at, locking=False):
    """发布前的最终校验：结果指纹、双人有效签署，以及分发开始后是否发生撤签。"""
    if job.status != 'completed':
        return False, 'result_not_ready'
    if not job.result_hash or job.result_hash != approvals.current_hash(job):
        return False, 'result_changed'
    if job.approval_status != 'approved' or not job.approved:
        return False, 'approval_invalid'
    if len(approvals.active_votes(db, job, locking=locking)) < approvals.REQUIRED_SIGNATURES:
        return False, 'approval_invalid'
    # 撤签与分发并发：以撤签生效为界。分发开算之后才生效的撤签，
    # 即使随后重新签署补齐票数，本次发布也必须拦住。
    if started_at is not None:
        stmt = select(ApprovalEvent.id).where(
            ApprovalEvent.job_id == job.id,
            ApprovalEvent.action == 'approval.revoke',
            ApprovalEvent.at >= started_at).limit(1)
        if locking:
            stmt = stmt.with_for_update()
        changed = db.scalar(stmt)
        if changed:
            return False, 'approval_changed'
    return True, ''


def validate_for_report(db, job):
    ok, reason = _approval_valid(db, job, None)
    if not ok:
        raise HTTPException(409, '请先选择已完成且由两名不同负责人共同复核的分析结果')
    return True


def create(db, data, user=None):
    j = db.get(Job, data.job_id)
    if not j:
        raise HTTPException(404, '分析任务不存在')
    validate_for_report(db, j)
    r = Report(name=data.name, job_id=j.id, destination=data.destination,
               interval_seconds=data.interval_seconds,
               next_run=time.time() + data.delay_seconds, enabled=True,
               paused_reason='')
    db.add(r)
    db.flush()
    return r


def pause(db, report, reason, at=None):
    report.enabled = False
    report.paused_reason = reason[:80]
    report.paused_at = at or time.time()
    db.flush()
    return report


def resume(db, report):
    """负责人手动恢复：重新凑齐有效签署后，才允许恢复计划。"""
    job = db.get(Job, report.job_id)
    if not job:
        raise HTTPException(409, '关联分析任务不存在')
    validate_for_report(db, job)
    report.enabled = True
    report.paused_reason = ''
    report.paused_at = None
    db.flush()
    return report


def deliver(db, report, started_at=None):
    """生成并发布一份归档。

    先在无锁状态下生成内容，再锁住计划与分析做发布前最终校验：
    - 若撤签在分发开算之后、发布之前生效，本次发布被拦住；
    - 若分发先完成校验并持有任务锁，撤签必须等归档落库后才生效，
      归档仍是撤签生效之前的历史依据。
    """
    if started_at is None:
        started_at = time.time()
    snapshot_report = db.get(Report, report.id)
    if not snapshot_report:
        raise DeliveryBlocked('disabled')
    out = io.StringIO()
    out.write('﻿')
    job = db.get(Job, snapshot_report.job_id)
    if not job:
        raise DeliveryBlocked('approval_invalid')
    table = (job.result or {}).get('table', {})
    cols = table.get('columns', [])
    writer = csv.writer(out)

    def safe(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        text = str(v)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text

    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows', []):
        writer.writerow([safe(row.get(c['key'], '')) for c in cols])
    data = out.getvalue().encode('utf-8')

    # 发布临界区：按"任务 → 计划"的固定顺序加行锁，与撤签（同样先锁任务）
    # 串行化，避免死锁；populate_existing 保证拿到最新已提交状态，而非事务快照。
    locked_job = db.scalar(
        select(Job).where(Job.id == snapshot_report.job_id)
        .with_for_update().execution_options(populate_existing=True))
    if not locked_job:
        raise DeliveryBlocked('approval_invalid')
    job = locked_job
    locked = db.scalar(
        select(Report).where(Report.id == report.id)
        .with_for_update().execution_options(populate_existing=True))
    if not locked or not locked.enabled:
        raise DeliveryBlocked('disabled')
    report = locked
    ok, reason = _approval_valid(db, job, started_at, locking=True)
    if not ok:
        raise DeliveryBlocked(reason)
    now = time.time()
    snapshot = approvals.approval_snapshot(db, job, now, locking=True)
    delivery = Delivery(report_id=report.id, created_at=now,
                        checksum=hashlib.sha256(data).hexdigest(),
                        filename='', destination=report.destination,
                        approval_snapshot=snapshot)
    db.add(delivery)
    db.flush()
    delivery.filename = f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename), 'wb') as f:
        f.write(data)
    with open(os.path.join(ARTIFACT_DIR, delivery.filename + '.json'), 'w') as f:
        json.dump({'job': job.name, 'params': job.params, 'result': job.result,
                   'checksum': delivery.checksum, 'approval': snapshot},
                  f, ensure_ascii=False, allow_nan=False)
    report.next_run = time.time() + report.interval_seconds
    return delivery
