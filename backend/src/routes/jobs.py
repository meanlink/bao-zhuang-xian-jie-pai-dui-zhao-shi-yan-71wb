from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from src.config.database import get_db
from src.models import Job
from src.schemas.job import JobInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs, approvals
from src.services.audit import record
from src.utils.serialization import job_dict

router = APIRouter(prefix='/jobs')


class OpinionInput(BaseModel):
    opinion: str = Field(default='', max_length=600)
    note: str = Field(default='', max_length=300)


def _with_live_approval(db, rows):
    """列表用实时有效票校正批准状态，避免结果变化后仍显示旧批准。"""
    out = []
    for j in rows:
        state = approvals.effective_status(db, j)
        out.append({**job_dict(j), 'approval_status': state,
                    'approved': state == 'approved'})
    return out


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    rows = list(db.scalars(select(Job).order_by(Job.id.desc()).limit(100)))
    return _with_live_approval(db, rows)


@router.post('', status_code=201)
def create(data: JobInput, db=Depends(get_db), u=Depends(can_write)):
    j = jobs.create(db, data, u)
    record(db, u.email, 'job.create', {'id': j.id, 'params': j.params})
    db.commit()
    jobs.enqueue(j.id)
    return job_dict(j)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    j = db.get(Job, id)
    if not j:
        raise HTTPException(404, '分析任务不存在')
    return _with_live_approval(db, [j])[0]


@router.get('/{id}/approvals')
def approval_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    j = db.get(Job, id)
    if not j:
        raise HTTPException(404, '分析任务不存在')
    return approvals.detail(db, j)


def _signed_payload(db, j):
    d = approvals.detail(db, j)
    return {**job_dict(j), 'approval_status': d['status'], 'approved': d['approved'],
            'approval': d}


@router.post('/{id}/approvals/sign')
def sign(id: int, data: OpinionInput | None = None, db=Depends(get_db), u=Depends(admin_only)):
    j = approvals.sign(db, id, u, data.opinion if data else '')
    db.commit()
    return _signed_payload(db, j)


@router.post('/{id}/approvals/revoke')
def revoke(id: int, data: OpinionInput | None = None, db=Depends(get_db), u=Depends(admin_only)):
    j = approvals.revoke(db, id, u, data.note if data else '')
    db.commit()
    return _signed_payload(db, j)


@router.post('/{id}/approve')
def approve(id: int, data: OpinionInput | None = None, db=Depends(get_db), u=Depends(admin_only)):
    """兼容入口：单次调用只计一票，仍需第二名负责人复核后才算批准。"""
    j = approvals.sign(db, id, u, data.opinion if data else '')
    db.commit()
    return _signed_payload(db, j)
