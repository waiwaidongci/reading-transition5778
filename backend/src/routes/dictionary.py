from fastapi import APIRouter,Depends
from ..config.database import db_session
from ..schemas.dictionary import DictVersionInput,AliasPreviewInput
from ..services.auth import current_user,writer
from ..services.backfill import queue
from ..controllers.dictionary import DictionaryController as C
router=APIRouter()
@router.get('/sources/{id}/dictionary/versions')
def versions(id:int,db=Depends(db_session),u=Depends(current_user)):return C.versions(db,id)
@router.get('/sources/{id}/dictionary/jobs')
def jobs(id:int,db=Depends(db_session),u=Depends(current_user)):return C.jobs(db,id)
@router.post('/sources/{id}/dictionary/preview')
def preview(id:int,data:AliasPreviewInput,db=Depends(db_session),u=Depends(writer)):return C.preview(db,u,id,data)
@router.post('/sources/{id}/dictionary/versions')
def create(id:int,data:DictVersionInput,db=Depends(db_session),u=Depends(writer)):
    v=C.create(db,u,id,data)
    try:queue.rpush('backfill:queue',v['backfill_job_id'])
    except Exception:
        # 入队失败：版本保留 building，任务可在队列恢复后由人工重试入口处理
        pass
    return v
@router.post('/sources/{id}/dictionary/revert')
def revert(id:int,db=Depends(db_session),u=Depends(writer)):
    return C.revert(db,u,id)
@router.post('/dictionary/versions/{version_id}/publish')
def publish(version_id:int,db=Depends(db_session),u=Depends(writer)):return C.publish(db,u,version_id)
@router.post('/dictionary/jobs/{job_id}/retry')
def retry(job_id:int,db=Depends(db_session),u=Depends(writer)):
    job=C.retry(db,u,job_id)
    try:queue.rpush('backfill:queue',job_id)
    except Exception:pass
    return job
