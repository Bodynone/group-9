# 阅见后端

FastAPI、Python 3.13、HTTPX 与 SQLite WAL 支持单份和批量作业批改。Agent 使用量表读取、原文定位、Decimal 计分与草稿校验工具，教师复核后确认归档。

## 安装与配置

在仓库根目录运行：

```bash
uv sync --project backend
uv run --project backend backend
```

入口为 `backend.app:create_app` 工厂，无模块级 `app`；本地 CLI 监听 `127.0.0.1:8000`，单 worker 运行。API 文档见 `http://127.0.0.1:8000/docs`。

根 `.env` 提供 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 和可选的 `DATABASE_PATH`，系统环境变量优先。默认示例仍为魔搭和 `Qwen/Qwen3.8-Flash-Next`，不替换已有配置。配置不足或服务失败时任务明确失败，不返回模拟评分。密钥不发送给前端或写入执行摘要。

Token 审计只记录上游返回的有效非负计数。费用默认不可用；如需估算，须同时配置实际服务的 `MODEL_INPUT_PRICE_CNY_PER_MILLION` 与 `MODEL_OUTPUT_PRICE_CNY_PER_MILLION`（人民币/百万 Token）。执行摘要中 `cost_cny` 是配置价格的估计值，`cost_basis=configured_estimate`，不是服务账单；缺失或非法价格返回 `cost_cny=null`、`cost_basis=unavailable`，不假设所有模型共用价格。

容器启动和网络配置见根 README。Docker 以 `0.0.0.0:8000` 暴露服务，数据库挂载 `./data:/app/backend/data`，保持一个 worker；后台调度在当前进程运行，不能通过增加 worker 数实现扩容。

## 行为与持久化

- 当前固定量表 `2026-v1`，A-F 满分为 15、25、25、15、10、10，档位为 100、70、30、0；后端确定性重算分数。
- 旧版 `af-2026-10-09-v1` 数据保留原始评分与归档快照，不按新版覆盖。旧任务只读，未确认任务可通过 retry 按当前量表创建新任务并保留 `parent_id`；已确认历史 JSON 可继续导出。
- 原文按原样保存，`input_version` 是 UTF-8 原文的 SHA-256。引用使用左闭右开字符区间，并逐字匹配当前输入版本。
- 首次草稿必须校验，最多两轮修正、三次校验；另有限制 24 次模型请求、每请求 90 秒和单任务 300 秒预算。
- SQLite 默认为 `backend/data/grading.sqlite3`。`batches` 保存批次概要，子任务保留批次和文件标识；批次创建为原子事务，任务进度更新后重新汇总批次状态。
- 单份、重试与所有批次共享并发上限 3；单个任务异常标记失败后继续处理其余作业。终态为 `completed`、`partial_failed` 或 `failed`；重启保留所有已存结果，仅将当前量表的中断任务置为失败。
- 六维档位和理由完整、均已勾选复核后才可确认；归档记录不可改写。故障注入和模型替身仅存在于测试服务。

## API

| 方法与路径 | 输入／行为 |
|---|---|
| `GET /api/health` | 服务、模型名及配置是否存在；不调用模型 |
| `GET /api/rubric` | 当前量表 |
| `POST /api/tasks` | `{ "text": "匿名作业正文", "rubric_version": "2026-v1" }`，返回 202 并后台处理 |
| `GET /api/tasks/{id}` | 输入、状态、草稿、复核、错误和执行摘要 |
| `POST /api/tasks/{id}/retry` | 失败任务重试；未确认旧量表任务按新版重建，原任务不变 |
| `POST /api/tasks/{id}/manual` | 当前量表失败任务转人工六维评分 |
| `PATCH /api/tasks/{id}/review` | `{ "input_version": "sha256", "dimensions": [{ "id": "A", "level": 100, "reason": "复核理由", "reviewed": true }, ...] }`，重算六维分数 |
| `POST /api/tasks/{id}/confirm` | 检查并确认六维评分 |
| `GET /api/tasks/{id}/export` | 导出不可变确认记录 JSON |
| `POST /api/batch/tasks` | `{ "name": "班级作业", "rubric_version": "2026-v1", "files": [{ "filename": "001.txt", "text": "正文" }] }`，返回 202 批次概要 |
| `GET /api/batch/{id}` | 批次状态、成功/失败计数与子任务列表 |
| `GET /api/batches?limit=10&offset=0` | 按创建时间倒序的分页批次列表 |
| `GET /api/batch/{id}/export-csv` | 带 UTF-8 BOM 的中文成绩单下载 |

批量接口接收已提取的文本，不负责解析二进制文件。非法文本、量表版本或分页参数返回 422，不存在的资源返回 404，状态或版本不允许的修改返回 409。成绩单包含文件标识、总分、A-F 得分、状态、安全预警和完成时间；无成绩的行保留空分数，不伪造为 0。

批次名称、文件名和正文均须非空白，文件列表至少一项，每份正文最多 50,000 个 Unicode 字符，原始空白不裁剪。分页默认 `limit=10, offset=0`，`limit` 范围为 1—100，`offset` 为非负整数。

批次中每份文件占一个固定槽位。失败项调用现有 retry 接口后，新任务保留 `parent_id` 并原子替代当前槽位，总份数与上传顺序不变；旧失败任务及其 Trace 保留为只读历史，重复重试旧尝试返回 409。`GET /api/batch/{id}` 和 CSV 只展示每个槽位的当前任务。

`completed_count` 统计 `pending_review` 和 `confirmed`，表示处理结束；人工接管后尚未填写的成绩仍为空。全部排队时批次为 `queued`，有处理进展且仍有排队/运行项时为 `running`；全部终结后按失败比例进入三类终态。批次详情和分页采用同一数据库快照，避免并发写入导致计数与列表不一致。

成绩单优先使用教师 review，只有不存在 review 时才使用 draft；零分保留，排队、运行、失败及未填成绩留空。完成时间来自最近的终态事件并转为北京时间，不随普通日志或复核保存改变；文件名中的逗号、引号、换行正确转义，公式前缀按文本导出。安全标识默认 `none`/“正常”，实际检测由算法模块接入。

班级学情分析接口、安全护栏和成本审计由其他成员负责，不属于本次 交付。

## 验证与历史证据

```bash
uv run --project backend pytest backend/tests
```

替身测试执行真实工具、存储与调度器，覆盖批量并发、异常隔离、状态汇总、CSV、分页、恢复和既有单份流程。当前 S1 参考分为 100，S2 为 75；参考结果禁止放入模型输入，教师核定独立保留为 pending。

历史实测中，Qwen 的 S1 得到 100，DeepSeek 的 S2 得到 70；这些来自旧量表与不同模型，不能当作当前量表或同一模型的完整验收。原始证据保留在 `docs/acceptance-record.md` 和 `docs/live-runs/`，本次结果见 `docs/backend-acceptance.md`。

以下 CLI 会加载根 `.env` 并实际调用模型；仅当程序检查与参考分均符合才退出 0：

```bash
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S1
UV_CACHE_DIR=/tmp/group9-uv-cache uv run --project backend python backend/scripts/live_acceptance.py --sample S2
```

CLI 使用独立数据库 `backend/data/live-acceptance.sqlite3`，向 `docs/live-runs/` 写入不含密钥的任务与检查结果，不改写历史实测 JSON。
