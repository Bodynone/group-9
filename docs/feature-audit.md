# 主规范功能核对（2026-10-22）

核对对象：主规范 14 个 REST API、三块前端页面、后端批量/安全/分析组件、五位成员交付物。兼容性复核环境为 Windows、Python 3.13.2：后端 222 项测试全部通过，含原有测试及新增评测脚本回归。TypeScript 检查、ESLint 和 webpack 生产构建通过；单份浏览器验收与真实批量 API 集成验收通过，模型使用测试替身，数据库独立于 Demo。真实模型效果评测尚未执行。

护栏性能门禁曾在本机负载下重复超过 5ms。现对以必需关键词开头的模式跳过无关长前缀，保持原正则与风险等级；Unicode 小写转换改变长度时回退全文扫描。包含长前缀、Unicode 和原 5ms/10ms 阈值的测试均通过。检查工作区复用依赖目录，因此构建存在 standalone 跟踪根目录外依赖的提示；本次验证的是 `next start` 服务，不包含独立打包产物或 Docker 镜像部署。

| 范围 | 仓库状态 | 核对依据与限制 |
|---|---|---|
| API 1–9 单份闭环 | 路由及实现齐全，后端测试通过 | `backend/src/backend/app.py`、`storage.py`、`agent.py`、`tools.py`；教师复核与归档流程已接线。 |
| API 10–11 批次创建/进度 | 路由及实现齐全 | `app.py`、`batch.py`、`storage.py`，有 `test_batch.py` 与 `test_batch_storage.py`。 |
| API 12 学情分析 | 路由及实现齐全 | `app.py`、`clustering.py`，有 `test_analytics_api.py` 与 `test_clustering.py`。 |
| API 13–14 CSV/历史批次 | 路由及实现齐全 | `app.py`、`storage.py`，CSV 带 BOM 的行为见现有测试。 |
| 前端三 Tab、批量上传、大屏 | 编译与浏览器流程通过 | `frontend/app/page.tsx`、两个组件及 `frontend/lib/grading.ts`；覆盖单份复核/导出、历史记录、批量进度、大屏及 CSV。 |
| Docker 部署 | 文件存在 | 根 `Dockerfile`、`docker-compose.yml`；本次未实际构建镜像。 |
| 安全护栏与 Token 审计 | 后端回归通过 | `guardrails.py`、`provider.py`、`test_guardrails.py`、`test_usage_audit.py`；批量集成也核验了注入告警。 |
| 胡梦杰评测交付 | 已补齐代码与样本；新增测试通过，真实数据待运行 | `samples/benchmark/` 20 份、`backend/scripts/ablation_study.py`、`docs/eval-report.md`。样本暂定标签需教师复核。 |

待完成的验收：配置真实模型后运行三组评测，并由独立教师复核暂定标签；Docker 镜像和 standalone 部署仍待实测。主规范描述的 `.docx` 文件出现在 API 示例，但前端任务清单只要求 `.txt`/`.md`；当前批量接口接收已提取文本，二进制 `.docx` 解析不在实现范围内。部署与模型名称也应以当前 `.env` 和运行结果为准，不能仅依据主规范中的示例值判定。
