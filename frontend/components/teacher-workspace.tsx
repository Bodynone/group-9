"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { AssignmentDetail, type DetailStep } from "@/components/assignment-detail";
import { StandardsLibrary } from "@/components/standards-library";
import { RubricPreview } from "@/components/rubric-preview";
import { allV2 } from "@/lib/workspace-navigation";
import { v2, type Assignment, type Course, type RubricVersion, type SubmissionSummary, type TaskV2 } from "@/lib/grading-v2";

type Page = "assignments" | "standards" | "detail";
const emptyForm = { course_id: "", title: "", instructions: "", reference_text: "", rubric_version_id: "" };
const stepValue = (value: string | null): DetailStep => value === "settings" || value === "results" ? value : "grading";

export function TeacherWorkspace() {
  const [page, setPage] = useState<Page>("assignments");
  const [courses, setCourses] = useState<Course[]>([]);
  const [versions, setVersions] = useState<RubricVersion[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [records, setRecords] = useState<SubmissionSummary[]>([]);
  const [courseId, setCourseId] = useState("");
  const [assignmentId, setAssignmentId] = useState("");
  const [taskId, setTaskId] = useState<string>();
  const [initialStep, setInitialStep] = useState<DetailStep>("grading");
  const [focusVersion, setFocusVersion] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty = useRef(false);
  const formDirty = useRef(false);
  const generation = useRef(0);
  const navigation = useRef(0);
  const changed = useCallback((value: boolean) => { dirty.current = value; }, []);
  const reload = useCallback(async () => {
    const token = ++generation.current;
    const [c, r, a, t] = await Promise.all([allV2<Course>("courses"), allV2<{ versions: RubricVersion[] }>("rubrics?include_archived=true"), allV2<Assignment>("assignments"), allV2<SubmissionSummary>("tasks")]);
    if (token === generation.current) { setCourses(c); setVersions(r.flatMap(item => item.versions)); setAssignments(a); setRecords(t); }
  }, []);
  function canLeave() { return !(dirty.current || formDirty.current) || window.confirm("有未保存的输入或待提交文本，离开将放弃这些修改。继续？"); }
  function address(query: URLSearchParams, push = true) {
    const url = `${window.location.pathname}${query.size ? "?" + query.toString() : ""}`;
    if (push) window.history.pushState(null, "", url); else window.history.replaceState(null, "", url);
  }
  const routeDetail = useCallback((step: DetailStep, id?: string) => {
    const query = new URLSearchParams(window.location.search); query.set("step", step);
    if (id) query.set("task", id); else query.delete("task");
    window.history.replaceState(null, "", `${window.location.pathname}?${query.toString()}`);
  }, []);
  useEffect(() => {
    let cancelled = false;
    async function location() {
      const ticket = ++navigation.current;
      const params = new URLSearchParams(window.location.search), id = params.get("task"), owner = params.get("assignment");
      dirty.current = false; formDirty.current = false; setCreating(false); setForm(emptyForm);
      if (params.get("view") === "standards") { setFocusVersion(params.get("version") || undefined); setPage("standards"); return; }
      if (id) {
        try {
          const value = await v2<TaskV2>(`tasks/${encodeURIComponent(id)}`);
          if (cancelled || ticket !== navigation.current) return;
          if (!value.assignment_snapshot.id) { window.location.replace(`/legacy?task=${encodeURIComponent(id)}`); return; }
          if (owner && owner !== value.assignment_snapshot.id) throw new Error("链接中的作业任务与提交记录不匹配，请从作业列表进入。");
          setAssignmentId(value.assignment_snapshot.id); setTaskId(id); setInitialStep(stepValue(params.get("step"))); setPage("detail");
        } catch (e) { if (!cancelled && ticket === navigation.current) { setError(e instanceof Error ? e.message : "无法打开历史提交"); setPage("assignments"); } }
      } else if (owner) { setAssignmentId(owner); setTaskId(undefined); setInitialStep(stepValue(params.get("step"))); setPage("detail"); }
      else setPage("assignments");
    }
    const timer = setTimeout(() => { reload().catch(e => { if (!cancelled) setError(e.message); }).finally(() => { if (!cancelled) setLoading(false); }); void location(); }, 0);
    const back = () => { if (!canLeave()) { window.history.go(1); return; } void location(); };
    const unload = (event: BeforeUnloadEvent) => { if (dirty.current || formDirty.current) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("popstate", back); window.addEventListener("beforeunload", unload);
    return () => { cancelled = true; clearTimeout(timer); window.removeEventListener("popstate", back); window.removeEventListener("beforeunload", unload); };
  }, [reload]);
  function navigate(next: "assignments" | "standards", version?: string) {
    if (!canLeave()) return false;
    navigation.current++; dirty.current = false; formDirty.current = false; setCreating(false); setForm(emptyForm); setError(""); setNotice(""); setFocusVersion(version); setPage(next);
    const query = new URLSearchParams(); if (next === "standards") query.set("view", "standards"); if (version) query.set("version", version); address(query); if (next === "assignments") void reload().catch(e => setError(e.message)); return true;
  }
  function openAssignment(assignment: Assignment) {
    if (!canLeave()) return;
    navigation.current++; dirty.current = false; formDirty.current = false; setCreating(false); setTaskId(undefined); setAssignmentId(assignment.id); setPage("detail"); setError("");
    const step = assignment.state === "published" ? "grading" : "settings"; setInitialStep(step);
    address(new URLSearchParams({ assignment: assignment.id, step }));
  }
  const activeVersions = versions.filter(v => v.state === "published" && !v.archived && !v.rubric_archived);
  const preview = versions.find(v => v.id === form.rubric_version_id);
  const currentAssignment = assignments.find(a => a.id === assignmentId);
  const useVersion = (id?: string) => {
    if (navigate("assignments")) { setForm({ ...emptyForm, course_id: courseId, rubric_version_id: id || "" }); setCreating(true); }
  };
  return <div className="v2-shell">
    <header className="v2-header"><Link href="/" onClick={e => { e.preventDefault(); navigate("assignments"); }}>阅见 / 教师工作台</Link>
      <nav aria-label="主导航"><button aria-current={page !== "standards" ? "page" : undefined} onClick={() => navigate("assignments")}>作业任务</button><button aria-current={page === "standards" ? "page" : undefined} onClick={() => navigate("standards")}>评分标准库</button></nav>
      <details className="v2-legacy-menu"><summary>历史兼容入口</summary><Link href="/legacy" onClick={e => { if (!canLeave()) e.preventDefault(); }}>固定量表工作台</Link><p>保留旧单份、批量和学情，使用原固定标准与历史数据。</p></details>
    </header>
    <main className="v2-main">
      {error && <p role="alert" className="v2-error">{error}</p>}<div role="status" className="v2-notice">{notice}</div>
      {loading ? <p role="status">正在读取课程和作业任务…</p> : page === "standards" ? <StandardsLibrary versions={versions} reload={reload} onDirty={changed} onTasks={useVersion} initialVersion={focusVersion} />
        : page === "detail" ? currentAssignment ? <><button className="v2-back" onClick={() => navigate("assignments")}>返回作业任务列表</button>
          <AssignmentDetail key={`${assignmentId}:${taskId || ""}:${initialStep}`} assignment={currentAssignment} versions={versions} initialTaskId={taskId} initialStep={initialStep} onDirty={changed} onChanged={reload} onRoute={routeDetail} /></>
          : <section className="v2-card"><h1>找不到这项作业任务</h1><p>历史记录仍保留，请返回列表选择任务，或从历史兼容入口打开旧版任务。</p><button onClick={() => navigate("assignments")}>返回作业任务列表</button></section>
        : <>
          <div className="v2-page-heading"><div><h1>作业任务</h1><p>选择老师布置的一次作业，在任务内完成学生提交、复核确认和结果查看。</p></div><button className="v2-primary" disabled={busy} onClick={() => { if (creating && !canLeave()) return; formDirty.current = false; setCreating(!creating); setForm({ ...emptyForm, course_id: courseId }); }}>新建作业任务</button></div>
          <section className="v2-card v2-course-filter"><label>按课程筛选<select value={courseId} disabled={busy} onChange={e => setCourseId(e.target.value)}><option value="">全部课程</option>{courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
            <details><summary>建立新课程</summary><form onSubmit={e => { e.preventDefault(); const element = e.currentTarget, name = String(new FormData(element).get("name")); setBusy(true); void v2<Course>("courses", "POST", { name }).then(async value => { await reload(); setCourseId(value.id); element.reset(); setNotice("课程已建立，可以新建作业任务。"); }).catch(e => setError(e.message)).finally(() => setBusy(false)); }}><label>课程名称<input name="name" required maxLength={200} placeholder="例如：数据库原理" /></label><button disabled={busy}>创建课程</button></form></details>
          </section>
          {creating && <section className="v2-card" aria-label="新建作业任务"><h2>设置本次作业任务</h2><p>先保存老师的任务草稿，检查后发布，再提交学生答案。此步骤不调用模型。</p>
            <div className="v2-detail-grid"><form onSubmit={e => { e.preventDefault(); setBusy(true); setError(""); void v2<Assignment>("assignments", "POST", form).then(async item => { await reload(); formDirty.current = false; setForm(emptyForm); setCreating(false); openAssignment(item); }).catch(e => setError(e.message)).finally(() => setBusy(false)); }}>
              <fieldset disabled={busy}>
                <label>所属课程<select aria-label="所属课程" required value={form.course_id} onChange={e => { setForm({ ...form, course_id: e.target.value }); formDirty.current = true; }}><option value="">请选择课程</option>{courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
                <label>任务标题<input required maxLength={200} value={form.title} onChange={e => { setForm({ ...form, title: e.target.value }); formDirty.current = true; }} placeholder="例如：数据库实验一：分组查询报告" /></label>
                <label>任务要求<textarea aria-label="任务要求" required rows={4} maxLength={10000} value={form.instructions} onChange={e => { setForm({ ...form, instructions: e.target.value }); formDirty.current = true; }} placeholder="学生需要完成什么？" /></label>
                <label>参考说明（选填，不作为学生证据）<textarea rows={3} maxLength={10000} value={form.reference_text} onChange={e => { setForm({ ...form, reference_text: e.target.value }); formDirty.current = true; }} /></label>
                <label>本次任务使用的评分标准<select aria-label="本次任务使用的评分标准" required value={form.rubric_version_id} onChange={e => { setForm({ ...form, rubric_version_id: e.target.value }); formDirty.current = true; }}><option value="">请选择已发布标准</option>{activeVersions.map(v => <option key={v.id} value={v.id}>{v.definition.title} · v{v.version_no}</option>)}</select></label>
                {!activeVersions.length && <p>暂无可用标准。请先到评分标准库创建并发布，或恢复归档标准。</p>}
                <button className="v2-primary" disabled={!activeVersions.length}>保存任务草稿</button>
              </fieldset>
            </form>{preview ? <RubricPreview definition={preview.definition} total={preview.total_score} /> : <p>选择一份评分标准，即可预览维度、满分和判据。<button onClick={() => navigate("standards")}>前往评分标准库</button></p>}</div>
          </section>}
          <section className="v2-card" aria-label="作业任务列表"><div className="v2-table-wrap"><table><thead><tr><th>作业任务</th><th>课程</th><th>绑定标准</th><th>状态</th><th>记录</th><th>操作</th></tr></thead><tbody>
            {assignments.filter(a => !courseId || a.course_id === courseId).map(a => { const bound = versions.find(v => v.id === a.rubric_version_id); return <tr key={a.id}><td>{a.title}</td><td>{courses.find(c => c.id === a.course_id)?.name}</td><td>{bound?.definition.title || a.rubric_version_id} · v{bound?.version_no ?? "历史版本"}</td><td>{a.state === "published" ? "已发布" : "任务草稿"}</td><td>{records.filter(r => r.assignment_id === a.id && !r.replaced_by).length} 条</td><td><button onClick={() => openAssignment(a)}>{a.state === "published" ? "进入批改" : "继续设置"}</button></td></tr>; })}
          </tbody></table></div>{!assignments.some(a => !courseId || a.course_id === courseId) && <div className="v2-empty"><h2>这里还没有作业任务</h2><p>先建立课程，在评分标准库准备标准，然后新建这次作业任务。</p><button onClick={() => navigate("standards")}>准备评分标准</button></div>}</section>
        </>}
    </main>
  </div>;
}
