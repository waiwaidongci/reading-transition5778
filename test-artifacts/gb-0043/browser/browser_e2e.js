// 真实浏览器验收：登录→章节归一页面→别名校验拒绝/通过→切版→回填进度→发布原子切换→原始/归一路径对照→撤销恢复
const {chromium}=require('/tmp/pw/node_modules/playwright');
const BASE='http://127.0.0.1:8022';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let pass=0,fail=0;
function check(name,cond,detail=''){if(cond){pass++;console.log('  PASS',name)}else{fail++;console.log('  FAIL',name,'-',detail)}}
(async()=>{
  const browser=await chromium.launch({env:{...process.env,LD_LIBRARY_PATH:'/tmp/chromelibs/root/usr/lib/aarch64-linux-gnu:/tmp/chromelibs/root/lib/aarch64-linux-gnu'}});
  const page=await browser.newPage({viewport:{width:1366,height:900}});
  page.on('console',m=>{if(m.type()==='error')console.log('  [console.error]',m.text())});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));

  console.log('[B1] 登录');
  await page.goto(BASE+'/#login');
  await page.waitForSelector('#login-form input',{timeout:10000});
  const inputs=await page.locator('#login-form input').all();
  await inputs[0].fill('analyst@reading-transition.demo');await inputs[1].fill('Research2026!');
  await page.locator('#login-form button').click();
  await page.waitForURL(/overview/,{timeout:10000});
  check('登录进入总览',page.url().includes('overview'));

  console.log('[B2] 章节归一导航与版本账册');
  await page.goto(BASE+'/#dictionary');await sleep(600);
  check('导航出现「章节归一」',await page.locator('nav a',{hasText:'章节归一'}).count()>0);
  check('页面有词典版本账册',await page.getByText('词典版本账册').count()>0);
  check('自动存在 v1 基线',await page.getByText(/v1/).count()>0);
  // 选第一个文集（默认选中第一个，先切到它）
  await page.locator('#dict-source-select').selectOption({index:0});await sleep(400);

  console.log('[B3] 别名链校验：先通过、再一名多义拒绝');
  await page.locator('.alias-row').first().locator('input').nth(0).fill('序章');
  await page.locator('.alias-row').first().locator('input').nth(1).fill('开篇');
  await page.locator('#add-alias-row').click();await sleep(100);
  const rows=page.locator('.alias-row');
  await rows.nth(1).locator('input').nth(0).fill('楔子');
  await rows.nth(1).locator('input').nth(1).fill('序章');
  await page.locator('#alias-validate').click();await sleep(500);
  check('合法链校验通过',await page.locator('.alias-preview.ok').count()>0,(await page.locator('.alias-preview').textContent().catch(()=>'')));
  // 制造一名多义：再加一行 序章→别的
  await page.locator('#add-alias-row').click();await sleep(100);
  const r2=page.locator('.alias-row');
  await r2.nth(2).locator('input').nth(0).fill('序章');
  await r2.nth(2).locator('input').nth(1).fill('其他章');
  await page.locator('#alias-validate').click();await sleep(500);
  check('一名多义被页面拒绝提示',await page.locator('.alias-preview.error').count()>0);
  check('错误文案含一名多义',(await page.locator('.alias-preview.error').textContent()).includes('一名多义'));
  // 删除冲突行，恢复合法
  await r2.nth(2).locator('[data-remove]').click();

  console.log('[B4] 提交切版并观察回填进度');
  await page.locator('#alias-form button[type=submit]').click();
  await page.waitForSelector('.dict-version .progress',{timeout:8000});
  check('出现回填进度条',await page.locator('.dict-version .progress').count()>0);
  // worker 同进程消费，等待完成
  await page.waitForFunction(()=>![...document.querySelectorAll('.dict-version small')].some(s=>s.textContent.includes('回填进行中')||s.textContent.includes('排队中')),{timeout:20000}).catch(()=>{});
  await sleep(800);
  check('回填完成可发布按钮出现',await page.locator('[data-publish]').count()>0);

  console.log('[B5] 发布前页面仍是旧版，发布后原子切换为新版');
  const beforeRows=await page.locator('tbody tr td:nth-child(2)').allInnerTexts();
  check('发布前样本表保留原始路径',beforeRows.some(t=>t.includes('序章')));
  const beforeCanon=await page.locator('tbody tr td:nth-child(3)').allInnerTexts();
  check('发布前归一列仍是完整旧版原文',beforeCanon.some(t=>t.includes('序章'))&&!beforeCanon.some(t=>t.includes('开篇')));
  await page.locator('[data-publish]').first().click();
  await page.waitForSelector('.status.completed:has-text("页面当前版本")',{timeout:8000});
  await sleep(500);
  const afterCanon=await page.locator('tbody tr td:nth-child(3)').allInnerTexts();
  check('发布后归一列只见新版（开篇）',afterCanon.every(t=>!t.includes('序章'))&&afterCanon.some(t=>t.includes('开篇')),afterCanon.join('|'));
  const afterRaw=await page.locator('tbody tr td:nth-child(2)').allInnerTexts();
  check('发布后原始路径仍保留',afterRaw.some(t=>t.includes('序章')));

  console.log('[B6] 版本账册状态与进度可查');
  check('当前发布版标记可见',await page.getByText('页面当前版本').count()>0);
  check('历史版本 superseded 可见',await page.locator('.dict-version.superseded').count()>0);

  console.log('[B7] 撤销合并恢复原文');
  await page.locator('[data-revert]').first().click();
  await page.waitForFunction(()=>![...document.querySelectorAll('tbody tr td:nth-child(3)')].some(td=>td.textContent.includes('开篇')),{timeout:8000});
  const reverted=await page.locator('tbody tr td:nth-child(3)').allInnerTexts();
  check('撤销后归一列恢复原文',reverted.every(t=>!t.includes('开篇'))&&reverted.some(t=>t.includes('序章')),reverted.join('|'));

  console.log('[B8] 研究页面显示冻结词典版本');
  await page.goto(BASE+'/#config');await sleep(500);
  await page.locator('#run-form button[type=submit]').click();
  await page.waitForURL(/results/,{timeout:8000});
  await page.waitForSelector('.run-title',{timeout:8000});
  const title=await page.locator('.run-title').innerText();
  check('结果页标注归一词典版本',title.includes('归一词典 v1'),title);

  console.log('[B9] 审计页可见切版事件');
  await page.goto(BASE+'/#audit');await sleep(500);
  const auditText=await page.locator('body').innerText();
  check('审计含切版与回填事件',auditText.includes('dict.version_created')&&auditText.includes('dict.version_published'));

  check('无未捕获页面错误',errors.length===0,errors.join(' ;; '));
  await page.screenshot({path:__dirname+'/dictionary-page.png',fullPage:true});
  await browser.close();
  console.log(`\n浏览器结果：${pass} 通过 / ${fail} 失败`);
  process.exit(fail?1:0);
})().catch(e=>{console.error(e);process.exit(1)});
