# FR-01 后端

FastAPI、HTTPX、python-dotenv 与 SQLite 支持单份作业批改。一个 Agent 调用量表读取、原文定位、Decimal 计分和草稿校验四类普通工具；教师确认最终评分。

## 安装与启动

在仓库根目录：

```bash
uv sync --project backend
uv run --project backend backend
```

需要 Python 3.13+。入口以 `backend.app:create_app` 工厂启动 uvicorn（无模块级 `app`），监听 `127.0.0.1:8000`，使用单 worker；后台任务在当前进程执行。API 文档：`http://127.0.0.1:8000/docs`。

后端加载仓库根 `.env` 中的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`，系统环境变量优先。默认服务与模型沿用现有魔搭和 `Qwen/Qwen3.8-Flash-Next`。配置不全时真实生成明确失败，不自动返回模拟评分。API 密钥不会提供给前端或写入执行摘要。

## 行为与持久化

- 固定量表版本 `af-2026-10-09-v1`；A-F 满分为 15、20、30、15、10、10；档位为 100、70、30、0。分项及总分由后端计算，保留半分。
- 原始作业按原样保存，输入版本为 UTF-8 原文的 SHA-256。引用位置为左闭右开字符区间，须逐字匹配原文和当前输入版本。
- 首次草稿校验，最多两轮修正／三次校验；通过即停止。模型或工具错误立即失败；另限制 24 次模型请求、每请求 90 秒及整个任务 300 秒预算。
- SQLite 默认为 `backend/data/grading.sqlite3`。模型建议、教师修改、最终评分与运行摘要分别保留。进程重启后未完成任务标为失败；原文仍可重试。
- 只有六维完成复核后允许确认；重复确认返回同一记录。已确认记录支持 JSON 导出。
- 提示要求每维选取 1-3 条关键证据、复用已经定位的有效引用并尽早校验，减少重复查证；不向模型提供固定样本的参考分数。
- 故障注入和模型替身仅测试使用，无生产 HTTP 注入接口。

## API

| 方法与路径 | 输入／行为 |
|---|---|
| `GET /api/rubric` | 读取量表 |
| `POST /api/tasks` | `{ "text": "匿名作业正文", "rubric_version": "af-2026-10-09-v1" }`；创建并后台运行 |
| `GET /api/tasks/{id}` | 查询原输入、状态、结果、错误和运行摘要 |
| `POST /api/tasks/{id}/retry` | 仅失败任务可重试；保留输入创建新任务，`parent_id` 关联旧任务，保留失败摘要 |
| `POST /api/tasks/{id}/manual` | 转入人工六维评分 |
| `PATCH /api/tasks/{id}/review` | `{ "input_version": "sha256", "dimensions": [{ "id": "A", "level": 100, "reason": "复核理由", "reviewed": true }, ...] }`；更新六维复核，重算得分 |
| `POST /api/tasks/{id}/confirm` | 检查并确认六维评分 |
| `GET /api/tasks/{id}/export` | 导出已确认记录 |

前端轮询查询接口，通过 Next.js 同源 `/api` 转发访问后端。具体响应字段和错误条件以 FastAPI OpenAPI 文档及类型定义为准。

## 测试

```bash
uv run --project backend pytest backend/tests
```

测试替身控制模型响应，执行真实工具及任务引擎，覆盖五个场景各三次，以及半分、非法档位、引用一致性、有限修正、复核权限、持久化与恢复。固定样本和参考结果位于根 `samples/`；参考得分禁止加入模型输入。

真实模型工具调用和评分检查必须另存结果，不能用模型替身的结果代填；此前魔搭返回 403，要求完成邮箱验证。Qwen 的 S1 完整运行形成 100 分草稿，S2 三次超时保留历史；外部切换根 `.env` 后，DeepSeek 的 S2 形成 70 分草稿并通过 11/11 机械检查，S1 因 429 限流失败。成功的 S1／S2 来自不同模型，不能记为同一模型的完整验收。实现未修改 `.env`；默认示例仍为 Qwen，实际配置可由环境变量覆盖。实际模型证据与待人工核定事项见 `docs/acceptance-record.md`。

## 真实模型验收 CLI

从仓库根目录执行：

```bash
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S1
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S2
```

脚本加载根 `.env`，使用独立的 `backend/data/live-acceptance.sqlite3`，向 `docs/live-runs/<时间与任务编号>.json` 写入服务／模型、超时配置、公开任务和程序检查结果，不写密钥。参考答案仅在模型返回后加载；只有检查与参考得分均符合才退出 0，否则退出 1。人工核定仍为 pending。脚本的 `--help` 可查看参数；本次先通过帮助与替身测试，随后按外部切换后的 DeepSeek 配置真实执行了 S1／S2，各自结果在 `docs/live-runs/` 保存。
