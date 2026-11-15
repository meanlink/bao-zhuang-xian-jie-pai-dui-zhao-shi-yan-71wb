import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit
from src.services.business import metadata, seed_records, analyze
from src.services import approvals
from src.services.reports import deliver
from src.utils.security import hash_password
from src.utils.serialization import checksum


def seed():
    migrate()
    with Session() as db:
        for role,name,email in [
            ('admin','林知 · 业务负责人','admin@demo.local'),
            ('admin','沈岚 · 质量负责人','admin2@demo.local'),
            ('analyst','陈舟 · 分析员','analyst@demo.local'),
            ('viewer','周禾 · 观察员','viewer@demo.local'),
        ]:
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            owner=db.scalar(select(User).where(User.email=='analyst@demo.local'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=owner.id,created_at=time.time()-3600,finished_at=time.time()-3595)
            approvals.ensure_result_hash(j)
            db.add(j);db.flush()
            # 双人复核：两名不同负责人各签一票；发起人（分析员）回避。
            reviewers=[
                (db.scalar(select(User).where(User.email=='admin@demo.local')),'基线数据完整，节拍口径可复核。'),
                (db.scalar(select(User).where(User.email=='admin2@demo.local')),'抽查参数与片段分配，同意作为分发依据。'),
            ]
            for reviewer,opinion in reviewers:
                approvals.sign(db,j.id,reviewer,opinion)
            db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True,paused_reason='')
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
