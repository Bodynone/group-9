# 阅见 · 教师批改工作台

Next.js 16 / React 19 中文前端，连接真实后端完成单份作业的六维评分和教师复核。

当前量表为 `2026-v1`，A-F 满分为 15、25、25、15、10、10。本次增加批量后端与部署，批量上传和学情页面由其他成员实现。

## 本地启动

先按仓库根 README 启动 FastAPI 后端，再执行：

```bash
pnpm install
pnpm dev
```

打开 <http://localhost:3000>。同源 `/api/*` 默认转发至 `http://127.0.0.1:8000/api/*`。需要其他地址时，在启动前设置 `BACKEND_URL`，例如：

```bash
BACKEND_URL=http://127.0.0.1:8001 pnpm dev
```

模型配置只由后端读取，不要将模型密钥设置为 `NEXT_PUBLIC_*`。

生产构建会固定 `BACKEND_URL`，运行 `pnpm build` 时就必须提供正确目标。Docker 使用 `http://backend:8000`，由 Compose 网络解析服务名；修改代理目标后需重新构建。生产输出使用 Next.js standalone，镜像同时包含 `public` 和 `.next/static`。

## 批改流程

1. 粘贴匿名作业，查看固定量表，点击“生成评分草稿”。
2. 草稿通过校验后，查看六维评分、理由和原文证据。点击引用可在原文中定位；引用偏移按 Unicode 字符转换为浏览器选区。
3. 逐维采纳或修改档位与理由，并勾选“我已核查此维度的档位与理由”。修改档位或理由后，该维度需要重新勾选。
4. 点击“保存复核”由后端重新计分；六维完成复核后，点击“确认保存批改记录”，再导出 JSON。
5. 生成失败时，原文仍然保留，可重新尝试或进入人工批改。

浏览器保存当前任务编号与输入。刷新会从后端恢复任务；修改原文会立即清除旧评分，并阻止旧请求覆盖新输入。手动修改复核尚未保存时，分数显示“保存后重新计分”，实际分数始终由后端计算。复核修改需点击保存后才会跨刷新恢复。

若任务的 `rubric_version` 与当前量表不同，页面标记为历史任务，禁止修改复核、人工接管或保存，也不轮询旧 queued/running 任务。历史维度隐藏当前量表满分，保留原得分；原始量表请参考历史 JSON。未确认历史任务可点击“按当前量表重新生成”，通过 retry 创建保留 `parent_id` 的新版任务；已确认历史任务仍可导出原始记录。

## 检查

```bash
pnpm lint
pnpm typecheck
pnpm build
```

页面使用系统字体，不依赖构建期间下载字体。桌面采用原文与复核双栏布局，小屏幕顺序展示原文、量表和复核表。

## 浏览器验收

浏览器验收使用测试专用 FastAPI 服务中的模型替身，驱动真实工具、API、数据库和页面。它不会读取模型密钥或调用外部模型；真实模型验收单独执行。

先从 `backend/` 启动测试服务：

```bash
UV_CACHE_DIR=/tmp/group9-uv-cache TEST_DB_PATH=/tmp/group9-ui-tests.sqlite3 uv run --group dev python tests/ui_server.py
```

为浏览器验收启动独立前端实例，再运行验收脚本：

```bash
NEXT_DIST_DIR=.next-e2e BACKEND_URL=http://127.0.0.1:8001 pnpm build
NEXT_DIST_DIR=.next-e2e BACKEND_URL=http://127.0.0.1:8001 pnpm start --port 3001
```

在另一个终端执行：

```bash
pnpm exec playwright install chromium
E2E_BASE_URL=http://127.0.0.1:3001 pnpm test:e2e
```

测试覆盖教师修改 A 维档位后得分 95.5、复核确认、JSON 下载、刷新恢复、原文变更失效、工具失败后重试、人工接管及桌面/移动布局。截图和导出记录写入忽略目录 `test-results/`。

历史任务使用浏览器路由返回旧快照，检查只读状态、隐藏满分、停止轮询、新版重生成及归档下载入口；真实旧数据的后端兼容由后端测试覆盖。本次实测状态见根目录 `docs/backend-acceptance.md`。

如果使用已安装的 Playwright 运行时，可以通过 `PLAYWRIGHT_MODULE_PATH` 指向其 `index.mjs`，通过 `PLAYWRIGHT_BROWSERS_PATH` 指定已安装浏览器目录。
