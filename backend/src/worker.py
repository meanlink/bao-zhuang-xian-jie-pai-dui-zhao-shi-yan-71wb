import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.approvals import ensure_result_hash
from src.services.reports import deliver, DeliveryBlocked
from src.services.audit import record
logging.basicConfig(level=logging.INFO)


def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            j.approved=False;j.approval_status='pending'
            ensure_result_hash(j)
            record(db,'worker','job.completed',{'id':j.id,'result_hash':j.result_hash})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()


def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        due=list(db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())))
    for report in due:
        with Session() as db:
            r=db.get(Report, report.id)
            if not r or not r.enabled: continue
            started_at=time.time()
            try:
                d=deliver(db,r,started_at=started_at)
            except DeliveryBlocked as blocked:
                # 签署在发布前失效（撤签/改签）：暂停计划等待重新复核。
                if blocked.reason in ('approval_invalid','approval_changed','result_changed','result_not_ready'):
                    r.enabled=False;r.paused_reason='approval_invalid';r.paused_at=time.time()
                    record(db,'worker','report.paused',{'id':r.id,'reason':blocked.reason})
                    db.commit()
                else:
                    db.rollback()
                continue
            record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id,
                   'approval':d.approval_snapshot})
            db.commit()


def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
