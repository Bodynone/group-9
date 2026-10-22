"use client";

import type { Assignment, Course, RubricVersion } from "@/lib/grading-v2";

export function AssignmentManager({ courses, assignments, versions, courseId, assignmentId, onCourse, onAssignment, onCreate, onSave, onPublish, busy }: {
  courses: Course[]; assignments: Assignment[]; versions: RubricVersion[]; courseId: string; assignmentId: string;
  onCourse: (id: string) => void; onAssignment: (id: string) => void;
  onCreate: (form: FormData) => void; onSave: (form: FormData) => void; onPublish: () => void; busy: boolean;
}) {
  const selected = assignments.find(a => a.id === assignmentId);
  return <section className="v2-card" aria-label="课程与作业管理">
    <h2>3. 建立并发布作业</h2>
    <label>所属课程<select value={courseId} onChange={e => onCourse(e.target.value)}><option value="">请选择课程</option>{courses.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
    <form onSubmit={e => { e.preventDefault(); onCreate(new FormData(e.currentTarget)); }}>
      <fieldset disabled={busy || !courseId}>
        <label>作业标题<input name="title" required maxLength={200} /></label>
        <label>任务要求<textarea name="instructions" required rows={4} maxLength={10000} /></label>
        <label>参考说明（选填，不作为学生证据）<textarea name="reference_text" rows={3} maxLength={10000} /></label>
        <label>绑定量表版本<select name="rubric_version_id" required><option value="">请选择已发布标准</option>{versions.filter(v => v.state === "published").map(v => <option value={v.id} key={v.id}>{v.definition.title} · v{v.version_no}</option>)}</select></label>
        <button type="submit">创建作业草稿</button>
      </fieldset>
    </form>
    <label>当前作业<select value={assignmentId} onChange={e => onAssignment(e.target.value)}><option value="">请选择作业</option>{assignments.filter(a => !courseId || a.course_id === courseId).map(a => <option value={a.id} key={a.id}>{a.title} · {a.state === "published" ? "已发布" : "草稿"}</option>)}</select></label>
    {selected && <div><p>{selected.instructions}</p><p>状态：{selected.state === "published" ? "已发布，任务要求与量表绑定已冻结" : "草稿，不能提交评分"}</p>
      {selected.state === "draft" && <><form key={`${selected.id}:${selected.revision}`} onSubmit={e => { e.preventDefault(); onSave(new FormData(e.currentTarget)); }}><fieldset disabled={busy}>
        <label>修改草稿标题<input name="title" required defaultValue={selected.title} /></label>
        <label>修改任务要求<textarea name="instructions" required defaultValue={selected.instructions} /></label>
        <label>修改参考说明<textarea name="reference_text" defaultValue={selected.reference_text} /></label>
        <label>修改绑定版本<select name="rubric_version_id" defaultValue={selected.rubric_version_id}>{versions.map(v => <option key={v.id} value={v.id}>{v.definition.title} · v{v.version_no} · {v.state}</option>)}</select></label>
        <button type="submit">保存作业草稿</button></fieldset></form><button type="button" className="v2-primary" disabled={busy} onClick={onPublish}>发布当前作业</button></>}
    </div>}
  </section>;
}
