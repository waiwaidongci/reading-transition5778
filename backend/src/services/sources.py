import secrets
from fastapi import HTTPException
from sqlalchemy import select,func
from ..models.source import Source
from ..models.record import Record
from ..models.dictionary import DictVersion
from ..utils.serialization import row
from .audit import log
from .domain_validation import validate_record
from .normalization import ensure_baseline,canonical_paths_for,active_lock_error
def list_sources(db):
    rows=[]
    for s in db.scalars(select(Source).order_by(Source.id)):
        d=row(s);d['record_count']=db.scalar(select(func.count()).select_from(Record).where(Record.source_id==s.id));rows.append(d)
    return rows
def source_or_404(db,id):
    s=db.get(Source,id)
    if not s:raise HTTPException(404,'未找到来源批次')
    return s
def save_source(db,user,data,id=None):
    if id:
        s=source_or_404(db,id)
        for k,v in data.model_dump().items():setattr(s,k,v)
        db.add(s);db.flush();log(db,user,'source.updated',s.id,s.name);db.commit();return row(s)
    s=Source(key='user-'+secrets.token_hex(10))
    for k,v in data.model_dump().items():setattr(s,k,v)
    db.add(s);db.flush()
    ensure_baseline(db,s,user.email)
    log(db,user,'source.created',s.id,s.name);db.commit()
    return row(s)
def list_records(db,id):
    s=source_or_404(db,id)
    records=[row(x) for x in db.scalars(select(Record).where(Record.source_id==id).order_by(Record.id))]
    # 页面只见完整旧版或新版：只按已发布版本展示归一路径，回填中的版本不出现
    if s.active_version_id:
        version=db.get(DictVersion,s.active_version_id)
    else:
        # 兼容历史数据：首次读取时补齐 v1 空词典基线并持久化
        version=ensure_baseline(db,s);db.commit()
    canonical=canonical_paths_for(db,version,[db.get(Record,r['id']) for r in records]) if records else {}
    for r in records:
        r['canonical_path']=canonical.get(r['id'],r['values']['path'])
    return records
def add_records(db,user,id,data):
    source_or_404(db,id)
    lock=active_lock_error(db,id)
    if lock:raise HTTPException(409,lock)
    validated=[];refs=set()
    for r in data.records:
        if r.reference in refs:raise HTTPException(422,'批内样本编号重复')
        refs.add(r.reference)
        try: values=validate_record(r.values)
        except ValueError as e:raise HTTPException(422,str(e))
        if db.scalar(select(Record.id).where(Record.source_id==id,Record.reference==r.reference)):raise HTTPException(409,'样本编号已存在：'+r.reference)
        validated.append(Record(source_id=id,reference=r.reference,values=values))
    db.add_all(validated);log(db,user,'records.added',id,str(len(validated)));db.commit();return {'added':len(validated)}
