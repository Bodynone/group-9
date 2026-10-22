"use client";

import type { Definition, RubricVersion } from "@/lib/grading-v2";

export function RubricEditor({ version, definition, onChange, onSave, onPublish, onExample, busy }: {
  version: RubricVersion; definition: Definition; onChange: (body: Definition) => void;
  onSave: () => void; onPublish: () => void; onExample: () => void; busy: boolean;
}) {
  const readOnly = version.state === "published" || busy;
  function dimension(index: number, key: string, value: string) {
    onChange({ ...definition, dimensions: definition.dimensions.map((row, i) => i === index ? { ...row, [key]: value } : row) });
  }
  return <section className="v2-card" aria-label="评分量表编辑器">
    <div className="v2-section-title"><h2>2. 配置评分量表</h2><span>{version.state === "published" ? "已发布 · 只读" : "草稿"} · 第 {version.version_no} 版</span></div>
    <p>配置 1–12 个维度、2–8 个统一档位。合计与评分均由后端计算，发布后永久只读。</p>
    <details open={version.state === "draft"}><summary>查看维度、档位与逐项判据（{definition.dimensions.length} 维）</summary><fieldset disabled={readOnly}>
      <label>量表标题<input value={definition.title} onChange={e => onChange({ ...definition, title: e.target.value })} /></label>
      <h3>统一档位</h3>
      {definition.levels.map((level, index) => <div className="v2-inline" key={index}>
        <label>档位 ID<input value={level.id} onChange={e => {
          const id = e.target.value;
          onChange({ ...definition, levels: definition.levels.map((l, i) => i === index ? { ...l, id } : l),
            dimensions: definition.dimensions.map(d => ({ ...d, criteria: Object.fromEntries(Object.entries(d.criteria).map(([k, value]) => [k === level.id ? id : k, value])) })) });
        }} /></label>
        <label>名称<input value={level.label} onChange={e => onChange({ ...definition, levels: definition.levels.map((l, i) => i === index ? { ...l, label: e.target.value } : l) })} /></label>
        <label>比例 %<input inputMode="decimal" value={level.percent} onChange={e => onChange({ ...definition, levels: definition.levels.map((l, i) => i === index ? { ...l, percent: e.target.value } : l) })} /></label>
        <button type="button" disabled={definition.levels.length <= 2} onClick={() => onChange({ ...definition, levels: definition.levels.filter((_, i) => i !== index), dimensions: definition.dimensions.map(d => ({ ...d, criteria: Object.fromEntries(Object.entries(d.criteria).filter(([key]) => key !== level.id)) })) })}>删除档位</button>
      </div>)}
      <button type="button" disabled={definition.levels.length >= 8} onClick={() => {
        const id = `level_${crypto.randomUUID().slice(0, 8)}`;
        onChange({ ...definition, levels: [...definition.levels, { id, label: "新档位", percent: "50.00" }], dimensions: definition.dimensions.map(d => ({ ...d, criteria: { ...d.criteria, [id]: "" } })) });
      }}>添加档位</button>
      <h3>评价维度与逐档判据</h3>
      {definition.dimensions.map((d, index) => <details className="v2-dimension" key={index} open={definition.dimensions.length <= 4}>
        <summary>{d.name || "未命名维度"} · 满分 {d.max_score}</summary>
        <div className="v2-inline">
          <label>维度 ID<input value={d.id} onChange={e => dimension(index, "id", e.target.value)} /></label>
          <label>维度名称<input value={d.name} onChange={e => dimension(index, "name", e.target.value)} /></label>
          <label>满分<input inputMode="decimal" value={d.max_score} onChange={e => dimension(index, "max_score", e.target.value)} /></label>
        </div>
        <label>评价说明<textarea rows={2} value={d.description} onChange={e => dimension(index, "description", e.target.value)} /></label>
        {definition.levels.map((level, levelIndex) => <label key={levelIndex}>{level.label}（{level.percent}%）判据<textarea rows={2} value={d.criteria[level.id] || ""} onChange={e => onChange({ ...definition, dimensions: definition.dimensions.map((row, i) => i === index ? { ...row, criteria: { ...row.criteria, [level.id]: e.target.value } } : row) })} /></label>)}
        <button type="button" disabled={definition.dimensions.length <= 1} onClick={() => onChange({ ...definition, dimensions: definition.dimensions.filter((_, i) => i !== index) })}>删除此维度</button>
      </details>)}
      <div className="v2-actions"><button type="button" disabled={definition.dimensions.length >= 12} onClick={() => onChange({ ...definition, dimensions: [...definition.dimensions, { id: `dim_${crypto.randomUUID().slice(0, 8)}`, name: "新维度", description: "", max_score: "1.00", criteria: Object.fromEntries(definition.levels.map(level => [level.id, ""])) }] })}>添加维度</button>
        <button type="button" onClick={onExample}>填入四维数据库教学示例</button><button type="button" onClick={onSave}>保存并校验</button></div>
    </fieldset></details>
    <div className="v2-validation" aria-live="polite">最近保存的服务端合计：<strong>{version.total_score} / 100.00</strong> · {version.publishable ? "可发布" : "请完善配置"}
      {version.field_errors?.map((error, i) => <p key={i}>{error.field}：{error.message}</p>)}
    </div>
    {version.state === "draft" && <button type="button" className="v2-primary" disabled={busy || !version.publishable} onClick={onPublish}>保存当前配置并发布</button>}
    {version.state === "published" && <p>修改标准请使用“复制为新版本”。已有任务仍使用原快照。</p>}
  </section>;
}
