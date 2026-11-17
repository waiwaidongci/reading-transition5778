import logging,os,time
from redis import Redis
from sqlalchemy import select
from ..config.settings import REDIS_URL
from ..config.database import Session
from ..models.backfill import BackfillJob
from ..models.dictionary import DictVersion
from ..models.record import Record
from ..models.normalized import NormalizedSession
from ..utils.serialization import now
from .normalization import mapping_of,split_path,fold_path,join_path
from .audit import log
queue=Redis.from_url(REDIS_URL)
BATCH_SIZE=int(os.getenv('BACKFILL_BATCH_SIZE','500'))
LOCK_TTL=int(os.getenv('BACKFILL_LOCK_TTL','30'))
def _lock_key(source_id):return f'dictionary:lock:source:{source_id}'
def acquire_source_lock(source_id,token):
    return bool(queue.set(_lock_key(source_id),token,nx=True,ex=LOCK_TTL))
def release_source_lock(source_id,token):
    # 仅持有者可释放，避免误删别人的锁
    current=queue.get(_lock_key(source_id))
    if current is not None and current.decode()==token:
        queue.delete(_lock_key(source_id))
def run_backfill(job_id):
    """分批回填归一路径。每批一个事务提交进度，中断后可从 last_record_id 续跑；重试幂等不新增接续。"""
    with Session() as db:
        job=db.get(BackfillJob,job_id)
        if not job or job.state not in ('queued','running'):
            return
        version=db.get(DictVersion,job.dict_version_id)
        if not version:
            job.state='failed';job.error='词典版本不存在';job.updated_at=now();db.commit();return
        source_id=job.source_id
        token=f'backfill-{job_id}-{now()}'
        if not acquire_source_lock(source_id,token):
            # 并发切版只允许一个回填；未拿到锁的任务延迟后回队，避免忙等
            time.sleep(2)
            queue.rpush('backfill:queue',job_id)
            return
        try:
            job.state='running';job.attempts=(job.attempts or 0)+1;job.updated_at=now()
            # 续跑时刷新总量：回填期间接收的新会话也纳入进度与发布校验
            job.total_sessions=db.query(Record).filter(Record.source_id==source_id).count()
            log(db,'worker','dict.backfill_started',job.id,f'v{version.version} 从 {job.processed_sessions} 续跑')
            db.commit()
            mapping=mapping_of(version)
            while True:
                # 刷新锁，长回填期间防止过期被他人抢占；仅持有者可续期
                current=queue.get(_lock_key(source_id))
                if current is None or current.decode()!=token:
                    raise RuntimeError('回填锁丢失，已停止以避免并发切版')
                queue.set(_lock_key(source_id),token,ex=LOCK_TTL)
                batch=list(db.scalars(
                    select(Record).where(Record.source_id==source_id,Record.id>job.last_record_id)
                    .order_by(Record.id).limit(BATCH_SIZE)))
                if not batch:
                    break
                existing_ids={rid for (rid,) in db.execute(
                    select(NormalizedSession.record_id).where(
                        NormalizedSession.dict_version_id==version.id,
                        NormalizedSession.record_id.in_([r.id for r in batch])))}
                for r in batch:
                    canonical=join_path(fold_path(split_path(r.values['path']),mapping))
                    if r.id in existing_ids:
                        # 重试幂等：已存在则覆盖为同一计算结果，不新增行、不新增接续
                        obj=db.scalar(select(NormalizedSession).where(
                            NormalizedSession.dict_version_id==version.id,
                            NormalizedSession.record_id==r.id))
                        obj.canonical_path=canonical
                    else:
                        db.add(NormalizedSession(dict_version_id=version.id,record_id=r.id,canonical_path=canonical))
                job.last_record_id=batch[-1].id
                job.processed_sessions=(job.processed_sessions or 0)+len(batch)
                job.updated_at=now()
                db.commit()
                # 每批落盘后即持久化进度，进程中断可从该水位继续
            total=db.query(Record).filter(Record.source_id==source_id).count()
            job.total_sessions=total;job.processed_sessions=db.query(NormalizedSession).filter(
                NormalizedSession.dict_version_id==version.id).count()
            job.state='completed';job.error='';job.updated_at=now()
            log(db,'worker','dict.backfill_completed',job.id,f'v{version.version} 共{job.processed_sessions}会话')
            db.commit()
        except Exception as e:
            logging.exception('backfill failed')
            db.rollback()
            fresh=db.get(BackfillJob,job_id)
            if fresh:
                fresh.state='failed';fresh.error=str(e)[:2000];fresh.updated_at=now()
                log(db,'worker','dict.backfill_failed',job_id,fresh.error)
                db.commit()
        finally:
            release_source_lock(source_id,token)
