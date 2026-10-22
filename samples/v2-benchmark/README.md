# 三课程 v2 合成样本（待人工核定）

软件工程、数据库实验报告、科技伦理论述各12份，共36份。`manifest.json` 保存每份原文的实际 UTF-8/LF 字节 SHA-256、课程作业和量表文件引用。示例量表不是任课教师正式标准，正文均为合成文本；同类文本存在模板重叠，不能作为独立真实学生样本集宣称效果。

软件工程文本复用既有匿名合成基准的前12份，按10月20日基线的15/20/30/15/10/10预设评价，原20份 `samples/benchmark/` 及其2026-v1规则保留不变。

`reference` 目前全部待核定。两位不同人工评阅者须分别填写 `{id, levels}`，再由人工裁定填写 `adjudicated_levels`，完成后将状态改为 `adjudicated`。levels 为维度ID到该量表档位ID的映射。不得使用模型输出替代人工参考。评测执行器会拒绝把未核定、评阅者相同、维度/档位不合法的参考计入评分一致率或总分误差。

```powershell
uv run --project backend python backend/scripts/ablation_study_v2.py --check
# 显式调用真实模型；使用根目录.env，结果默认留在忽略的backend/data目录
uv run --project backend python backend/scripts/ablation_study_v2.py --run --samples 36
```

三条件分别为直接JSON、工具但不校验、完整生产引擎。失败也写入逐样本结果，保存输入与配置哈希、模型草稿、末次文本、耗时、调用与usage；只在有有效人工裁定时计算评分一致性。三组仍有提示词和输出协议差异，不能将全部差异解释为校验工具的因果效果。
