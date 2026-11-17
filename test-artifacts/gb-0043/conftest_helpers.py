"""章节归一词典切版：后端测试夹具（SQLite + 进程内 FakeRedis，不依赖外部服务）。"""
import os,sys,types,json,tempfile
from pathlib import Path
BACKEND=Path(__file__).resolve().parents[2]/'backend'
sys.path.insert(0,str(BACKEND))
TMP=Path(tempfile.mkdtemp(prefix='dict-test-'))
os.environ['DATABASE_URL']='sqlite:///'+str(TMP/'test.db')
os.environ['REDIS_URL']='redis://fake/0'
os.environ['ARTIFACT_DIR']=str(TMP/'artifacts')
os.environ['SEED_DEMO']='false'
os.environ['BACKFILL_BATCH_SIZE']='50'

class FakeRedis:
    def __init__(self):
        self.kv={};self.lists={}
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
            if self.lists.get(k):
                return k.encode(),str(self.lists[k].pop(0)).encode()
        return None
    def ping(self):return True

FAKE=FakeRedis()
import redis as _redis
_redis.Redis.from_url=lambda *a,**k:FAKE

from src.config.database import Base,engine,Session
from src.models import user as user_model,source as source_model,record as record_model
from src.models import run as run_model,note as note_model,audit as audit_model
from src.models import dictionary as dict_model,backfill as bf_model,normalized as norm_model
from src.utils.security import hash_password
from src.models.source import Source
from src.models.record import Record
from src.models.run import Run
from src.models.dictionary import DictVersion
from src.models.backfill import BackfillJob
from src.models.normalized import NormalizedSession
from src.utils.serialization import now
from src.services import normalization as norm
from src.services.backfill import run_backfill
from src.services.algorithm import calculate

class U:
    def __init__(self,email):self.email=email
ADMIN=U('admin@reading-transition.demo')

def fresh_db():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    return Session()

def make_source(db,name='测试文集'):
    s=Source(key='k-'+name,name=name,filename=name+'.csv',description='d');db.add(s);db.flush()
    norm.ensure_baseline(db,s,ADMIN.email);db.commit();return s

def add_record(db,source_id,reference,session,path):
    r=Record(source_id=source_id,reference=reference,values={'session':session,'path':path})
    db.add(r);db.commit();return r

def create_and_backfill(db,source_id,aliases):
    v,job_id=norm.create_version(db,ADMIN,source_id,aliases)
    run_backfill(job_id)
    db.expire_all()
    return db.get(DictVersion,v['id']),db.get(BackfillJob,job_id)
