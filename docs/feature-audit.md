# 主规范功能核对（2026-10-22）

核对对象：主规范 14 个 REST API、三块前端页面、后端批量/安全/分析组件、五位成员交付物。结论基于仓库源码和测试；后端 208 项测试已在临时 Python 3.12 环境通过，真实模型与前端端到端验收尚未执行。护栏 5ms 性能测试在一次全套运行中受机器负载影响未达标，单独复测及随后全套复测通过；该阈值需在项目目标环境复验。

| 范围 | 仓库状态 | 核对依据与限制 |
|---|---|---|
| API 1–9 单份闭环 | 路由及实现齐全，后端测试通过 | `backend/src/backend/app.py`、`storage.py`、`agent.py`、`tools.py`；教师复核与归档流程已接线。 |
| API 10–11 批次创建/进度 | 路由及实现齐全 | `app.py`、`batch.py`、`storage.py`，有 `test_batch.py` 与 `test_batch_storage.py`。 |
| API 12 学情分析 | 路由及实现齐全 | `app.py`、`clustering.py`，有 `test_analytics_api.py` 与 `test_clustering.py`。 |
| API 13–14 CSV/历史批次 | 路由及实现齐全 | `app.py`、`storage.py`，CSV 带 BOM 的行为见现有测试。 |
| 前端三 Tab、批量上传、大屏 | 文件与接线齐全 | `frontend/app/page.tsx`、两个组件及 `frontend/lib/grading.ts`；本次未执行编译和浏览器验收。 |
| Docker 部署 | 文件存在 | 根 `Dockerfile`、`docker-compose.yml`；本次未实际构建镜像。 |
| 安全护栏与 Token 审计 | 实现与测试文件存在 | `guardrails.py`、`provider.py`、`test_guardrails.py`、`test_usage_audit.py`；未作本次运行验证。 |
| 胡梦杰评测交付 | 已补齐代码与样本；新增测试通过，真实数据待运行 | `samples/benchmark/` 20 份、`backend/scripts/ablation_study.py`、`docs/eval-report.md`。样本暂定标签需教师复核。 |

待完成的验收：在项目要求的 Python 3.13 环境复跑 `uv run --project backend pytest backend/tests`；安装前端依赖后运行 `pnpm --dir frontend typecheck`、`pnpm --dir frontend build`；配置真实模型后运行三组评测。主规范描述的 `.docx` 文件出现在 API 示例，但前端任务清单只要求 `.txt`/`.md`；当前批量接口接收已提取文本，二进制 `.docx` 解析不在实现范围内。部署与模型名称也应以当前 `.env` 和运行结果为准，不能仅依据主规范中的示例值判定。
