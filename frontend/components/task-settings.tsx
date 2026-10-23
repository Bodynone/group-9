"use client";

import { useEffect, useState } from "react";
import { RubricPreview } from "@/components/rubric-preview";
import type { Assignment, RubricVersion } from "@/lib/grading-v2";

export function TaskSettings({ assignment, versions, busy, onSave, onPublish, onSubmit, onDirty }: {
  assignment: Assignment; versions: RubricVersion[]; busy: boolean;
  onSave: (form: FormData) => Promise<boolean>; onPublish: () => Promise<boolean>; onSubmit: () => void; onDirty: (dirty: boolean) => void;
}) {
  const [fields, setFields] = useState({ title: assignment.title, instructions: assignment.instructions, reference_text: assignment.reference_text, rubric_version_id: assignment.rubric_version_id });
  const [confirming, setConfirming] = useState(false);
  const dirty = Object.entries(fields).some(([key, value]) => value !== assignment[key as keyof typeof fields]);
  const selected = versions.find(v => v.id === fields.rubric_version_id);
  const published = assignment.state === "published";
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  return <div className="v2-detail-grid">
    <section className="v2-card" aria-label="任务设置"><h2>任务要求与评分标准</h2>
      <p>{published ? "任务已发布，要求和标准版本已冻结。" : dirty ? "有未保存修改，请先保存再预览发布。" : "任务草稿已保存，发布后才可提交学生文本。"}</p>
      <form onSubmit={e => { e.preventDefault(); void onSave(new FormData(e.currentTarget)); }}>
        <fieldset disabled={published || busy}>
          <label>任务标题<input name="title" required maxLength={200} value={fields.title} onChange={e => setFields({ ...fields, title: e.target.value })} /></label>
          <label>任务要求<textarea aria-label="任务要求" name="instructions" required rows={5} maxLength={10000} value={fields.instructions} onChange={e => setFields({ ...fields, instructions: e.target.value })} /></label>
          <label>参考说明（选填，不作为学生证据）<textarea name="reference_text" rows={3} maxLength={10000} value={fields.reference_text} onChange={e => setFields({ ...fields, reference_text: e.target.value })} /></label>
          <label>本次任务使用的评分标准<select aria-label="本次任务使用的评分标准" name="rubric_version_id" value={fields.rubric_version_id} onChange={e => setFields({ ...fields, rubric_version_id: e.target.value })}>
            {versions.filter(v => v.id === fields.rubric_version_id || (v.state === "published" && !v.archived && !v.rubric_archived)).map(v => <option key={v.id} value={v.id}>{v.definition.title} · v{v.version_no}{v.archived || v.rubric_archived ? "（已归档，保留原绑定）" : ""}</option>)}
          </select></label>
        </fieldset>
        {!published && <button type="submit" disabled={busy || !dirty}>保存任务修改</button>}
      </form>
      {published ? <button className="v2-primary" type="button" disabled={busy} onClick={onSubmit}>开始提交学生作业</button>
        : <button className="v2-primary" type="button" disabled={busy || dirty} onClick={() => setConfirming(true)}>预览并发布任务</button>}
      {confirming && <div role="dialog" aria-label="发布任务前确认" className="v2-validation"><h3>确认本次作业任务</h3>
        <p><strong>{assignment.title}</strong></p><p>{assignment.instructions}</p><p>评分标准：{selected?.definition.title} · v{selected?.version_no}</p>
        <p>发布后冻结以上要求与标准版本，不会自动调用模型。</p><div className="v2-actions">
          <button type="button" disabled={busy} onClick={() => void onPublish().then(ok => { if (ok) setConfirming(false); })}>确认发布任务</button>
          <button type="button" disabled={busy} onClick={() => setConfirming(false)}>返回检查</button></div></div>}
    </section>
    {selected && <RubricPreview definition={selected.definition} total={selected.total_score} />}
  </div>;
}
