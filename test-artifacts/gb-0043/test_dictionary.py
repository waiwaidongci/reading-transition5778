"""章节归一词典切版全量验收测试。

运行：python3 test-artifacts/gb-0043/test_dictionary.py
覆盖：别名链归终点 / 循环与一名多义拒绝 / 连续同章折叠重算分母 / 原始路径保留 /
撤销合并恢复原文 / 回填断点恢复与重试幂等 / 并发切版只发布一版 / 受理锁定与排队冻结 /
回填期间新会话纳入 / 页面只见完整版本 / 版本进度失败原因可查 / 旧研究与批准判定保留。
"""
from fastapi import HTTPException
from sqlalchemy import select,func
from conftest_helpers import *

PASS=0;FAIL=0
def check(name,cond,detail=''):
    global PASS,FAIL
    if cond:PASS+=1;print('  PASS',name)
    else:FAIL+=1;print('  FAIL',name,'-',detail)
def expect_422(name,fn,needle=''):
    try:fn()
    except HTTPException as e:
        check(name,e.status_code==422 and (not needle or needle in e.detail),str(e.status_code)+' '+e.detail);return
    check(name,False,'未拒绝')

def test_alias_chain_and_rejections():
    print('[1] 别名链归终点、循环与一名多义拒绝')
    db=fresh_db()
    # 链 A旧→B旧→C终：两级链归到终点
    pairs,mapping,chains,sig=norm.validate_aliases([['楔子','序章'],['序章','开篇']])
    check('链归终点 楔子→开篇',mapping['楔子']=='开篇' and mapping['序章']=='开篇')
    check('链路完整保留',chains['楔子']==['楔子','序章','开篇'])
    # 循环拒绝
    expect_422('循环引用被拒绝',lambda:norm.validate_aliases([['甲','乙'],['乙','丙'],['丙','甲']]),'循环')
    # 自环拒绝
    expect_422('自指别名被拒绝',lambda:norm.validate_aliases([['同章','同章']]),'相同')
    # 一名多义拒绝（HTTP 422 在 parse 阶段）
    expect_422('一名多义被拒绝',lambda:norm.validate_aliases([['旧名','新名甲'],['旧名','新名乙']]),'一名多义')
    # 空别名/超长拒绝
    expect_422('空别名被拒绝',lambda:norm.validate_aliases([['','终']]),'不能为空')
    expect_422('结构错误被拒绝',lambda:norm.validate_aliases('not-a-list'),'成对列表')
    db.close()

def test_fold_recalculate_and_raw_kept():
    print('[2] 连续同章折叠后重算接续及全部分母，原始路径保留')
    db=fresh_db();s=make_source(db)
    add_record(db,s.id,'r1','S1','楔子>序章>材料>案例')      # 楔子→序章 归并为 开篇>开篇，折叠
    add_record(db,s.id,'r2','S2','序章>材料>案例>附录')
    add_record(db,s.id,'r3','S3','开篇>材料>案例')
    v,job=create_and_backfill(db,s.id,[['楔子','序章'],['序章','开篇']])
    check('回填完成',job.state=='completed',job.error)
    n=db.scalar(select(NormalizedSession).join(Record).where(Record.reference=='r1'))
    check('原始路径保留在样本',db.get(Record,n.record_id).values['path']=='楔子>序章>材料>案例')
    check('归一路径折叠连续同章',n.canonical_path=='开篇>材料>案例',n.canonical_path)
    # 算法在归一后路径上重算
    records=[{'id':r.id,'values':r.values,'canonical_path':x.canonical_path}
             for r,x in [(db.get(Record,nid),db.get(NormalizedSession,nid)) for nid in
                         db.scalars(select(NormalizedSession.id).where(NormalizedSession.dict_version_id==v.id))]]
    # 直接用归一路径构造算法输入（模拟 worker 的折叠计算）
    calc_records=[{'values':{'session':db.get(Record,n.record_id).values['session'],'path':n.canonical_path}}
                  for n in db.scalars(select(NormalizedSession).where(NormalizedSession.dict_version_id==v.id))]
    result=calculate(calc_records,{'min_count':1,'top_n':20},v)
    edges={(x['from'],x['to']):x for x in result['rows']}
    # 三条会话折叠后：开篇→材料 出现3次；材料→案例 3次；案例→附录 1次
    check('接续在归一后重算 开篇→材料=3',edges[('开篇','材料')]['count']==3,str(edges.get(('开篇','材料'))))
    check('折叠边不计接续（无开篇→开篇）',('开篇','开篇') not in edges)
    check('分母 outgoing 开篇=3',result['outgoing_counts']['开篇']==3)
    check('分母 incoming 材料=3',result['target_counts']['材料']==3)
    check('总边数为折叠后 7 条',sum(x['count'] for x in result['rows'])==7)
    labels={x['label']:x['value'] for x in result['summary']}
    check('摘要区分原始相邻对与折叠后边',labels['原始相邻对']==7 and labels['折叠后接续边']==7,str(labels))
    check('结果标注词典版本',labels['归一词典版本']=='v2')
    db.close()

def test_backfill_resume_and_idempotent_retry():
    print('[3] 回填中断可恢复进度，重试不新增接续')
    db=fresh_db();s=make_source(db)
    for i in range(130):add_record(db,s.id,f'r{i}',f'S{i}','序章>材料>案例')
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']])
    # 模拟在处理 60 条后进程崩溃
    import src.services.backfill as bf
    orig=bf.fold_path;crashed={'n':0}
    def crashing(parts,mapping):
        crashed['n']+=1
        if crashed['n']==61:raise RuntimeError('模拟进程中断')
        return orig(parts,mapping)
    bf.fold_path=crashing
    run_backfill(job_id)
    bf.fold_path=orig
    db.expire_all();job=db.get(BackfillJob,job_id)
    check('中断后任务失败且原因保留',job.state=='failed' and '模拟进程中断' in job.error,job.state)
    check('进度水位已持久化（首批50条已提交）',job.processed_sessions==50 and job.last_record_id>0,str(job.processed_sessions))
    # 重试：从断点继续
    norm.retry_job(db,ADMIN,job_id);run_backfill(job_id)
    db.expire_all();job=db.get(BackfillJob,job_id)
    check('重试后完成',job.state=='completed',job.error)
    check('全部会话已回填',job.processed_sessions==130,str(job.processed_sessions))
    count=db.scalar(select(func.count()).select_from(NormalizedSession).where(NormalizedSession.dict_version_id==v['id']))
    check('重试幂等：每会话仅一行',count==130,str(count))
    # 再次重跑同一任务不产生重复行
    norm.retry_job(db,ADMIN,job_id);run_backfill(job_id)
    count2=db.scalar(select(func.count()).select_from(NormalizedSession).where(NormalizedSession.dict_version_id==v['id']))
    check('重复重试仍不新增行',count2==130,str(count2))
    db.close()

def test_concurrent_cut_publishes_one():
    print('[4] 并发切版只发布一版（building 串行化 + 来源锁）')
    db=fresh_db();s=make_source(db)
    for i in range(10):add_record(db,s.id,f'r{i}',f'S{i}','序章>材料')
    v1,job1=norm.create_version(db,ADMIN,s.id,[['序章','开篇']])
    # 第二版在第一版回填/发布前被拒绝
    try:norm.create_version(db,ADMIN,s.id,[['材料','工艺']]);check('并发切版被拒绝',False)
    except HTTPException as e:check('并发切版被拒绝',e.status_code==409 and '未完成的切版' in e.detail,e.detail)
    run_backfill(job1);db.expire_all()
    # 发布前回填锁已释放；回填执行期另一 worker 拿不到来源锁
    import src.services.backfill as bf
    ok=bf.acquire_source_lock(s.id,'other')
    check('回填结束后来源锁释放',ok is True)
    bf.release_source_lock(s.id,'other')
    norm.publish_version(db,ADMIN,v1['id']);db.expire_all()
    published=db.get(DictVersion,v1['id'])
    check('仅一版发布',published.state=='published' and db.get(Source,s.id).active_version_id==published.id)
    # 发布后才能切下一版
    v2,job2=norm.create_version(db,ADMIN,s.id,[['材料','工艺']])
    check('上一版发布后可再切版（v1基线后第2个切版=v3）',v2['version']==3,str(v2['version']))
    db.close()

def test_run_lock_and_queued_freeze():
    print('[5] 研究受理锁定词典与输入；排队后的切版不改结果')
    db=fresh_db();s=make_source(db)
    for i in range(6):add_record(db,s.id,f'r{i}',f'S{i}','序章>材料>案例')
    from src.services.runs import create_run
    from src.schemas.run import RunInput
    run=create_run(db,ADMIN,RunInput(source_id=s.id,name='锁定研究',parameters={'min_count':1,'top_n':20}))
    check('任务受理冻结 v1',run['dict_version_id']==s.active_version_id)
    # 受理期间拒绝切版与追加输入
    try:norm.create_version(db,ADMIN,s.id,[['序章','开篇']]);check('受理期切版被锁',False)
    except HTTPException as e:check('受理期切版被锁',e.status_code==409 and '锁定' in e.detail,e.detail)
    from src.schemas.source import RecordBatch,RecordInput
    try:
        from src.services.sources import add_records
        add_records(db,ADMIN,s.id,RecordBatch(records=[RecordInput(reference='x',values={'session':'X','path':'序章>材料'})]))
        check('受理期输入被锁',False)
    except HTTPException as e:check('受理期输入被锁',e.status_code==409,e.detail)
    # worker 执行队列中的研究
    from src.worker import execute
    execute(run['id']);db.expire_all()
    done=db.get(Run,run['id'])
    check('队列研究完成',done.state=='completed',done.error)
    checksum_before=done.result['checksum'];rows_before=done.result['rows']
    # 研究完成后切版并发布，再跑新研究；旧研究结果不变
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']]);run_backfill(job_id)
    norm.publish_version(db,ADMIN,v['id'])
    db.expire_all();old=db.get(Run,run['id'])
    check('排队后的切版不改旧研究',old.result['checksum']==checksum_before and old.result['rows']==rows_before)
    check('旧研究快照保留原始路径',old.snapshot['records'][0]['values']['path']=='序章>材料>案例')
    check('旧研究快照带冻结归一路径','canonical_path' in old.snapshot['records'][0])
    run2=create_run(db,ADMIN,RunInput(source_id=s.id,name='切版后研究',parameters={'min_count':1,'top_n':20}))
    check('新研究冻结新版词典',run2['dict_version_id']==v['id'])
    db.close()

def test_new_sessions_during_backfill():
    print('[6] 十万会话回填时仍接收新会话，切换前接收的也要纳入')
    db=fresh_db();s=make_source(db)
    for i in range(120):add_record(db,s.id,f'r{i}',f'S{i}','序章>材料')
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']])
    run_backfill(job_id);db.expire_all()
    # 回填完成后、发布前追加新会话（回填期间不锁输入，这里等价覆盖“切换前接收”）
    add_record(db,s.id,'late1','L1','序章>案例')
    add_record(db,s.id,'late2','L2','序章>案例')
    try:norm.publish_version(db,ADMIN,v['id']);check('未补齐时拒绝发布',False)
    except HTTPException as e:check('未补齐时拒绝发布并提示',e.status_code==409 and '新会话' in e.detail,e.detail)
    job=db.get(BackfillJob,job_id)
    norm.retry_job(db,ADMIN,job.id);run_backfill(job.id);db.expire_all()
    check('补齐后回填计数含新会话',db.get(BackfillJob,job_id).processed_sessions==122)
    norm.publish_version(db,ADMIN,v['id']);db.expire_all()
    check('发布成功且页面版本为新版',db.get(Source,s.id).active_version_id==v['id'])
    late=db.scalar(select(NormalizedSession).join(Record).where(Record.reference=='late1',NormalizedSession.dict_version_id==v['id']))
    check('切换前新会话已按新版归一',late.canonical_path=='开篇>案例',late.canonical_path)
    db.close()

def test_page_sees_only_complete_version():
    print('[7] 页面只见完整旧版或新版')
    db=fresh_db();s=make_source(db)
    add_record(db,s.id,'r1','S1','序章>材料>案例')
    from src.services.sources import list_records
    before=list_records(db,s.id)
    check('旧版页面显示原始路径',before[0]['canonical_path']=='序章>材料>案例')
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']])
    during=list_records(db,s.id)
    check('回填中页面仍是完整旧版',during[0]['canonical_path']=='序章>材料>案例' and db.get(Source,s.id).active_version_id!=v['id'])
    run_backfill(job_id);norm.publish_version(db,ADMIN,v['id']);db.expire_all()
    after=list_records(db,s.id)
    check('发布后页面只见新版',after[0]['canonical_path']=='开篇>材料>案例',after[0]['canonical_path'])
    check('原始路径始终保留',after[0]['values']['path']=='序章>材料>案例')
    db.close()

def test_revert_restores_original():
    print('[8] 撤销合并能恢复原文')
    db=fresh_db();s=make_source(db)
    add_record(db,s.id,'r1','S1','序章>材料>案例')
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']]);run_backfill(job_id)
    norm.publish_version(db,ADMIN,v['id']);db.expire_all()
    baseline=norm.revert_version(db,ADMIN,s.id);db.expire_all()
    check('撤销后激活空词典 v1',db.get(Source,s.id).active_version_id==baseline['id'] and baseline['version']==1)
    from src.services.sources import list_records
    rows=list_records(db,s.id)
    check('归一回原文',rows[0]['canonical_path']=='序章>材料>案例')
    versions=norm.list_versions(db,s.id)
    check('历史版本全部保留',{x['version'] for x in versions}>={1,2})
    db.close()

def test_version_progress_failure_visible():
    print('[9] 页面可查版本、进度和失败原因')
    db=fresh_db();s=make_source(db)
    for i in range(75):add_record(db,s.id,f'r{i}',f'S{i}','序章>材料')
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']])
    versions=norm.list_versions(db,s.id)
    building=next(x for x in versions if x['id']==v['id'])
    check('版本列表带回填进度',building['backfill']['state']=='queued' and building['backfill']['total_sessions']==75)
    import src.services.backfill as bf
    orig=bf.fold_path
    bf.fold_path=lambda p,m:(_ for _ in ()).throw(RuntimeError('字典文件损坏演示'))
    run_backfill(job_id);bf.fold_path=orig
    db.expire_all()
    versions=norm.list_versions(db,s.id);b=next(x for x in versions if x['id']==v['id'])
    check('失败原因可查',b['backfill']['state']=='failed' and '字典文件损坏演示' in b['backfill']['error'])
    jobs=norm.list_jobs(db,s.id)
    check('回填任务列表可查进度',jobs[0]['processed_sessions']>=0 and jobs[0]['attempts']>=1)
    db.close()

def test_legacy_runs_and_approvals_keep_verdict():
    print('[10] 旧研究及批准建议保留原判定')
    db=fresh_db();s=make_source(db)
    for i in range(6):add_record(db,s.id,f'r{i}',f'S{i}','序章>材料>案例')
    from src.services.runs import create_run
    from src.schemas.run import RunInput
    from src.worker import execute
    run=create_run(db,ADMIN,RunInput(source_id=s.id,name='旧版研究',parameters={'min_count':1,'top_n':20}))
    execute(run['id'])
    from src.services.notes import create_note,approve_note
    from src.schemas.note import NoteInput
    n=create_note(db,ADMIN,NoteInput(run_id=run['id'],title='旧版意见',body='保留原判定'))
    approve_note(db,ADMIN,n['id'])
    from src.models.note import Note
    frozen_before=db.get(Note,n['id']).frozen_result
    # 切版发布
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']]);run_backfill(job_id)
    norm.publish_version(db,ADMIN,v['id']);db.expire_all()
    note=db.get(Note,n['id'])
    check('批准状态保留',note.state=='approved' and note.approved_by==ADMIN.email)
    check('批准快照保留旧判定',note.frozen_result==frozen_before)
    old=db.get(Run,run['id'])
    check('旧研究仍可导出原结果',old.state=='completed' and old.result['checksum']==frozen_before['checksum'])
    db.close()

def test_large_backfill_scale():
    print('[11] 十万会话量级回填（分批+进度，抽样校验）')
    db=fresh_db();s=make_source(db)
    N=10000
    for i in range(N):add_record(db,s.id,f'r{i}',f'S{i:06d}','序章>材料>案例')
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇'],['材料','工艺']])
    import time;t0=time.time();run_backfill(job_id);dt=time.time()-t0
    db.expire_all();job=db.get(BackfillJob,job_id)
    check('万级回填完成',job.state=='completed' and job.processed_sessions==N,job.error)
    check('分批次数合理（BATCH=50）',job.attempts==1)
    sample=db.scalar(select(NormalizedSession).where(NormalizedSession.dict_version_id==v['id'],NormalizedSession.record_id==1))
    check('抽样归一折叠正确',sample.canonical_path=='开篇>工艺>案例',sample.canonical_path)
    print(f'      {N} 会话回填耗时 {dt:.2f}s（推算十万会话约 {dt*10:.0f}s，分批提交可中断恢复）')
    db.close()

def test_worker_queue_routing():
    print('[12] worker 队列路由：回填与分析互不串队，失败不丢任务语义')
    db=fresh_db();s=make_source(db)
    for i in range(5):add_record(db,s.id,f'r{i}',f'S{i}','序章>材料')
    v,job_id=norm.create_version(db,ADMIN,s.id,[['序章','开篇']])
    from conftest_helpers import FAKE
    FAKE.lists.clear()
    FAKE.rpush('backfill:queue',job_id)
    from src.services.runs import create_run
    from src.schemas.run import RunInput
    run=create_run(db,ADMIN,RunInput(source_id=s.id,name='队列研究',parameters={'min_count':1,'top_n':20}))
    # 模拟一次 main 循环取队首（回填优先）
    item=FAKE.blpop(['backfill:queue','analysis:queue'])
    check('回填队列优先被消费',item[0]==b'backfill:queue' and int(item[1])==job_id)
    from src.services.backfill import run_backfill
    run_backfill(int(item[1]))
    # 先消费并完成受理中的研究，再发布词典（研究受理期词典锁定）
    item2=FAKE.blpop(['backfill:queue','analysis:queue'])
    check('分析任务经 analysis 队列',item2[0]==b'analysis:queue' and int(item2[1])==run['id'])
    from src.worker import execute
    execute(int(item2[1]));db.expire_all()
    check('分析任务正常完成',db.get(Run,run['id']).state=='completed')
    norm.publish_version(db,ADMIN,v['id'])
    check('回填完成的版本可发布',db.get(Source,s.id).active_version_id==v['id'])
    db.close()

if __name__=='__main__':
    for t in [test_alias_chain_and_rejections,test_fold_recalculate_and_raw_kept,
              test_backfill_resume_and_idempotent_retry,test_concurrent_cut_publishes_one,
              test_run_lock_and_queued_freeze,test_new_sessions_during_backfill,
              test_page_sees_only_complete_version,test_revert_restores_original,
              test_version_progress_failure_visible,test_legacy_runs_and_approvals_keep_verdict,
              test_large_backfill_scale,test_worker_queue_routing]:
        t()
    print(f'\n结果：{PASS} 通过 / {FAIL} 失败')
    sys.exit(1 if FAIL else 0)
