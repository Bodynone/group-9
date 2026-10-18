# 交付验收记录

验收日期：2026-10-17（Asia/Shanghai）。本记录只记录实际完成的检查。测试使用替身，不读取模型密钥或调用外部模型。真实模型验收与教师核定未包含在本次自动化检查中。

## 交付边界

负责 SQLite 批次扩展、并发调度、批次 API、CSV 成绩单、Docker 全栈部署和旧量表兼容。当前量表统一为 `2026-v1`，A-F 满分 15/25/25/15/10/10，S1=100、S2=75。批量上传 UI、班级分析、安全护栏和成本审计由其他成员负责。

旧量表 `af-2026-10-09-v1` 的任务及确认记录保留原值，只读查看；未确认历史任务可按新量表重生成并保留关联。历史实测文件中 S2=70 属于旧 B=20/C=30 量表，不改写为新结果。

## 自动化验收清单

| 检查 | 通过标准 | 实测状态 |
|---|---|---|
| 后端完整测试 | 既有单份流程及新增批次/迁移测试全部通过 | 通过：153 passed；另有 1 条现有 Starlette 弃用警告 |
| 批次事务与状态 | 原子创建；并发上限 3；单份失败隔离；三类终态与计数正确 | 通过：五任务及跨批次/单份/重试混合并发测试；写入回滚、跨连接快照与状态计数测试 |
| CSV 与分页 | BOM、中文列头、六维分数和空值正确；不存在批次 404；分页边界有效 | 通过：单元测试及容器内五行成绩单；B/C 各25分，教师分数优先，公式前缀转义 |
| 旧量表兼容 | 旧数据不重算；旧写操作受限；新版 retry 保留 parent；旧确认 JSON 可导出 | 通过：旧 schema 原始 JSON 字节不变、四类未确认状态与已归档接口测试；浏览器历史状态覆盖 |
| 重启与关闭 | 中断任务失败恢复、批次汇总正确；关闭不遗留可继续写入的工作任务 | 通过：调度取消与 lifespan 关闭顺序测试；容器重建后 queued/running 两项均恢复 interrupted 失败 |
| 前端 lint / typecheck | ESLint 与 TypeScript 无错误 | 通过：在 frontend/ 直接运行本地 eslint、tsc --noEmit，均退出 0 |
| 前端生产构建 | Next.js standalone 输出完整，代理地址正确 | 通过：主机与 Node 22 容器构建成功；容器代理和静态资源实际可访问 |
| 浏览器受控验收 | 单份复核导出、历史只读与重生成、停止旧任务轮询、桌面移动布局通过 | 通过：Playwright 全流程、五种历史状态及桌面/移动布局，无浏览器运行错误 |
| Compose 配置 | `docker compose config --quiet` 通过，不输出展开的密钥 | 通过 |
| Docker 构建 | Python 3.13、Node 22、锁定依赖成功构建两个 target | 通过：两个镜像均构建成功，Python 3.13.16、Node 22、pnpm 11.28.5 |
| 容器连通性 | 首页/静态资源和代理 health、后端 health 均可用 | 通过：为避开已有服务，使用隔离端口 3108/8108；默认 3000/8000 映射通过配置检查 |
| 容器持久化 | 重建后任务、批次和归档仍可读取，目录挂载保留数据库 | 通过：隔离目录 `/tmp/group9-backend-docker-data`；重建后归档 JSON 与 CSV 原样一致 |

## 执行命令与证据

```bash
uv run --project backend pytest backend/tests
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

浏览器验收服务与命令见 `frontend/README.md`。容器验收使用隔离 Compose 项目 `group9-backend-check`，测试端口 3108/8108，数据库目录 `/tmp/group9-backend-docker-data`，注入测试 provider 而不调用真实模型。本地浏览器验收使用 3109/8109，完整通过。容器验收先使用测试 provider 验证真实工具/接口，再切回最新后端镜像的生产工厂，确认健康检查、旧归档读取及缺密钥时明确失败，未发起真实模型请求。

主机 pnpm 的自动版本切换尝试写入只读用户目录，因此主机验证直接执行 `frontend/node_modules/.bin/eslint`、`tsc --noEmit` 和 `next build`，对应 package scripts，未修改工具版本或锁文件。`node --check frontend/tests/e2e.mjs` 与 `git diff --check` 通过；容器内使用 manifest 指定的 pnpm 正常安装及构建。

部署约束：Dockerfile 使用多阶段构建，前端 `BACKEND_URL` 在构建时固定为 `http://backend:8000`；后端单 worker，Compose 的 `stop_grace_period` 为 40 秒，数据库目录挂载 `./data:/app/backend/data`。容器首次构建需要拉取基础镜像和锁定依赖。

## 结果证据与剩余验收

机器可读结果见 [backend-smoke-results.json](backend-smoke-results.json)。浏览器截图与下载记录保存在忽略目录 `frontend/test-results/`。新增测试分布在 `backend/tests/test_batch.py`、`test_batch_storage.py` 和 `test_legacy_api.py`；原有 92 项覆盖保留，更新了新量表的分值断言。

容器五份作业初始结果为成功3、失败2；失败项重试后仍为总数5，人工接管并确认后为成功5、失败0。S2为75；教师将B维改为70%后总分92.5，CSV采用复核分数。容器重建前后已确认JSON及CSV完全相同。随后生产工厂在空密钥下返回 `model_not_configured`，未使用替身评分冒充真实模型结果。

真实模型的40份作业≤300秒吞吐、429发生率和评分准确率尚未实测。并发上限3与受控测试不能替代这些验收，教师核定状态仍保留 pending。
