"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AssignmentManager } from "@/components/assignment-manager";
import { RubricEditor } from "@/components/rubric-editor";
import { databaseExample, v2, versionFields, type AnalyticsV2, type Assignment, type BatchV2, type Course, type Definition, type Evidence, type Review, type RubricVersion, type TaskV2 } from "@/lib/grading-v2";

const statusName: Record<string, string> = { queued: "排队中", running: "正在批改", pending_review: "待教师复核", confirmed: "已确认", failed: "失败", completed: "草稿处理结束", partial_failed: "部分失败" };

function Chart({ data }: { data: AnalyticsV2 }) {
  const dimensions = data.dimensions;
  if (data.analyzed === 0) return <p>当前统计口径下暂无可分析结果。</p>;
  if (dimensions.length <= 2) return <div>{dimensions.map(d => <label key={d.id}>{d.name} · {d.scoring_rate}%<meter min={0} max={100} value={Number(d.scoring_rate)} /></label>)}</div>;
  // Numeric conversion here positions SVG marks from server-computed rates;
  // component grades and averages are never calculated in the browser.
  const point = (i: number, rate: number) => {
    const angle = (Math.PI * 2 * i / dimensions.length) - Math.PI / 2;
    return [180 + Math.cos(angle) * 110 * rate, 160 + Math.sin(angle) * 110 * rate];
  };
  return <svg className="v2-chart" viewBox="0 0 360 330" role="img" aria-label={`${dimensions.length}维平均得分率雷达图`}>
    {[0.25, 0.5, 0.75, 1].map(rate => <polygon key={rate} points={dimensions.map((_, i) => point(i, rate).join(",")).join(" ")} fill="none" stroke="#d7e1d0" />)}
    {dimensions.map((d, i) => { const p = point(i, 1.26); const end = point(i, 1); return <g key={d.id}><line x1={180} y1={160} x2={end[0]} y2={end[1]} stroke="#e3e8ee" /><text x={p[0]} y={p[1]} textAnchor="middle" fontSize={10}>{d.name}</text></g>; })}
    <polygon points={dimensions.map((d, i) => point(i, Number(d.scoring_rate) / 100).join(",")).join(" ")} fill="#8aab6344" stroke="#648740" strokeWidth={2} />
  </svg>;
}

export function CourseWorkspace() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [versions, setVersions] = useState<RubricVersion[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [batches, setBatches] = useState<Pick<BatchV2, "id" | "name" | "assignment_id">[]>([]);
  const [courseId, setCourseId] = useState("");
  const [assignmentId, setAssignmentId] = useState("");
  const [version, setVersion] = useState<RubricVersion | null>(null);
  const [definition, setDefinition] = useState<Definition | null>(null);
  const [task, setTask] = useState<TaskV2 | null>(null);
  const [review, setReview] = useState<Review[]>([]);
  const [dirty, setDirty] = useState(false);
  const [batch, setBatch] = useState<BatchV2 | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsV2 | null>(null);
  const [basis, setBasis] = useState("confirmed");
  const [source, setSource] = useState("");
  const [label, setLabel] = useState("匿名提交-01");
  const [files, setFiles] = useState<{ filename: string; submission_label: string; text: string }[]>([]);
  const [batchName, setBatchName] = useState("本次作业");
  const [highlight, setHighlight] = useState<Evidence | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pendingKeys = useRef(new Map<string, string>());

  const reload = useCallback(async () => {
    const [c, r, a, b] = await Promise.all([
      v2<{ items: Course[] }>("courses?limit=100"), v2<{ items: { versions: RubricVersion[] }[] }>("rubrics?limit=100"),
      v2<{ items: Assignment[] }>("assignments?limit=100"), v2<{ items: BatchV2[] }>("batches?limit=100"),
    ]);
    setCourses(c.items); setVersions(r.items.flatMap(row => row.versions)); setAssignments(a.items); setBatches(b.items);
  }, []);

  const loadTask = useCallback((value: TaskV2) => {
    setTask(value); setReview(value.review?.dimensions || []); setDirty(false); setHighlight(null);
    if (value.assignment_snapshot.id) setAssignmentId(value.assignment_snapshot.id);
    if (value.assignment_snapshot.course_id) setCourseId(value.assignment_snapshot.course_id);
    try { localStorage.setItem("yuejian.v2-task", value.id); } catch { /* Browser storage is optional. */ }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      reload().catch(e => { if (!cancelled) setError(String(e.message)); });
      try {
        const id = new URLSearchParams(window.location.search).get("task") || localStorage.getItem("yuejian.v2-task");
        if (id) v2<TaskV2>(`tasks/${id}`).then(value => { if (!cancelled) loadTask(value); }).catch(() => {});
      } catch { /* Browser storage is optional. */ }
    }, 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [reload, loadTask]);

  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    const id = task.id;
    const timer = setInterval(() => v2<TaskV2>(`tasks/${id}`).then(loadTask).catch(e => setError(e.message)), 1000);
    return () => clearInterval(timer);
  }, [task?.id, task?.status, task, loadTask]);

  useEffect(() => {
    if (!batch) return;
    let cancelled = false;
    const id = batch.id;
    v2<AnalyticsV2>(`batches/${id}/analytics?basis=${basis}`).then(value => { if (!cancelled) setAnalytics(value); }).catch(e => setError(e.message));
    if (!["queued", "running"].includes(batch.status)) return () => { cancelled = true; };
    const timer = setInterval(() => v2<BatchV2>(`batches/${id}`).then(value => { if (!cancelled) setBatch(value); }).catch(e => setError(e.message)), 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [batch, basis]);

  async function act(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "请求失败，请重试"); } finally { setBusy(false); }
  }
  async function submitOnce<T>(path: string, body?: unknown): Promise<T> {
    const signature = path + JSON.stringify(body);
    const key = pendingKeys.current.get(signature) || crypto.randomUUID();
    pendingKeys.current.set(signature, key);
    const result = await v2<T>(path, "POST", body, key);
    pendingKeys.current.delete(signature);
    return result;
  }
  async function selectVersion(id: string) {
    if (!id) { setVersion(null); setDefinition(null); return; }
    const value = await v2<RubricVersion>(`rubric-versions/${id}`);
    setVersion(value); setDefinition(value.definition);
  }
  async function saveVersion(publish = false) {
    if (!version || !definition) return;
    let saved = await v2<RubricVersion>(`rubric-versions/${version.id}`, "PATCH", { expected_revision: version.revision, definition });
    setVersion(saved); setDefinition(saved.definition);
    if (publish) {
      saved = await v2<RubricVersion>(`rubric-versions/${version.id}/publish`, "POST", { expected_revision: saved.revision });
      setVersion(saved); setNotice("量表已发布，已有任务快照不会随新版本变化。");
    }
    await reload();
  }
  function editReview(index: number, fields: Partial<Review>) {
    setReview(review.map((row, i) => i === index ? { ...row, ...fields, reviewed: fields.reviewed ?? false } : row));
    setDirty(true);
  }
  const currentAssignment = assignments.find(a => a.id === assignmentId);
  const canSubmit = currentAssignment?.state === "published" && !busy;
  const taskReadOnly = task?.status !== "pending_review" || busy;
  const text = Array.from(task?.text || "");

  return <main className="v2-main">
    <div className="v2-intro"><span>教师配置 · 跨课程文本作业</span><h1>用课程自己的标准，逐项批改。</h1><p>先配置和发布标准，再提交匿名文本。AI 生成建议，教师确认后才进入成绩统计。</p></div>
    <div role="status" className="v2-notice">{notice}</div>{error && <div role="alert" className="v2-error">{error}</div>}
    <div className="v2-columns">
      <div>
        <section className="v2-card"><h2>1. 建立课程与量表草稿</h2>
          <form onSubmit={e => { e.preventDefault(); const form = e.currentTarget; const name = String(new FormData(form).get("name")); void act(async () => { const value = await v2<Course>("courses", "POST", { name }); await reload(); setCourseId(value.id); form.reset(); }); }}>
            <label>课程名称<input name="name" required maxLength={200} placeholder="例如：数据库原理" /></label><button disabled={busy} type="submit">创建课程</button>
          </form>
          <form onSubmit={e => { e.preventDefault(); const title = String(new FormData(e.currentTarget).get("title")); void act(async () => { const value = await v2<{ draft: RubricVersion }>("rubrics", "POST", { title }); setVersion(value.draft); setDefinition(value.draft.definition); await reload(); }); }}>
            <label>新量表名称<input name="title" required maxLength={200} placeholder="例如：数据库实验报告" /></label><button disabled={busy} type="submit">新建评分量表</button>
          </form>
          <label>查看量表版本<select value={version?.id || ""} onChange={e => void act(() => selectVersion(e.target.value))}><option value="">请选择量表</option>{versions.map(v => <option key={v.id} value={v.id}>{v.definition.title} · v{v.version_no} · {v.state === "published" ? "已发布" : "草稿"}</option>)}</select></label>
          {version?.state === "published" && <button disabled={busy} type="button" onClick={() => void act(async () => { const value = await v2<RubricVersion>(`rubrics/${version.rubric_id}/versions`, "POST", { source_version_id: version.id }); setVersion(value); setDefinition(value.definition); await reload(); })}>复制为新版本</button>}
        </section>
        {version && definition && <RubricEditor version={version} definition={definition} onChange={setDefinition} busy={busy} onSave={() => void act(() => saveVersion())} onPublish={() => void act(() => saveVersion(true))} onExample={() => { setDefinition(structuredClone(databaseExample)); setNotice("已填入示例，尚未保存。请按课程要求修改，并由教师确认标准。"); }} />}
        <AssignmentManager courses={courses} assignments={assignments} versions={versions} courseId={courseId} assignmentId={assignmentId} onCourse={id => { setCourseId(id); setAssignmentId(""); }} onAssignment={setAssignmentId} busy={busy}
          onCreate={form => void act(async () => { const value = await v2<Assignment>("assignments", "POST", { course_id: courseId, title: form.get("title"), instructions: form.get("instructions"), reference_text: form.get("reference_text"), rubric_version_id: form.get("rubric_version_id") }); await reload(); setAssignmentId(value.id); })}
          onSave={form => void act(async () => { if (!currentAssignment) return; await v2(`assignments/${assignmentId}`, "PATCH", { expected_revision: currentAssignment.revision, title: form.get("title"), instructions: form.get("instructions"), reference_text: form.get("reference_text"), rubric_version_id: form.get("rubric_version_id") }); await reload(); setNotice("作业草稿已保存，尚未发布。"); })}
          onPublish={() => void act(async () => { if (!currentAssignment) return; await v2(`assignments/${assignmentId}/publish`, "POST", { expected_revision: currentAssignment.revision }); await reload(); setNotice("作业已发布，可以提交单份或批量文本。"); })} />
      </div>
      <div>
        <section className="v2-card"><h2>4. 提交匿名文本</h2><p>当前作业：{currentAssignment?.title || "请先在左侧选择已发布作业"}</p>
          <label>匿名提交号<input value={label} onChange={e => setLabel(e.target.value)} maxLength={200} /></label>
          <label>作业正文<textarea rows={9} value={source} onChange={e => setSource(e.target.value)} placeholder="粘贴文本前请去除姓名、学号等身份信息" /></label>
          <button className="v2-primary" disabled={!canSubmit || !source.trim()} onClick={() => void act(async () => { const value = await submitOnce<TaskV2>("tasks", { assignment_id: assignmentId, submission_label: label, text: source }); loadTask(value); })}>按当前作业标准生成草稿</button>
          <h3>批量 TXT / MD</h3>
          <label>批次名称<input value={batchName} onChange={e => setBatchName(e.target.value)} /></label>
          <label>选择多个文本文件<input type="file" multiple accept=".txt,.md" disabled={busy} onChange={e => {
            const selected = Array.from(e.target.files || []);
            setFiles([]);
            void act(async () => {
              if (selected.length > 40) throw new Error("每批最多40份文本");
              const parsed = await Promise.all(selected.map(async file => {
                if (!/\.(txt|md)$/i.test(file.name) || file.size > 200000) throw new Error(`${file.name}：仅支持200000字节以内的TXT/MD`);
                const body = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
                if (!body.trim() || Array.from(body).length > 50000) throw new Error(`${file.name}：正文须为1至50000字符`);
                return { filename: file.name, submission_label: file.name, text: body };
              })); setFiles(parsed); setNotice(`已解析${parsed.length}份文件，保留原始换行和字符。`);
            });
          }} /></label><p>已选 {files.length} 份</p>
          <button disabled={!canSubmit || !files.length} onClick={() => void act(async () => { const value = await submitOnce<BatchV2>("batches", { assignment_id: assignmentId, name: batchName, files }); setBatch(value); await reload(); })}>创建批量任务</button>
        </section>
        {task && <section className="v2-card" aria-label="动态评分与复核"><div className="v2-section-title"><h2>5. 逐项复核 · {task.submission_label}</h2><span>{statusName[task.status]}</span></div>
          <p>{task.assignment_snapshot.title} · {task.rubric_snapshot.dimensions.length} 个维度 · 模型调用 {task.model_calls} 次 · 修正 {task.repair_rounds} 轮</p>
          {task.security_detail && <p className="v2-error">{task.security_detail}</p>}
          {task.error && <p className="v2-error">{task.error.code}：{task.error.message}</p>}
          {task.status === "failed" && <div className="v2-actions"><button disabled={busy} onClick={() => void act(async () => { loadTask(await submitOnce<TaskV2>(`tasks/${task.id}/retry`)); if (batch) setBatch(await v2<BatchV2>(`batches/${batch.id}`)); })}>重试本份</button><button disabled={busy} onClick={() => void act(async () => loadTask(await v2<TaskV2>(`tasks/${task.id}/manual`, "POST")))}>转人工批改</button></div>}
          <details><summary>冻结标准与任务要求</summary><p>{task.assignment_snapshot.instructions}</p><p>参考说明：{task.assignment_snapshot.reference_text || "未提供"}</p><p>量表版本：{task.rubric_version_id}</p><p className="v2-hash">原文 SHA-256：{task.input_version}<br />量表 SHA-256：{task.rubric_hash}<br />上下文 SHA-256：{task.context_hash}</p></details>
          <details open={!!highlight}><summary>学生原文{highlight ? ` · 已定位第${highlight.paragraph}段` : ""}</summary><div className="v2-source" tabIndex={0}>{highlight ? <>{text.slice(0, highlight.start).join("")}<mark>{text.slice(highlight.start, highlight.end).join("")}</mark>{text.slice(highlight.end).join("")}</> : task.text}</div></details>
          {review.map((row, index) => {
            const dimension = task.rubric_snapshot.dimensions.find(d => d.id === row.dimension_id);
            const draft = task.draft?.dimensions.find(d => d.dimension_id === row.dimension_id);
            return <fieldset className="v2-review-row" key={row.dimension_id} disabled={busy}>
              <legend>{dimension?.name} · 满分 {dimension?.max_score}</legend>
              <label>评分档位<select disabled={taskReadOnly} value={row.level_id || ""} onChange={e => editReview(index, { level_id: e.target.value })}><option value="">请选择档位</option>{task.rubric_snapshot.levels.map(level => <option value={level.id} key={level.id}>{level.label}（{level.percent}%）：{dimension?.criteria[level.id]}</option>)}</select></label>
              <label>复核理由<textarea disabled={taskReadOnly} rows={3} value={row.reason} onChange={e => editReview(index, { reason: e.target.value })} /></label>
              <label className="v2-checkbox"><input type="checkbox" disabled={taskReadOnly} checked={row.reviewed} onChange={e => editReview(index, { reviewed: e.target.checked })} />已核查本维档位、理由与证据</label>
              <p>最近保存得分：{row.score ?? "尚未计算"}{dirty ? "（有修改，保存后由后端重算）" : ""}</p>
              {draft?.review_note && <p>待核查：{draft.review_note}</p>}
              {draft?.evidence.map((ref, i) => <button type="button" disabled={false} key={i} className="v2-quote" onClick={() => setHighlight(ref)}>定位证据：「{ref.quote}」</button>)}
            </fieldset>;
          })}
          {task.review && <p className="v2-total">最近保存总分：<strong>{task.review.total ?? "待计算"}</strong> / 100.00</p>}
          {task.status === "pending_review" && <div className="v2-actions"><button disabled={busy} onClick={() => void act(async () => { loadTask(await v2<TaskV2>(`tasks/${task.id}/review`, "PATCH", { ...versionFields(task), dimensions: review.map(({ dimension_id, level_id, reason, reviewed }) => ({ dimension_id, level_id, reason, reviewed })) })); setNotice("复核已保存，分值由后端重算。"); })}>保存复核并重算</button>
            <button className="v2-primary" disabled={busy || dirty || !review.length || review.some(row => !row.reviewed)} onClick={() => void act(async () => { loadTask(await v2<TaskV2>(`tasks/${task.id}/confirm`, "POST", versionFields(task))); if (batch) setBatch(await v2<BatchV2>(`batches/${batch.id}`)); setNotice("教师已确认，已写入不可变记录。"); })}>确认并归档</button></div>}
          {task.status === "confirmed" && <a href={`/api/v2/tasks/${task.id}/export`} download>下载确认记录 JSON</a>}
        </section>}
        <section className="v2-card"><h2>6. 同次作业的进度与学情</h2>
          <label>历史批次<select value={batch?.id || ""} onChange={e => void act(async () => { if (e.target.value) setBatch(await v2<BatchV2>(`batches/${e.target.value}`)); })}><option value="">请选择批次</option>{batches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
          {batch && <><p>{statusName[batch.status]} · 共 {batch.total_count} 份 · 处理结束 {batch.finished_count} · 教师确认 {batch.confirmed_count} · 失败 {batch.failed_count}</p>
            <div className="v2-table-wrap"><table><thead><tr><th>匿名提交号</th><th>状态</th><th>最近保存分数</th><th>操作</th></tr></thead><tbody>{batch.items.map(item => <tr key={item.task_id}><td>{item.submission_label}</td><td>{statusName[item.status]}</td><td>{item.total ?? "—"}</td><td><button disabled={busy} onClick={() => void act(async () => loadTask(await v2<TaskV2>(`tasks/${item.task_id}`)))}>打开复核</button></td></tr>)}</tbody></table></div>
            <label>统计口径<select value={basis} onChange={e => setBasis(e.target.value)}><option value="confirmed">仅教师确认结果</option><option value="working">临时预览（含未确认结果）</option></select></label>
            {analytics && <><p className={analytics.provisional ? "v2-error" : "v2-validation"}>{analytics.provisional ? "临时统计，包含未确认草稿或复核" : "确认统计，只使用不可变确认记录"} · 已分析 {analytics.analyzed} / {analytics.submitted} · 排除 {analytics.excluded} · 均分 {analytics.average_score ?? "暂无"}</p><Chart data={analytics} />
              {analytics.dimensions.map(d => <p key={d.id}>{d.name}：平均 {d.average_score ?? "暂无"} / {d.max_score}，得分率 {d.scoring_rate ?? "暂无"}%</p>)}
              {analytics.rows.map(row => <p key={row.task_id}>{row.submission_label} · 来源：{row.source === "record" ? "确认记录" : row.source === "review" ? "未确认复核" : "AI 草稿"} · {row.total}</p>)}
              <h3>常见薄弱维度（规则统计）</h3>{analytics.common_weaknesses.map(w => <details key={w.dimension_id}><summary>{w.name} · {w.affected_count} 份</summary>{w.reasons.map((r, i) => <p key={i}>{r.submission_label}：{r.reason}</p>)}</details>)}
            </>}
            {batch.confirmed_count > 0 ? <a href={`/api/v2/batches/${batch.id}/export-csv`} download>导出已确认 {batch.confirmed_count} 份 CSV（其他提交不导出）</a> : <p>暂无确认成绩，完成教师复核后可导出 CSV。</p>}
          </>}
        </section>
      </div>
    </div>
  </main>;
}
