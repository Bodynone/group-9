# FR-01 验收记录

记录日期：2026-10-13（Asia/Shanghai）。判据与数字来源见 [requirements.md](requirements.md)。本记录区分可控程序测试、真实模型调用及人工核定；没有证据的事项保留“待完成”。

## 人工核定与真实互评

| 事项 | 状态 | 判定人／日期 | 原文证据、结论与理由 |
|---|---|---|---|
| 教师实际困难及匿名化要求 | 待确认 | 待填写 | 待填写 |
| 固定量表与 S1=100、S2=70 参考档位 | 待核定 | 待填写 | `samples/expected.json` 当前 `human_approval=pending` |
| 草稿引用对档位的语义支持 | 待核查 | 待填写 | 程序逐字校验不能替代教师判断 |
| 真实 AI 建议的逐项采纳／拒绝 | 待核查 | 待填写 | 方向授权不等于逐项人工认可 |
| 邻组反馈与本组处理 | 待互评 | 待填写 | 待填写真实原文反馈、采纳／拒绝理由和修改前后 |
| 源任务单实际六维评分及最终版本 | 待评价 | 待填写 | 不用 S1/S2 的参考分数代填 |

S1 中匿名角色甲、乙、丙与 G-P 的经历是合成样本内容，不是本项目真实协作或互评记录。

## 可控程序验收

执行方式：模型测试替身驱动真实工具与执行引擎；五个场景各三次，逐次满足全部判据才通过。原始输入、SHA-256、工具调用、每次校验结论、修正轮次和停止状态须能对应任务编号。故障配置仅测试使用。

| 场景 | 第 1 次 | 第 2 次 | 第 3 次 | 证据路径／测试名称 |
|---|---|---|---|---|
| T1 正常 | 通过 | 通过 | 通过 | `backend/tests/test_agent.py::test_five_acceptance_scenarios_three_times[T1-run-1/2/3]` |
| T2 C 区缺失 | 通过 | 通过 | 通过 | 同测试的 `T2-run-1/2/3` 参数项 |
| T3a 定位 503、解除后重试 | 通过 | 通过 | 通过 | 同测试的 `T3a-run-1/2/3` 参数项 |
| T3b 一次引用修正 | 通过 | 通过 | 通过 | 同测试的 `T3b-run-1/2/3` 参数项 |
| T3c 持续错误达到上限 | 通过 | 通过 | 通过 | 同测试的 `T3c-run-1/2/3` 参数项 |

总计：**15/15 通过（可控程序验收）**。2026-10-13 后端核验：在 `backend/` 执行 `UV_CACHE_DIR=/tmp/group9-uv-cache uv run --group dev pytest -q --junitxml=/tmp/group9-backend-tests.xml`（报告复制至 `docs/backend-test-results.xml`），得到 **92 passed、0 failed**（1 条依赖弃用警告）。自动测试成功只证明受控条件下的流程，不证明模型语义评分的准确性。

| 其他检查 | 状态 | 证据／说明 |
|---|---|---|
| 半分、合法档位、六维完整性、虚构／旧引用拒绝 | 通过 | `backend/tests/test_tools.py`、`test_agent.py`；含定位来源与失败后重新定位检查 |
| 教师改档重算、复核确认限制、重复确认、导出一致性 | 通过 | `backend/tests/test_api.py`、`test_storage.py`；含确认后不可变、人工重复接管与复核摘要原子保存 |
| 输入保留、重启恢复、重试、人工接管 | 通过 | `backend/tests/test_agent.py`、`test_api.py`、`test_storage.py` |
| 前端复核保存与失败恢复流程 | 通过 | Playwright 完整 E2E 连续两次通过；包含定位、95.5 半分重算、确认／导出／刷新恢复、输入变化清除旧结果、失败重试与完整人工接管 |
| pytest | 通过 | 后端 92 项通过；命令与日期如上，机器报告 [backend-test-results.xml](backend-test-results.xml)（92 项，0 failures，0 errors） |
| 前端生产构建 | 通过 | 独立及默认生产构建成功；[frontend-check-results.json](frontend-check-results.json) 保存各次命令与退出码 |
| ESLint、TypeScript 独立检查 | 通过 | 两项检查均 exit 0；完整命令及结果见 [frontend-check-results.json](frontend-check-results.json) |
| 桌面／手机浏览器布局 | 通过 | 无页面错误、无横向溢出；[桌面确认截图](../frontend/test-results/desktop-confirmed.png)、[手机复核截图](../frontend/test-results/mobile-review.png)、[失败截图](../frontend/test-results/failure.png)及[确认导出 JSON](../frontend/test-results/confirmed-record.json) |

## 真实模型检查

已知前置状态：此前使用仓库 `.env` 的真实推理请求返回 HTTP 403，服务提示账号先完成邮箱验证。此历史结果保留为服务不可用记录。2026-10-13 本次重试已取得真实工具调用及 S1 完整评分结果；Qwen 的 S2 三次实测均超时，全部失败按实记录。随后根 `.env` 被用户／外部切换至 DeepSeek（本次实现未修改 `.env`），按新配置追加实测，DeepSeek S2 机械验收通过，DeepSeek S1 因 429 限流失败。不得记录 API 密钥。

| 日期与服务／模型 | 输入与检查 | 结果 | 证据 |
|---|---|---|---|
| 既有会话记录；魔搭／`Qwen/Qwen3.8-Flash-Next` | 真实推理连通性 | 403；邮箱验证前置条件未满足 | 会话中服务返回；当时尚无成功模型评分 |
| 2026-10-13；魔搭／`Qwen/Qwen3.8-Flash-Next` | 真实模型工具请求 | 通过；模型实际请求工具 | [live-model-check.json](live-model-check.json) |
| 2026-10-13 19:54（Asia/Shanghai）；魔搭／`Qwen/Qwen3.8-Flash-Next` | S1 完整真实 Agent 循环 | 分项 15、20、30、15、10、10，总分 100；模型请求 10 次、校验 1 次、修正 0 轮；状态 `pending_review`，人工核定仍待完成 | [live-acceptance.json](live-acceptance.json)，任务 `f30cb5b1-6188-40f6-8a98-8415844613e5` |
| 2026-10-13 19:57（Asia/Shanghai）；魔搭／`Qwen/Qwen3.8-Flash-Next` | S2 首次真实运行 | `model_timeout`；第 2 次模型请求超时，未生成有效草稿；输入及量表保留，允许重试 | [live-acceptance-s2-timeout.json](live-acceptance-s2-timeout.json)，任务 `594e4bae-6924-4a5a-bd68-b3de6e140fe0` |
| 2026-10-13 20:02（Asia/Shanghai）；S2 第二次 | 固定 S2、真实模型重试 | 再次 `model_timeout`；15 次模型请求，已调用计分得到 70，但未形成通过校验的有效草稿，不能记为评分成功 | [live-acceptance-s2-retry-timeout.json](live-acceptance-s2-retry-timeout.json) |
| 2026-10-13 20:05（Asia/Shanghai）；S2 第三次 | 固定 S2，限制每维关键证据数量、减少重复定位；请求超时 90 秒，总预算仍 300 秒 | `model_timeout`；2 次模型请求，0 次校验、0 轮修正，`draft/review=null`；原输入保留，无有效评分 | [live-acceptance-s2.json](live-acceptance-s2.json)，任务 `071e096e-05a7-4b45-8121-143b8b9527a3` |
| 2026-10-13 20:10（Asia/Shanghai）；DeepSeek S1 | 外部切换后的 `.env` 模型 `deepseek-ai/DeepSeek-V4-Flash-0731`，真实 CLI | 第 2 次请求 `model_http_429`；原文保留，无有效草稿；当前模型的 S1 验收仍待重试完成 | [DeepSeek S1 运行证据](live-runs/20261013T201046+0800-789905fe-5d82-4bd8-9839-cec6c5969761.json) |
| 2026-10-13 20:11（Asia/Shanghai）；DeepSeek S2 | 固定 S2、真实 CLI，模型 `deepseek-ai/DeepSeek-V4-Flash-0731` | **11/11 机械检查通过**；分项 15、20、0、15、10、10，总分 70；模型请求 4 次、校验 1 次、修正 0 轮；`pending_review`，人工核定 pending | [DeepSeek S2 运行证据](live-runs/20261013T201045+0800-189e0eef-17a8-467f-9679-807f16760c3e.json) |

Qwen 的 S2 三次均未通过：首次超时，第二次虽实际调用计分得到 70 但没有有效草稿，第三次仍超时，历史证据保留。外部切换 `.env` 后，通过 CLI 按 DeepSeek 新配置追加 S1／S2 两次实测；S2 的真实缺失评分机械验收已完成，S1 受限流仍待重试。**成功的 S1 来自 Qwen，成功的 S2 来自 DeepSeek；不能宣称同一模型的 S1／S2 均已通过。** 当前不再追加调用。参考档位、教师语义核定、真实互评与正式评价仍待完成。

如服务仍不可用，记录失败时间、状态码及脱敏错误，保留“未完成真实模型验收”。如真实结果偏离拟定档位，保存原结果及人工裁定，不修改参考答案以制造通过。

## 单次验收填写模板

- 场景／重复编号：
- 验收人、核查人、日期与设备：
- 模型服务、模型及配置版本（不含密钥）：
- 任务编号、输入文件与 SHA-256、量表版本：
- 前置条件／故障注入配置：
- 操作步骤及开始／停止时间：
- 实际六维档位、得分、总分及状态：
- 引用逐字定位、四类调用、校验次数、修正轮次、停止规则检查：
- 失败前后输入比较、恢复与教师控制检查：
- 每项通过／不通过及原因：
- 原始输入、输出、截图、执行摘要与导出证据路径：
- 人工语义核查、采纳／拒绝理由和待办：
