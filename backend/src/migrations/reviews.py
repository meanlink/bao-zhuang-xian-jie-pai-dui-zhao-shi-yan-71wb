"""增量迁移：把旧的单人批准记录退回待复核，并补齐双人复核所需字段。

可在每次启动时重复执行：只添加缺失列、只迁移仍未迁移的旧记录。
"""
import time
from sqlalchemy import inspect, text
from src.config.database import Base, engine


# 列定义按方言区分；MySQL 的 JSON/DOUBLE 与 SQLite 不同。
_COLUMNS = {
    'jobs': [
        ('approval_status', {'mysql': "VARCHAR(20) NOT NULL DEFAULT 'pending'", 'default': "VARCHAR(20) NOT NULL DEFAULT 'pending'"}),
        ('result_hash', {'mysql': "VARCHAR(64) NOT NULL DEFAULT ''", 'default': "VARCHAR(64) NOT NULL DEFAULT ''"}),
    ],
    'reports': [
        ('paused_reason', {'mysql': "VARCHAR(80) NOT NULL DEFAULT ''", 'default': "VARCHAR(80) NOT NULL DEFAULT ''"}),
        ('paused_at', {'mysql': 'DOUBLE NULL', 'default': 'FLOAT NULL'}),
    ],
    'deliveries': [
        ('approval_snapshot', {'mysql': 'JSON NULL', 'default': 'TEXT NULL'}),
    ],
}


def _add_missing_columns():
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for table, columns in _COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c['name'] for c in insp.get_columns(table)}
            for name, types in columns:
                if name in present:
                    continue
                ddl = types['mysql'] if dialect == 'mysql' else types['default']
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))


def _backfill_result_hashes():
    from sqlalchemy import select
    from src.config.database import Session
    from src.models import Job
    from src.services.approvals import ensure_result_hash
    with Session() as db:
        changed = 0
        for job in db.scalars(select(Job).where(Job.status == 'completed', Job.result_hash == '')):
            ensure_result_hash(job)
            changed += 1
        if changed:
            db.commit()
        return changed


def _retire_legacy_approvals():
    """旧的 approved=True 只有一人批准，不能作为双人复核；统一退回待复核。"""
    from sqlalchemy import select
    from src.config.database import Session
    from src.models import Job, Report, ApprovalVote, ApprovalEvent, Audit
    with Session() as db:
        migrated = 0
        for job in db.scalars(select(Job).where(Job.approved == True)):  # noqa: E712
            votes = db.scalar(select(ApprovalVote).where(
                ApprovalVote.job_id == job.id, ApprovalVote.state == 'active').limit(1))
            if votes:
                continue
            job.approved = False
            job.approval_status = 'pending'
            db.add(ApprovalEvent(
                job_id=job.id, vote_id=None, user_id=None,
                actor_name='system', actor_email='migration',
                action='approval.migrated', opinion='',
                result_hash=job.result_hash or '', note='旧单人批准记录迁移为待复核',
                at=time.time()))
            # 旧批准不再有效，关联计划暂停；历史归档不受影响。
            for report in db.scalars(select(Report).where(
                    Report.job_id == job.id, Report.enabled == True)):  # noqa: E712
                report.enabled = False
                report.paused_reason = 'legacy_approval'
                report.paused_at = time.time()
            migrated += 1
        if migrated:
            db.add(Audit(actor='migration', action='approval.legacy_pending',
                         detail={'jobs': migrated}, at=time.time()))
            db.commit()
        return migrated


def run():
    _add_missing_columns()
    Base.metadata.create_all(engine)
    hashes = _backfill_result_hashes()
    migrated = _retire_legacy_approvals()
    return {'result_hashes': hashes, 'legacy_approvals': migrated}
