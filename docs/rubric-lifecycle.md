# 评分量表管理与作业任务选择（2026-10-23补充）

本补充落实教师工作台反馈，不改变评分、证据和教师确认协议。既有25条v2接口继续保留，新增5条量表管理接口，合计30条。

## 教师界面

- 查看量表版本后，可删除未发布且未被引用的当前草稿。删除前显示当前标题、版本及确认操作，支持取消。
- 已发布版本不能删除。可以归档当前版本或整个量表系列，默认列表隐藏归档项；勾选“显示已归档量表”后可恢复。
- 系列归档影响系列内所有版本的可用性，但不改写各版本自身的归档标记。恢复系列后，单独归档过的版本仍需分别恢复。
- 归档标准不能用于新建作业、复制新标准或发布待发布作业。已发布作业仍按原绑定接受提交、重试和教师复核，任务及确认导出保持不变。
- “3. 选择或新建作业任务”先展示课程和已有任务选择。新建表单默认收起，字段说明任务是老师布置的题目和要求，学生的实际答案在右侧提交。
- “保存任务草稿”只保存教师的任务配置，不调用模型。创建成功后自动选中该任务并收起新建入口；检查或修改后发布，才能提交学生文本。

## API补充

| 方法 | 路径 | 行为 |
|---|---|---|
| DELETE | `/api/v2/rubric-versions/{id}` | 删除未被引用的草稿 |
| POST | `/api/v2/rubric-versions/{id}/archive` | 归档当前版本 |
| POST | `/api/v2/rubric-versions/{id}/restore` | 恢复当前版本 |
| POST | `/api/v2/rubrics/{id}/archive` | 归档整个系列 |
| POST | `/api/v2/rubrics/{id}/restore` | 恢复整个系列 |

以上请求均携带JSON `{"expected_revision": 1}`，使用相应对象的当前修订号。版本描述增加 `archived`、`rubric_archived`、`rubric_revision`；系列修订号使用 `rubric_revision`。旧对象缺少系列revision时按1解释，不需要批量改写旧数据。

`GET /api/v2/rubrics` 默认过滤归档项，`?include_archived=true` 同时返回归档项。分页在过滤之后执行，已删除草稿不返回。`GET /api/v2/rubric-versions/{id}` 仍可读取归档版本，已删除草稿返回404。

状态冲突返回409：旧修订号 `REVISION_CONFLICT`、已发布版本删除 `STATE_CONFLICT`、引用中的草稿删除 `RUBRIC_IN_USE`、新配置使用归档标准 `RUBRIC_ARCHIVED`。

## 数据与兼容

使用现有JSON存储对象的归档标记及修订号，不更改量表definition/content_hash、任务上下文或确认记录。删除草稿保留内部tombstone，防止版本号复用；界面不再显示该草稿。删除前在同一事务中检查作业、任务上下文、任务和确认记录引用。

新建量表仍优先复制原默认已发布预设。若其已归档，使用其他可用发布标准；所有发布标准都归档时返回可操作提示，教师需先恢复标准。页面展示实际复制的维度与分值。

## 验证

本次后端268项测试通过，包含11项新增生命周期用例。浏览器在隔离数据库与脚本模型下验收作业任务的新建/发布、四维改档88.00与确认、批量部分失败、CSV、历史版本、草稿删除/取消、版本与系列归档恢复、新绑定过滤、1/2/12维图表及390/768宽度。此类测试证明协议与流程，不代表真实模型准确率。

运行：

```powershell
uv run --project backend pytest backend/tests
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend build --webpack
```

浏览器回归沿用 `backend/tests/ui_server.py` 和 `frontend/tests/v2-e2e.mjs`，只在独立测试库、脚本模型上运行。当前工作台页面不能替代正式教师评分标准或人工评测。
