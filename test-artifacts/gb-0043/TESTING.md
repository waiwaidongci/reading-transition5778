# 章节归一词典切版 · 测试说明

本目录测试与源码隔离，不依赖外部 MySQL / Redis：后端用 SQLite + 进程内 FakeRedis，浏览器用 Playwright Chromium。

## 运行方式

```bash
# 依赖（仅测试环境）
python3 -m pip install --user --break-system-packages fastapi==0.115.6 \
  "sqlalchemy==2.0.36" "redis==5.2.1" PyJWT==2.10.1 httpx uvicorn==0.34.0

# 1) 服务级断言：别名链/拒绝/折叠重算/回填断点/锁/版本/旧判定（59项）
python3 test-artifacts/gb-0043/test_dictionary.py

# 2) HTTP 全链路：真实 FastAPI 路由、JWT 角色、422/409 状态码（29项）
python3 test-artifacts/gb-0043/test_http_flow.py

# 3) 真实浏览器（可选，需 node 与 playwright chromium）
python3 test-artifacts/gb-0043/browser/launch_backend.py &      # 测试后端 8011
node test-artifacts/gb-0043/browser/static_server.js &          # 静态前端 8022
cd <playwright目录> && node test-artifacts/gb-0043/browser/browser_e2e.js
```

## 验收矩阵（对应需求逐条）

| 需求 | 覆盖位置 |
|---|---|
| 别名链归到终点 | test_dictionary [1]；test_http_flow [H3]；browser [B3] |
| 循环与一名多义拒绝 | test_dictionary [1]；test_http_flow [H3]；browser [B3] |
| 原始路径保留 | test_dictionary [2][7]；test_http_flow [H4]；browser [B5] |
| 连续同章折叠后重算接续及全部分母 | test_dictionary [2] |
| 撤销合并恢复原文 | test_dictionary [8]；test_http_flow [H6]；browser [B7] |
| 回填中断可恢复、重试不新增接续 | test_dictionary [3] |
| 并发切版只发布一版 | test_dictionary [4]；test_http_flow [H4] |
| 受理锁定词典与输入、排队后切版不改结果 | test_dictionary [5]；test_http_flow [H5] |
| 回填期间接收新会话、切换前会话纳入 | test_dictionary [6] |
| 页面只见完整旧版或新版 | test_dictionary [7]；browser [B5] |
| 版本、进度、失败原因可查 | test_dictionary [9]；test_http_flow [H7]；browser [B6] |
| 旧研究及批准建议保留原判定 | test_dictionary [10]；test_http_flow [H6] |
| 十万级回填分批与进度 | test_dictionary [11]（万级实测并外推） |
| worker 双队列路由 | test_dictionary [12] |
| 审计留痕 | test_http_flow [H8]；browser [B9] |

## 最近一次结果

- `test_dictionary.py`：59 通过 / 0 失败
- `test_http_flow.py`：29 通过 / 0 失败
- `browser/browser_e2e.js`：19 通过 / 0 失败（截图 `browser/dictionary-version-page.png`、`browser/dictionary-page.png`）
