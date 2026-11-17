import hashlib,json
from fastapi import HTTPException
from sqlalchemy import select,func
from ..models.source import Source
from ..models.record import Record
from ..models.dictionary import DictVersion
from ..models.backfill import BackfillJob
from ..models.normalized import NormalizedSession
from ..models.run import Run
from ..utils.serialization import row,now
from .audit import log

MAX_ALIAS_PAIRS=2000
MAX_NAME_LEN=120

def parse_aliases(raw):
    """归一化输入为有序 [(旧名,新名)]，拒绝一名多义与自指。"""
    if isinstance(raw,dict):
        pairs=[(str(k),str(v)) for k,v in raw.items()]
    elif isinstance(raw,list):
        pairs=[]
        for item in raw:
            if not isinstance(item,(list,tuple)) or len(item)!=2:
                raise HTTPException(422,'别名条目必须为[旧名,新名]成对出现')
            pairs.append((str(item[0]),str(item[1])))
    else:
        raise HTTPException(422,'别名需为旧名→新名的成对列表')
    if len(pairs)>MAX_ALIAS_PAIRS:
        raise HTTPException(422,f'别名最多{MAX_ALIAS_PAIRS}条')
    cleaned=[];seen={}
    for old,new in pairs:
        old=old.strip();new=new.strip()
        if not old or not new:
            raise HTTPException(422,'别名旧名与新名均不能为空')
        if len(old)>MAX_NAME_LEN or len(new)>MAX_NAME_LEN:
            raise HTTPException(422,f'章节名最多{MAX_NAME_LEN}字符')
        if old==new:
            raise HTTPException(422,'旧名与新名相同，无需别名：'+old)
        if old in seen and seen[old]!=new:
            raise HTTPException(422,'一名多义被拒绝：章节「'+old+'」同时指向「'+seen[old]+'」与「'+new+'」')
        seen[old]=new;cleaned.append((old,new))
    return cleaned

def resolve_aliases(pairs):
    """别名链归到终点；检测循环。返回 mapping（旧名→终点名）与 chains（旧名→完整链）。"""
    direct=dict(pairs)
    mapping={};chains={}
    def terminal_of(start):
        if start in mapping:
            return mapping[start]
        chain=[];cur=start;seen=set()
        while cur in direct:
            if cur in seen:
                cycle=chain[chain.index(cur):]+[cur]
                raise HTTPException(422,'别名存在循环引用，已拒绝：'+'→'.join(cycle))
            seen.add(cur);chain.append(cur);cur=direct[cur]
        terminal=cur
        for i,node in enumerate(chain):
            mapping[node]=terminal
            chains[node]=chain[i:]+[terminal]
        return terminal
    for old in direct:
        terminal_of(old)
    return mapping,chains

def validate_aliases(raw):
    pairs=parse_aliases(raw)
    mapping,chains=resolve_aliases(pairs)
    signature=hashlib.sha256(json.dumps(pairs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return pairs,mapping,chains,signature

def fold_path(parts,mapping):
    """按归一映射改写章节名，并折叠连续同章；原始路径由调用处保留。"""
    canonical=[mapping.get(x,x) for x in parts]
    folded=[]
    for x in canonical:
        if not folded or folded[-1]!=x:
            folded.append(x)
    return folded

def split_path(path):
    return [s.strip() for s in path.split('>')]

def join_path(parts):
    return '>'.join(parts)

def active_lock_error(db,source_id):
    """研究受理（队列中/计算中）时锁定词典与输入；回填不锁定输入，十万会话回填时仍可接收新会话。"""
    run=db.scalar(select(Run.id).where(Run.source_id==source_id,Run.state.in_(('queued','running'))).limit(1))
    if run:
        return '存在受理中的研究（队列中或计算中），词典与输入已锁定；请等该研究完成后再切版'
    return ''

def building_version_error(db,source_id):
    """串行化切版：同一来源同时只允许一个未完成（building）版本，保证并发切版只发布一版。"""
    v=db.scalar(select(DictVersion).where(DictVersion.source_id==source_id,DictVersion.state=='building').limit(1))
    if v:
        return f'存在未完成的切版 v{v.version}（回填中），请等其回填完成并发布，或处理失败后再切版'
    return ''

def ensure_baseline(db,source,actor='system'):
    """每个来源自动获得 v1 空词典基线（即完整旧版）。"""
    existing=db.scalar(select(DictVersion).where(DictVersion.source_id==source.id,DictVersion.version==1))
    if existing:
        return existing
    ts=now()
    v=DictVersion(source_id=source.id,version=1,state='published',aliases=[],alias_chains={},
                  signature=hashlib.sha256(b'').hexdigest(),created_by=actor,created_at=ts,published_at=ts)
    db.add(v);db.flush()
    source.active_version_id=v.id
    return v

def get_version_or_404(db,version_id):
    v=db.get(DictVersion,version_id)
    if not v:
        raise HTTPException(404,'未找到词典版本')
    return v

def list_versions(db,source_id):
    versions=[row(v) for v in db.scalars(select(DictVersion).where(DictVersion.source_id==source_id).order_by(DictVersion.version.desc()))]
    for v in versions:
        job=db.scalar(select(BackfillJob).where(BackfillJob.dict_version_id==v['id']).order_by(BackfillJob.id.desc()))
        v['backfill']=row(job) if job else None
    return versions

def list_jobs(db,source_id):
    return [row(j) for j in db.scalars(select(BackfillJob).where(BackfillJob.source_id==source_id).order_by(BackfillJob.id.desc()))]

def mapping_of(version):
    return {old:chain[-1] for old,chain in (version.alias_chains or {}).items()}

def canonical_paths_for(db,version,records):
    """返回 record_id -> 归一折叠后路径；优先读回填产物，缺失时即时按映射计算。"""
    ids=[r.id for r in records]
    existing={}
    if ids:
        existing={n.record_id:n.canonical_path for n in db.scalars(
            select(NormalizedSession).where(NormalizedSession.dict_version_id==version.id,
                                            NormalizedSession.record_id.in_(ids)))}
    mapping=mapping_of(version);out={}
    for r in records:
        if r.id in existing:
            out[r.id]=existing[r.id]
        else:
            out[r.id]=join_path(fold_path(split_path(r.values['path']),mapping))
    return out

def create_version(db,user,source_id,raw_aliases):
    source=db.get(Source,source_id)
    if not source:
        raise HTTPException(404,'未找到来源批次')
    ensure_baseline(db,source)
    lock=active_lock_error(db,source_id)
    if lock:
        raise HTTPException(409,lock)
    building=building_version_error(db,source_id)
    if building:
        raise HTTPException(409,building)
    pairs,mapping,chains,signature=validate_aliases(raw_aliases)
    if not pairs:
        raise HTTPException(409,'空词典无需切版；如需撤销合并恢复原文，请使用「撤销合并」重新发布 v1 空词典')
    dup=db.scalar(select(DictVersion.id).where(DictVersion.source_id==source_id,DictVersion.signature==signature).limit(1))
    if dup:
        raise HTTPException(409,'该别名词典与已有版本完全相同，无需重复切版')
    next_version=(db.scalar(select(func.max(DictVersion.version)).where(DictVersion.source_id==source_id)) or 0)+1
    ts=now()
    v=DictVersion(source_id=source_id,version=next_version,state='building',aliases=pairs,alias_chains=chains,
                  signature=signature,created_by=user.email,created_at=ts)
    db.add(v);db.flush()
    total=db.scalar(select(func.count()).select_from(Record).where(Record.source_id==source_id)) or 0
    job=BackfillJob(source_id=source_id,dict_version_id=v.id,state='queued',total_sessions=total,
                    processed_sessions=0,last_record_id=0,attempts=0,created_at=ts,updated_at=ts)
    db.add(job);db.flush()
    log(db,user,'dict.version_created',v.id,f'v{next_version} 别名{len(pairs)}条 回填任务#{job.id}')
    db.commit()
    return row(v),job.id

def publish_version(db,user,version_id):
    v=get_version_or_404(db,version_id)
    source=db.get(Source,v.source_id)
    lock=active_lock_error(db,v.source_id)
    if lock:
        raise HTTPException(409,lock)
    if v.state=='published':
        raise HTTPException(409,'该版本已经发布')
    if v.state not in ('building','superseded'):
        raise HTTPException(409,f'版本状态为{v.state}，不能发布')
    if v.state=='building':
        job=db.scalar(select(BackfillJob).where(BackfillJob.dict_version_id==v.id).order_by(BackfillJob.id.desc()))
        if not job:
            # 无回填任务的只能是空词典基线，恒为完整可用版本
            if v.aliases:
                raise HTTPException(409,'该版本缺少回填记录，不能发布')
        elif job.state!='completed':
            raise HTTPException(409,'回填尚未完成，不能发布；页面可见版本与进度')
        # 回填期间仍接收新会话：发布前核对当前全部会话均已纳入本版本（含切换前接收的会话）
        total_now=db.scalar(select(func.count()).select_from(Record).where(Record.source_id==v.source_id)) or 0
        normalized_now=db.scalar(select(func.count()).select_from(NormalizedSession).where(NormalizedSession.dict_version_id==v.id)) or 0
        if normalized_now<total_now:
            raise HTTPException(409,f'回填后又有 {total_now-normalized_now} 条新会话尚未纳入，请先在页面重试回填补齐再发布')
    ts=now()
    if source.active_version_id:
        old=db.get(DictVersion,source.active_version_id)
        if old and old.state=='published':
            old.state='superseded'
    v.state='published';v.published_at=ts
    source.active_version_id=v.id
    log(db,user,'dict.version_published',v.id,f'v{v.version} 原子切换，旧版保留可回退')
    db.commit()
    return row(v)

def revert_version(db,user,source_id):
    """撤销合并：重新发布空词典版本（归一回原文）；全部历史版本保留，不新建重复词典。"""
    source=db.get(Source,source_id)
    if not source:
        raise HTTPException(404,'未找到来源批次')
    baseline=ensure_baseline(db,source)
    lock=active_lock_error(db,source_id)
    if lock:
        raise HTTPException(409,lock)
    empty_signature=hashlib.sha256(b'').hexdigest()
    candidates=db.scalars(select(DictVersion).where(
        DictVersion.source_id==source_id,DictVersion.signature==empty_signature).order_by(DictVersion.version))
    target=next((v for v in candidates if not v.aliases),baseline)
    return publish_version(db,user,target.id)

def retry_job(db,user,job_id):
    job=db.get(BackfillJob,job_id)
    if not job:
        raise HTTPException(404,'未找到回填任务')
    if job.state not in ('failed','completed'):
        raise HTTPException(409,'仅失败或需要补齐新会话的回填任务可以重试')
    lock=active_lock_error(db,job.source_id)
    if lock:
        raise HTTPException(409,lock)
    job.state='queued';job.error='';job.updated_at=now()
    log(db,user,'dict.backfill_retry',job.id,f'从水位 {job.processed_sessions}/{job.total_sessions} 断点续跑')
    db.commit()
    return row(job)
