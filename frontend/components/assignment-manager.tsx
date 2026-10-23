"use client";

import { useState } from "react";
import type { Assignment, Course, RubricVersion } from "@/lib/grading-v2";

export function AssignmentManager({ courses, assignments, versions, courseId, assignmentId, onCourse, onAssignment, onCreate, onSave, onPublish, busy }: {
  courses: Course[]; assignments: Assignment[]; versions: RubricVersion[]; courseId: string; assignmentId: string;
  onCourse: (id: string) => void; onAssignment: (id: string) => void;
  onCreate: (form: FormData) => Promise<boolean>; onSave: (form: FormData) => void; onPublish: () => void; busy: boolean;
}) {
  const [creating, setCreating] = useState(false);
  const selected = assignments.find(a => a.id === assignmentId);
  const available = versions.filter(v => v.state === "published" && !v.archived && !v.rubric_archived);
  const bound = versions.find(v => v.id === selected?.rubric_version_id);
  const versionLabel = (v: RubricVersion) => `${v.definition.title} · v${v.version_no}${v.archived || v.rubric_archived ? " · 已归档，保留原绑定" : ""}`;
  return <section className="v2-card" aria-label="课程与作业管理">
    <h2>3. 选择或新建作业任务</h2>
    <p>作业任务是老师布置的题目与要求，不是某位学生交的答案。先选择已有任务，或新建并发布，再到右侧提交学生文本。</p>
    <label>所属课程<select disabled={busy} value={courseId} onChange={e => { onCourse(e.target.value); setCreating(false); }}><option value="">请选择课程</option>{courses.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
    <label>选择本次要批改的作业任务<select disabled={busy || !courseId} value={assignmentId} onChange={e => { onAssignment(e.target.value); setCreating(false); }}><option value="">请选择已有作业任务</option>{assignments.filter(a => a.course_id === courseId).map(a => <option value={a.id} key={a.id}>{a.title} · {a.state === "published" ? "已发布" : "任务草稿"}</option>)}</select></label>
    {!selected && <p>还没有选择任务。已有任务可直接选择，不必重复创建；首次使用请展开下方新建入口。</p>}
    <details open={creating} onToggle={e => setCreating(e.currentTarget.open)} className="v2-new-assignment">
    <summary>新建作业任务</summary>
    <p>填写本次题目与要求，选择已发布标准。保存的只是老师的任务草稿，不会生成学生答案或开始批改。</p>
    <form key={courseId} onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); void onCreate(form).then(ok => { if (ok) setCreating(false); }); }}>
      <fieldset disabled={busy || !courseId}>
        <label>任务标题<input name="title" required maxLength={200} placeholder="例如：数据库实验一：分组查询报告" /></label>
        <label>任务要求<textarea name="instructions" required rows={4} maxLength={10000} placeholder="学生需要完成什么？例如说明查询、实验步骤、结果与限制。" /></label>
        <label>参考说明（选填，不作为学生证据）<textarea name="reference_text" rows={3} maxLength={10000} /></label>
        <label>本次任务使用的评分标准<select name="rubric_version_id" required><option value="">请选择可用的已发布标准</option>{available.map(v => <option value={v.id} key={v.id}>{versionLabel(v)}</option>)}</select></label>
        {!available.length && <p>暂无可用标准，请先发布量表或恢复已归档标准。</p>}
        <button type="submit" disabled={!available.length}>保存任务草稿</button>
      </fieldset>
    </form>
    </details>
    {selected && <div className="v2-assignment-summary"><h3>已选任务：{selected.title}</h3>
      <p><strong>学生需要完成：</strong>{selected.instructions}</p>
      <p><strong>评分标准：</strong>{bound ? versionLabel(bound) : selected.rubric_version_id}</p>
      <p><strong>参考说明：</strong>{selected.reference_text || "未提供"}</p>
      <p>状态：{selected.state === "published" ? "已发布，任务要求与量表绑定已冻结，可以提交学生文本" : "任务草稿，尚未开始AI批改，发布后才能提交学生文本"}</p>
      {selected.state === "draft" && <><form key={`${selected.id}:${selected.revision}`} onSubmit={e => { e.preventDefault(); onSave(new FormData(e.currentTarget)); }}><fieldset disabled={busy}>
        <label>修改任务标题<input name="title" required maxLength={200} defaultValue={selected.title} /></label>
        <label>修改任务要求<textarea name="instructions" required defaultValue={selected.instructions} /></label>
        <label>修改参考说明<textarea name="reference_text" defaultValue={selected.reference_text} /></label>
        <label>修改评分标准<select name="rubric_version_id" defaultValue={selected.rubric_version_id}>{versions.filter(v => available.includes(v) || v.id === selected.rubric_version_id).map(v => <option key={v.id} value={v.id}>{versionLabel(v)}</option>)}</select></label>
        <button type="submit">保存任务修改</button></fieldset></form>
        <p>先保存修改，再发布任务。发布会冻结任务要求及所选标准，不会自动调用模型。</p>
        <button type="button" className="v2-primary" disabled={busy} onClick={onPublish}>发布任务，允许提交学生文本</button></>}
    </div>}
  </section>;
}
