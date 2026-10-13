# 面向课程的 AI Agent 作业辅助批改系统

根据 `9_1_v2.pdf` 实现 FR-01：教师输入一份匿名文本作业，单 Agent 按固定 A-F 量表取证、计分及有限修正，教师复核后确认保存。默认量表版本为 `af-2026-10-09-v1`；模型建议始终待教师确认。

需求与验收表达见 [docs/requirements.md](docs/requirements.md)，实际执行及待人工核定事项见 [docs/acceptance-record.md](docs/acceptance-record.md)，完整冻结样本见 [samples](samples)。样本内课堂小测统计是待批改案例。

## 启动

需要 Python 3.13+、uv、Node.js 与 pnpm。以下命令在仓库根目录执行。首次安装：

```bash
uv sync --project backend
pnpm --dir frontend install
```

根目录 `.env` 使用以下配置；系统环境变量优先。保留已有密钥，或根据 `.env.example` 填写。密钥由后端使用。

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api-inference.modelscope.cn/v1
OPENAI_MODEL=Qwen/Qwen3.8-Flash-Next
```

分别在两个终端启动：

```bash
uv run --project backend backend
```

```bash
pnpm --dir frontend dev
```

访问 [http://localhost:3000](http://localhost:3000)。后端监听 `127.0.0.1:8000`，单 worker 运行；前端将同源 `/api` 请求转发到后端。服务通过 `backend.app:create_app` 工厂启动（无模块级 `app`）。API 文档为 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。SQLite 默认保存到 `backend/data/grading.sqlite3`，重启保留记录，未完成任务转为失败可重试。

真实验收中，Qwen 的 S1 形成 100 分待确认草稿；Qwen 的 S2 三次超时保留历史。根 `.env` 随后被用户／外部切换为 DeepSeek，本次实现未修改 `.env`；DeepSeek 的 S2 形成 70 分草稿、11/11 机械检查通过，S1 因 429 限流失败。两份成功结果来自不同模型，人工核定与当前模型的完整验收仍待完成。全部结果见验收记录。缺配置、服务或工具错误时，页面保留作业并提供重试与人工批改。

## 使用

1. 粘贴已匿名化的单份作业，点击“生成评分草稿”。可用 `samples/S1.txt` 或 `samples/S2.txt` 验证流程；不要把 `expected.json` 的参考答案粘贴给模型。
2. 查看六维建议、逐字证据定位、待核查事项与执行摘要。首次草稿必须校验，最多两轮修正／三次校验。
3. 逐维采纳或调整档位及理由，再明确确认。分项与总分始终由后端重算。
4. 保存确认记录并导出 JSON。失败时可直接重试，或填写完整人工评分表后确认。重试会创建以 `parent_id` 关联旧失败任务的新任务，保留旧失败摘要。

本次验证后，生产页面 [http://localhost:3001](http://localhost:3001) 与真实后端 `127.0.0.1:8000` 已启动，后端当前模型为 `deepseek-ai/DeepSeek-V4-Flash-0731`。上述 Qwen 配置是默认示例，实际值由根 `.env` 和系统环境变量决定。

首版按本地单教师设计；不包含批量、PDF/OCR、自由量表、登录和正式成绩发布。工具校验通过不能替代教师对评分依据的判断。

## 验证

```bash
uv run --project backend pytest backend/tests
pnpm --dir frontend lint
pnpm --dir frontend exec tsc --noEmit
pnpm --dir frontend build
```

受控验收通过模型替身驱动真实工具与执行引擎，T1/T2/T3a/T3b/T3c 各三次，共 15 次。15/15 是固定样本流程判据，不代表模型泛化评分准确率。真实模型检查与人工核定另行记录；真实互评和源任务单实际评分仍待填写。

可重复执行的真实模型检查命令（加载根 `.env`，需服务可用）：

```bash
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S1
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S2
```

CLI 使用独立数据库 `backend/data/live-acceptance.sqlite3`，脱敏证据保存到 `docs/live-runs/`。仅当程序检查与参考分数均符合时退出 0；失败退出 1。参考分数在模型返回后才加载，不放入模型输入。人工核定始终单独保留为 pending。

后端接口、配置及持久化说明见 [backend/README.md](backend/README.md)。`.env`、数据库、日志和验收运行产物不提交；示例配置只有占位密钥。
