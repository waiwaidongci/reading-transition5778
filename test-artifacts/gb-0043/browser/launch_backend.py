"""浏览器验收用后端启动器：SQLite + FakeRedis，自动种子，无外部依赖。"""
import os,sys,tempfile
from pathlib import Path
BACKEND=Path(__file__).resolve().parents[3]/'backend'
sys.path.insert(0,str(BACKEND))
TMP=Path(tempfile.mkdtemp(prefix='browser-backend-'))
os.environ['DATABASE_URL']='sqlite:///'+str(TMP/'browser.db')
os.environ['REDIS_URL']='redis://fake/0'
os.environ['ARTIFACT_DIR']=str(TMP/'artifacts')
os.environ['SEED_DEMO']='true'
os.environ['BACKFILL_BATCH_SIZE']='100'

class FakeRedis:
    def __init__(self):self.kv={};self.lists={}
    def set(self,k,v,nx=False,ex=None):
        if nx and k in self.kv:return None
        self.kv[k]=v if isinstance(v,bytes) else str(v).encode();return True
    def get(self,k):return self.kv.get(k)
    def delete(self,k):return self.kv.pop(k,None) is not None
    def rpush(self,k,*vals):
        for v in vals:self.lists.setdefault(k,[]).append(v)
        return len(self.lists[k])
    def blpop(self,keys,timeout=0):
        for k in ([keys] if isinstance(keys,str) else keys):
            if self.lists.get(k):return k.encode(),str(self.lists[k].pop(0)).encode()
        return None
    def ping(self):return True

import redis as _redis
FAKE=FakeRedis()
_redis.Redis.from_url=lambda *a,**k:FAKE

import threading,time
def worker_loop():
    # 同进程 worker：周期性排空两个队列，模拟真实独立 worker 的消费语义
    import importlib
    from src.config.database import Session
    from src.models.run import Run
    from src.worker import execute
    from src.services.backfill import run_backfill
    while True:
        item=FAKE.blpop(['backfill:queue','analysis:queue'],timeout=0)
        if not item:
            time.sleep(0.2);continue
        channel=item[0].decode();payload=int(item[1])
        try:
            if channel=='backfill:queue':run_backfill(payload)
            else:execute(payload)
        except Exception:
            import logging;logging.exception('browser worker error')

import uvicorn
if __name__=='__main__':
    os.chdir(BACKEND)
    threading.Thread(target=worker_loop,daemon=True).start()
    uvicorn.run('src.main:app',host='127.0.0.1',port=8011,log_level='warning')
