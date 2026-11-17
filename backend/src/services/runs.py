from sqlalchemy import select
from fastapi import HTTPException
from redis import Redis
from ..config.settings import REDIS_URL
from ..models.run import Run
from ..models.dictionary import DictVersion
from ..models.record import Record
from ..utils.serialization import row,now
from .sources import source_or_404,list_records
from .normalization import ensure_baseline,canonical_paths_for,active_lock_error
from .domain_validation import validate_parameters
from .audit import log
queue=Redis.from_url(REDIS_URL)
def get_run(db,id):
    r=db.get(Run,id)
    if not r:raise HTTPException(404,'未找到分析任务')
    return r
def create_run(db,user,data):
    s=source_or_404(db,data.source_id)
    lock=active_lock_error(db,s.id)
    if lock:raise HTTPException(409,lock)
    version=ensure_baseline(db,s)
    db.flush()
    records=list_records(db,s.id)
    if not records:raise HTTPException(422,'至少录入1个完整阅读会话后才能执行')
    try: params=validate_parameters(data.parameters)
    except ValueError as e:raise HTTPException(422,str(e))
    # 受理即冻结：词典版本与全部输入在此时点固定，排队后切版不改变本研究结果
    version=db.get(DictVersion,s.active_version_id)
    record_objs=list(db.scalars(select(Record).where(Record.source_id==s.id).order_by(Record.id)))
    canonical=canonical_paths_for(db,version,record_objs)
    frozen=[]
    for r in records:
        item=dict(r)
        item['canonical_path']=canonical[r['id']]
        frozen.append(item)
    r=Run(source_id=s.id,name=data.name,parameters=params,
          snapshot={'source':row(s),'records':frozen,'dict_version':row(version)},
          dict_version_id=version.id,created_at=now(),state='queued')
    db.add(r);db.flush();log(db,user,'run.queued',r.id,data.name+f'（冻结词典 v{version.version}）');db.commit()
    try:queue.rpush('analysis:queue',r.id)
    except Exception:
        r.state='failed';r.error='队列暂不可用，请重新创建任务';db.commit();raise HTTPException(503,r.error)
    return row(r)
def list_runs(db):
    return [{k:v for k,v in row(r).items() if k not in ('snapshot','result')} for r in db.scalars(select(Run).order_by(Run.id.desc()))]
