"""章节归一词典切版：HTTP 全链路测试（FastAPI TestClient + FakeRedis + SQLite）。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from conftest_helpers import *  # noqa
from fastapi.testclient import TestClient
from src.main import app
from src.models.user import User
from src.utils.security import hash_password
from src.services.backfill import run_backfill

client=TestClient(app)
with Session() as db:
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    for role in ('admin','analyst','viewer'):
        db.add(User(email=role+'@reading-transition.demo',password_hash=hash_password('pw'),role=role))
    db.commit()

def token(role):
    r=client.post('/auth/login',json={'email':role+'@reading-transition.demo','password':'pw'})
    assert r.status_code==200,r.text
    return r.json()['token']
ADMIN=token('admin');ANALYST=token('analyst');VIEWER=token('viewer')
H={'admin':{'Authorization':'Bearer '+ADMIN},'analyst':{'Authorization':'Bearer '+ANALYST},'viewer':{'Authorization':'Bearer '+VIEWER}}
PASS=0;FAIL=0
def check(name,cond,detail=''):
    global PASS,FAIL
    if cond:PASS+=1;print('  PASS',name)
    else:FAIL+=1;print('  FAIL',name,'-',detail)

print('[H1] 认证与权限')
r=client.get('/sources')
check('匿名访问 401',r.status_code==401)
r=client.post('/sources',headers=H['viewer'],json={'name':'无权文集','filename':'x.csv','description':''})
check('viewer 写入 403',r.status_code==403)

print('[H2] 文集与词典版本基线')
r=client.post('/sources',headers=H['analyst'],json={'name':'HTTP文集','filename':'http.csv','description':'d'})
check('创建文集 200',r.status_code==200,r.text);sid=r.json()['id']
r=client.get(f'/sources/{sid}/dictionary/versions',headers=H['admin'])
check('自动获得 v1 空词典基线',r.status_code==200 and r.json()[0]['version']==1 and r.json()[0]['state']=='published')

print('[H3] 追加样本与词典校验')
for i in range(40):
    r=client.post(f'/sources/{sid}/records',headers=H['analyst'],
                  json={'records':[{'reference':f'r{i}','values':{'session':f'S{i}','path':'序章>材料>案例'}}]})
    if i==0:check('追加样本 200',r.status_code==200,r.text)
r=client.post(f'/sources/{sid}/records',headers=H['analyst'],
              json={'records':[{'reference':'bad','values':{'session':'B','path':''}}]})
check('非法路径 422',r.status_code==422)

r=client.post(f'/sources/{sid}/dictionary/preview',headers=H['analyst'],
              json={'aliases':[{'old':'甲','new':'乙'},{'old':'乙','new':'丙'},{'old':'丙','new':'甲'}]})
check('循环别名预览 422',r.status_code==422 and '循环' in r.json()['detail'],r.text)
r=client.post(f'/sources/{sid}/dictionary/preview',headers=H['analyst'],
              json={'aliases':[{'old':'序章','new':'甲'},{'old':'序章','new':'乙'}]})
check('一名多义预览 422',r.status_code==422 and '一名多义' in r.json()['detail'])
r=client.post(f'/sources/{sid}/dictionary/preview',headers=H['analyst'],
              json={'aliases':[{'old':'序章','new':'开篇'}]})
check('合法链预览 200',r.status_code==200 and r.json()['mapping']=={'序章':'开篇'},r.text)

print('[H4] 切版、回填进度、发布原子切换')
r=client.post(f'/sources/{sid}/dictionary/versions',headers=H['analyst'],
              json={'aliases':[{'old':'序章','new':'开篇'}]})
check('切版 200 且 building',r.status_code==200 and r.json()['state']=='building',r.text);vid=r.json()['id'];jid=r.json()['backfill_job_id']
r=client.post(f'/sources/{sid}/dictionary/versions',headers=H['analyst'],json={'aliases':[{'old':'材料','new':'工艺'}]})
check('并发切版 409',r.status_code==409 and '未完成的切版' in r.json()['detail'])
r=client.get(f'/sources/{sid}/dictionary/jobs',headers=H['viewer'])
check('viewer 可查回填进度',r.status_code==200 and r.json()[0]['total_sessions']==40)
# 模拟 worker 消费
run_backfill(jid)
r=client.post(f'/dictionary/versions/{vid}/publish',headers=H['admin'])
check('回填完成后发布 200',r.status_code==200 and r.json()['state']=='published',r.text)
r=client.get(f'/sources/{sid}/records',headers=H['viewer'])
check('页面只见新版归一路径',all(x['canonical_path']=='开篇>材料>案例' for x in r.json()))
check('原始路径保留',all(x['values']['path']=='序章>材料>案例' for x in r.json()))
r=client.post(f'/dictionary/versions/{vid}/publish',headers=H['admin'])
check('重复发布 409',r.status_code==409)

print('[H5] 研究冻结词典、排队后切版不改结果')
r=client.post('/runs',headers=H['analyst'],json={'source_id':sid,'name':'HTTP研究','parameters':{'min_count':1,'top_n':20}})
check('研究受理 200',r.status_code==200,r.text);rid=r.json()['id']
r=client.post(f'/sources/{sid}/dictionary/versions',headers=H['analyst'],json={'aliases':[{'old':'案例','new':'终章'}]})
check('受理期切版 409 锁定',r.status_code==409 and '锁定' in r.json()['detail'])
r=client.post(f'/sources/{sid}/records',headers=H['analyst'],json={'records':[{'reference':'locked','values':{'session':'L','path':'序章>材料'}}]})
check('受理期输入 409 锁定',r.status_code==409)
from src.worker import execute
execute(rid)
r=client.get(f'/runs/{rid}',headers=H['viewer'])
check('研究完成且冻结 v2',r.json()['state']=='completed' and r.json()['dict_version_id']==vid)
frozen=r.json()['snapshot']
check('快照含冻结词典与归一路径',frozen['dict_version']['version']==2 and frozen['records'][0]['canonical_path']=='开篇>材料>案例')
checksum=r.json()['result']['checksum']
r=client.get(f'/runs/{rid}/export',headers=H['viewer'])
check('结果 CSV 可导出',r.status_code==200 and 'text/csv' in r.headers['content-type'])

print('[H6] 撤销合并恢复原文')
r=client.post(f'/sources/{sid}/dictionary/revert',headers=H['admin'])
check('撤销合并 200 回到 v1',r.status_code==200 and r.json()['version']==1 and r.json()['state']=='published',r.text)
r=client.get(f'/sources/{sid}/records',headers=H['viewer'])
check('页面恢复完整旧版原文',all(x['canonical_path']=='序章>材料>案例' for x in r.json()))
r=client.get(f'/runs/{rid}',headers=H['viewer'])
check('旧研究判定不受撤销影响',r.json()['result']['checksum']==checksum)

print('[H7] 失败原因与重试')
r=client.post(f'/sources/{sid}/dictionary/versions',headers=H['analyst'],json={'aliases':[{'old':'材料','new':'工艺'}]})
vid2=r.json()['id'];jid2=r.json()['backfill_job_id']
import src.services.backfill as bf
orig=bf.fold_path
bf.fold_path=lambda p,m:(_ for _ in ()).throw(RuntimeError('模拟回填失败'))
run_backfill(jid2);bf.fold_path=orig
r=client.get(f'/sources/{sid}/dictionary/versions',headers=H['viewer'])
b=next(x for x in r.json() if x['id']==vid2)
check('失败状态与原因可查',b['backfill']['state']=='failed' and '模拟回填失败' in b['backfill']['error'])
r=client.post(f'/dictionary/jobs/{jid2}/retry',headers=H['analyst'])
check('失败任务可重试 200',r.status_code==200 and r.json()['state']=='queued',r.text)
run_backfill(jid2)
r=client.post(f'/dictionary/versions/{vid2}/publish',headers=H['admin'])
check('重试补齐后发布 200',r.status_code==200,r.text)

print('[H8] 审计留痕覆盖切版全流程')
r=client.get('/audit',headers=H['admin'])
actions={x['action'] for x in r.json()}
need={'dict.version_created','dict.version_published','dict.backfill_started','dict.backfill_completed','dict.backfill_failed','dict.backfill_retry','run.queued','run.completed'}
check('审计事件齐全',need<=actions,str(sorted(need-actions)))

print(f'\nHTTP 结果：{PASS} 通过 / {FAIL} 失败')
sys.exit(1 if FAIL else 0)
