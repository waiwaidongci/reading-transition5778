import json,time,logging
from redis import Redis
from sqlalchemy import select
from .config.database import Session
from .config.settings import REDIS_URL,ARTIFACT_DIR
from .models.run import Run
from .models.dictionary import DictVersion
from .models import source,record,user,note,audit
from .services.algorithm import calculate
from .services.audit import log
from .services.export import csv_response
from .services.backfill import run_backfill
queue=Redis.from_url(REDIS_URL)
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
def execute(id):
    with Session() as db:
        r=db.get(Run,id)
        if not r or r.state!='queued':return
        r.state='running';db.commit()
        try:
            # 使用受理时冻结的输入与词典版本；排队后的切版不影响本研究
            version=db.get(DictVersion,r.dict_version_id) if r.dict_version_id else None
            result=calculate(r.snapshot['records'],r.parameters,version)
            json.dumps(result,allow_nan=False)
            r.result=result;r.state='completed'
            response=csv_response(result,'run.csv')
            (ARTIFACT_DIR/f'run-{r.id}.csv').write_bytes(response.body)
            log(db,'worker','run.completed',r.id)
        except Exception as e:
            logging.exception('analysis failed');r.state='failed';r.error=str(e)[:2000]
            log(db,'worker','run.failed',r.id,r.error)
        db.commit()
def main():
    while True:
        (ARTIFACT_DIR/'heartbeat').write_text(str(time.time()))
        # 回填队列优先，避免大回填期间分析任务饥饿：轮流 BLPOP 两个队列
        value=queue.blpop(['backfill:queue','analysis:queue'],timeout=2)
        if not value:continue
        channel,payload=value[0].decode(),int(value[1])
        if channel=='backfill:queue':
            try:run_backfill(payload)
            except Exception:logging.exception('backfill loop error')
        else:
            execute(payload)
if __name__=='__main__':main()
