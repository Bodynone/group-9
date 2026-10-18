# 阅见 · AI Agent 作业辅助批改系统

教师提交匿名文本作业，Agent 按固定 A-F 量表取证、确定性计分并进行有限修正，教师复核后确认归档。的交付增加班级批次后端、并发调度、中文 CSV 成绩单和 Docker 部署；现有页面继续提供单份批改工作台，批量上传与学情分析页面由其他成员负责。

当前量表为 `2026-v1`，A-F 满分依次为 **15、25、25、15、10、10**，档位为 100%、70%、30%、0%。S1 参考总分为 100，C 维缺失的 S2 为 75。历史任务保持原量表与原评分，只读查看；未确认历史任务可按新量表创建关联的新任务，已确认记录仍可下载原始 JSON。

主规范见 [master-engineering-spec-and-wbs.md](master-engineering-spec-and-wbs.md)，本次验收状态见 [docs/backend-acceptance.md](docs/backend-acceptance.md)。旧版需求与实测证据保留在 [docs/requirements.md](docs/requirements.md)、[docs/acceptance-record.md](docs/acceptance-record.md)，其中 `af-2026-10-09-v1` 及 S2=70 的结果属于旧量表，不能作为新版实测结果。

## 本地启动

需要 Python 3.13+、uv、Node.js 22 与 `pnpm@11.28.5`。在仓库根目录安装：

```bash
uv sync --project backend
pnpm --dir frontend install --frozen-lockfile
```

根据 `.env.example` 配置根 `.env`，保留已有模型配置。系统环境变量优先，模型密钥只供后端读取。示例默认仍为魔搭与 `Qwen/Qwen3.8-Flash-Next`，实际模型由环境决定。

分别在两个终端运行：

```bash
uv run --project backend backend
```

```bash
pnpm --dir frontend dev
```

访问 [http://localhost:3000](http://localhost:3000)，API 文档位于 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。本地后端监听 `127.0.0.1:8000`，通过 `backend.app:create_app` 工厂以单 worker 启动；前端将同源 `/api` 请求代理到后端。

SQLite 默认保存到 `backend/data/grading.sqlite3`，可通过 `DATABASE_PATH` 修改。进程重启保留任务和归档记录，当前量表的未完成任务恢复为失败，便于重试或人工接管；旧量表任务保持原样。批次进度由子任务状态汇总。

## Docker 启动

安装 Docker 与 Compose，根目录准备好 `.env` 后执行：

```bash
docker compose up -d --build
docker compose ps
```

前端访问 [http://localhost:3000](http://localhost:3000)，后端健康检查 [http://localhost:8000/api/health](http://localhost:8000/api/health)。Dockerfile 为 Python 3.13 后端和 Node.js 22 前端分别构建生产镜像；Compose 等待后端健康后启动前端。

数据库目录挂载到宿主 `./data`，执行 `docker compose down` 后数据仍保留；容器内部固定为 `/app/backend/data/grading.sqlite3`。本地已有 `backend/data` 的数据库不会自动迁移到 `./data`，需要迁移时先停止本地服务，再将完整数据库目录复制至 `./data`。

容器后端使用单 worker，Compose 给予 40 秒停止宽限。镜像构建不需要模型密钥，根 `.env` 仅在运行时注入后端。前端构建参数 `BACKEND_URL=http://backend:8000` 写入 Next.js 代理配置；修改代理地址需要重建前端镜像，运行时单独设置该变量不会更新代理目标。

## 使用与接口

1. 粘贴匿名文本并生成草稿，可用 [samples/S1.txt](samples/S1.txt) 或 [samples/S2.txt](samples/S2.txt)；不要将 `expected.json` 提交给模型。
2. 查看 A-F 建议、逐字证据及待核查事项。首次草稿必须校验，最多两轮修正、三次校验。
3. 逐维采纳或修改档位、理由并勾选复核；保存后由后端重算分项与总分。
4. 确认归档后导出 JSON。失败可重试或人工批改；重试创建带 `parent_id` 的新任务，保留原记录。

批量后端提供 `POST /api/batch/tasks`、`GET /api/batch/{id}`、`GET /api/batches` 和 `GET /api/batch/{id}/export-csv`。每个文件传入 `filename` 和提取后的 `text`；该接口不接收二进制文件。调度默认并发上限为 3，单份失败不阻塞其余任务。CSV 带 UTF-8 BOM，包含六维得分、状态、安全标识及完成时间。详细接口及配置见 [backend/README.md](backend/README.md)。

系统按本地单教师使用设计，不含登录、PDF/OCR、自由量表和正式成绩发布。程序校验不能替代教师对评分依据的判断。

## 验证

```bash
uv run --project backend pytest backend/tests
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
docker compose config --quiet
```

单元测试与浏览器验收通过模型替身驱动真实工具、API 和数据库，无需模型密钥；浏览器步骤见 [frontend/README.md](frontend/README.md)。测试通过只能证明这些场景与流程，不代表模型评分准确率。

真实模型检查须单独执行并记录，以下命令加载根 `.env`、实际调用模型：

```bash
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S1
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S2
```

CLI 使用独立数据库 `backend/data/live-acceptance.sqlite3`，脱敏证据保存到 `docs/live-runs/`。参考答案仅在模型返回后加载，人工核定状态独立保留。历史实测 JSON 不改写为新量表结果；本次实际验证结果以 验收记录为准。
