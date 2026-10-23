"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { TaskSettings } from "@/components/task-settings";
import { LearningSettings } from "@/components/learning-settings";
import { LearningReview } from "@/components/learning-review";
import { LearningResults } from "@/components/learning-results";
import { LearningEvaluation } from "@/components/learning-evaluation";
import { v2, versionFields, type AnalyticsV2, type Assignment, type BatchV2, type Evidence, type Review, type RubricVersion, type SubmissionSummary, type TaskV2 } from "@/lib/grading-v2";
import { allV2 } from "@/lib/workspace-navigation";

export type DetailStep = "settings" | "grading" | "results" | "evaluation";
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


export function AssignmentDetail({ assignment: initialAssignment, versions, initialTaskId, initialStep, onDirty, onChanged, onRoute }: {
  assignment: Assignment; versions: RubricVersion[]; initialTaskId?: string; initialStep: DetailStep;
  onDirty: (value: boolean) => void; onChanged: () => Promise<void>; onRoute: (step: DetailStep, taskId?: string) => void;
}) {
  const [assignment, setAssignment] = useState(initialAssignment);
  const [step, setStep] = useState<DetailStep>(initialStep);
  const [task, setTask] = useState<TaskV2 | null>(null);
  const [review, setReview] = useState<Review[]>([]);
  const [dirty, setDirty] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [learningSettingsDirty, setLearningSettingsDirty] = useState(false);
  const [learningReviewDirty, setLearningReviewDirty] = useState(false);
  const [evaluationDirty, setEvaluationDirty] = useState(false);
  const [records, setRecords] = useState<SubmissionSummary[]>([]);
  const [showReplaced, setShowReplaced] = useState(false);
  const [batches, setBatches] = useState<Pick<BatchV2, "id" | "name" | "assignment_id">[]>([]);
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
  const mounted = useRef(true);
  const openGeneration = useRef(0);
  const batchGeneration = useRef(0);
  const evidenceMark = useRef<HTMLElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const pendingKeys = useRef(new Map<string, string>());
  const settingsChanged = useCallback((value: boolean) => setSettingsDirty(value), []);
  const learningSettingsChanged = useCallback((value: boolean) => setLearningSettingsDirty(value), []);
  const learningReviewChanged = useCallback((value: boolean) => setLearningReviewDirty(value), []);
  const evaluationChanged = useCallback((value: boolean) => setEvaluationDirty(value), []);
  useEffect(() => { if (highlight) evidenceMark.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [highlight]);
  useEffect(() => { onDirty(dirty || settingsDirty || learningSettingsDirty || learningReviewDirty || evaluationDirty || !!source.trim() || files.length > 0); return () => onDirty(false); }, [dirty, settingsDirty, learningSettingsDirty, learningReviewDirty, evaluationDirty, source, files, onDirty]);
  const refresh = useCallback(async () => {
    const [rows, list] = await Promise.all([allV2<SubmissionSummary>(`tasks?assignment_id=${assignment.id}`), allV2<Pick<BatchV2,"id"|"name"|"assignment_id">>(`batches?assignment_id=${assignment.id}`)]);
    if (mounted.current) { setRecords(rows); setBatches(list); }
  }, [assignment.id]);
  function go(next: DetailStep) { setStep(next); onRoute(next, task?.id); }
  const loadTask = useCallback((value: TaskV2, activate = true) => {
    if (!mounted.current) return;
    if (value.assignment_snapshot.id !== initialAssignment.id) throw new Error("该提交属于其他作业任务，请从任务列表重新进入。");
    setTask(value); setReview(value.review?.dimensions || []); setDirty(false); setHighlight(null);
    if (activate) { setStep("grading"); onRoute("grading", value.id); }
    try { localStorage.setItem("yuejian.v2-task", value.id); } catch { /* Optional storage. */ }
  }, [initialAssignment.id, onRoute]);
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    const timer = setTimeout(() => {
      refresh().catch(e => { if (!cancelled) setError(e.message); });
      if (initialTaskId) v2<TaskV2>(`tasks/${initialTaskId}`).then(value => { if (!cancelled) loadTask(value, false); }).catch(e => { if (!cancelled) setError(e.message); });
    }, 0);
    return () => { cancelled = true; mounted.current = false; clearTimeout(timer); };
  }, [initialTaskId, loadTask, refresh]);
  useEffect(() => {
    if (!task || !["queued", "running"].includes(task.status)) return;
    let cancelled = false;
    const generation = openGeneration.current;
    const timer = setInterval(() => v2<TaskV2>(`tasks/${task.id}`).then(value => {
      if (!cancelled && generation === openGeneration.current) { loadTask(value, false); if (!["queued", "running"].includes(value.status)) void refresh(); }
    }).catch(e => { if (!cancelled) setError(e.message); }), 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [task, loadTask, refresh]);
  useEffect(() => {
    if (!batch) return;
    let cancelled = false;
    v2<AnalyticsV2>(`batches/${batch.id}/analytics?basis=${basis}`).then(value => { if (!cancelled) setAnalytics(value); }).catch(e => { if (!cancelled) setError(e.message); });
    const timer = ["queued", "running"].includes(batch.status) ? setInterval(() => v2<BatchV2>(`batches/${batch.id}`).then(value => { if (!cancelled) { setBatch(value); void refresh(); } }).catch(e => { if (!cancelled) setError(e.message); }), 1000) : null;
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [batch, basis, refresh]);
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); return true; } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : "请求失败"); return false; } finally { if (mounted.current) setBusy(false); }
  }
  async function submitOnce<T>(path: string, body?: unknown): Promise<T> {
    const signature = path + JSON.stringify(body), key = pendingKeys.current.get(signature) || crypto.randomUUID();
    pendingKeys.current.set(signature, key);
    const result = await v2<T>(path, "POST", body, key); pendingKeys.current.delete(signature); return result;
  }
  async function openRecord(id: string) {
    if ((dirty || learningReviewDirty) && !window.confirm("当前复核或修改稿有未保存修改，放弃修改并打开其他记录？")) return;
    const generation = ++openGeneration.current;
    await act(async () => { const value = await v2<TaskV2>(`tasks/${id}`); if (generation === openGeneration.current) loadTask(value); });
  }
  async function chooseBatch(id: string) {
    const generation = ++batchGeneration.current;
    setAnalytics(null); setBatch(null);
    if (!id) return;
    await act(async () => { const value = await v2<BatchV2>(`batches/${id}`); if (value.assignment_id !== assignment.id) throw new Error("该批次不属于当前作业任务"); if (mounted.current && generation === batchGeneration.current) setBatch(value); });
  }
  function editReview(index: number, fields: Partial<Review>) { setReview(review.map((row,i) => i === index ? { ...row, ...fields, reviewed: fields.reviewed ?? false } : row)); setDirty(true); }
  const currentAssignment = assignment, assignmentId = assignment.id;
  const bound = versions.find(v => v.id === assignment.rubric_version_id);
  const canSubmit = assignment.state === "published" && !busy;
  const taskReadOnly = task?.status !== "pending_review" || !!task.replaced_by || busy;
  const text = Array.from(task?.text || "");
  function tabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const keys: DetailStep[] = ["settings","grading","results","evaluation"];
    const next = event.key === "ArrowRight" ? (index+1)%4 : event.key === "ArrowLeft" ? (index+3)%4 : event.key === "Home" ? 0 : event.key === "End" ? 3 : -1;
    if (next >= 0) { event.preventDefault(); go(keys[next]); document.getElementById(`detail-tab-${keys[next]}`)?.focus(); }
  }
  return <>
    <section className="v2-context" aria-label="当前作业上下文"><div><span>{assignment.state === "published" ? "已发布任务" : "任务草稿"}</span><h1>{assignment.title}</h1><p>绑定标准：{bound?.definition.title || assignment.rubric_version_id} · v{bound?.version_no ?? "历史版本"}</p></div>
      <p>所有提交、复核记录和统计均限定在这个作业任务内。标准库中查看其他量表不会改变这里的绑定。</p></section>
    <nav className="v2-detail-tabs" role="tablist" aria-label="作业任务流程">{([['settings','任务设置'],['grading','提交与复核'],['results','结果与学情'],['evaluation','教学评测']] as const).map(([key,title],i) => <button key={key} role="tab" id={`detail-tab-${key}`} aria-controls={`detail-${key}`} aria-selected={step===key} tabIndex={step===key?0:-1} disabled={busy} onKeyDown={e => tabKey(e,i)} onClick={() => go(key)}>{title}</button>)}</nav>
    <div role="status" className="v2-notice">{notice}</div>{error && <p role="alert" className="v2-error">{error}</p>}
    <div role="tabpanel" id="detail-settings" aria-labelledby="detail-tab-settings" hidden={step!=="settings"}>
      <TaskSettings key={`${assignment.id}:${assignment.revision}`} assignment={assignment} versions={versions} busy={busy} onDirty={settingsChanged} onSubmit={() => go("grading")}
        onSave={form => act(async () => { const value = await v2<Assignment>(`assignments/${assignment.id}`,"PATCH",{expected_revision:assignment.revision,title:form.get("title"),instructions:form.get("instructions"),reference_text:form.get("reference_text"),rubric_version_id:form.get("rubric_version_id")}); setAssignment(value); await onChanged(); setNotice("任务修改已保存，可以预览发布。"); })}
        onPublish={() => act(async () => { const value=await v2<Assignment>(`assignments/${assignment.id}/publish`,"POST",{expected_revision:assignment.revision}); setAssignment(value); await onChanged(); setNotice("任务已发布，点击开始提交学生作业。"); })} />
      <LearningSettings assignment={assignment} onDirty={learningSettingsChanged} />
    </div>
    <div role="tabpanel" id="detail-grading" aria-labelledby="detail-tab-grading" hidden={step!=="grading"}>
      {assignment.state!=="published" && <p className="v2-validation">当前任务尚未发布，请先在任务设置中保存并发布。<button onClick={() => go("settings")}>前往任务设置</button></p>}
      <div className="v2-detail-grid"><div>
        <section className="v2-card"><h2>提交学生作业文本</h2><p>本次批改任务：{currentAssignment?.title || "请先在左侧选择已发布的作业任务"}</p>
          <p>这里填写学生实际提交的答案，AI将依据本次任务要求和绑定标准生成评分草稿。</p>
          <label>匿名提交号<input value={label} onChange={e => setLabel(e.target.value)} maxLength={200} /></label>
          <label>作业正文<textarea aria-label="作业正文" rows={9} value={source} onChange={e => setSource(e.target.value)} placeholder="粘贴文本前请去除姓名、学号等身份信息" /></label>
          <button className="v2-primary" disabled={!canSubmit || !source.trim()} onClick={() => void act(async () => { ++openGeneration.current; const value = await submitOnce<TaskV2>("tasks", { assignment_id: assignmentId, submission_label: label, text: source }); loadTask(value); setSource(""); await refresh(); })}>按当前作业标准生成草稿</button>
          <h3>批量 TXT / MD</h3>
          <label>批次名称<input value={batchName} onChange={e => setBatchName(e.target.value)} /></label>
          <label>选择多个文本文件<input ref={fileInput} type="file" multiple accept=".txt,.md" disabled={busy} onChange={e => {
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
          <button disabled={!canSubmit || !files.length} onClick={() => void act(async () => { const value = await submitOnce<BatchV2>("batches", { assignment_id: assignmentId, name: batchName, files }); ++batchGeneration.current; setAnalytics(null); setBatch(value); setFiles([]); if (fileInput.current) fileInput.current.value = ""; go("results"); await refresh(); })}>创建批量任务</button>
        </section>

        <section className="v2-card" aria-label="本次作业的提交记录"><h2>本次作业的提交记录</h2><p>单份与批量记录统一保留在此处，刷新后仍可打开。</p>
          <label className="v2-checkbox"><input type="checkbox" checked={showReplaced} onChange={e => setShowReplaced(e.target.checked)} />显示已替换的重试历史</label>
          {records.length ? <div className="v2-table-wrap"><table><thead><tr><th>匿名提交号</th><th>状态</th><th>最近保存总分</th><th>操作</th></tr></thead><tbody>
            {records.filter(r => showReplaced || !r.replaced_by).map(r => <tr key={r.id}><td>{r.submission_label}</td><td>{r.replaced_by ? "已由重试替换" : statusName[r.status]}</td><td>{r.total ?? "—"}</td><td><button disabled={busy} onClick={() => void openRecord(r.id)}>打开复核</button></td></tr>)}
          </tbody></table></div> : <p>暂无提交。可粘贴一份文本，或批量上传TXT / MD。</p>}
        </section>
      </div><div>
        {task && <section className="v2-card" aria-label="动态评分与复核"><div className="v2-section-title"><h2>逐项复核 · {task.submission_label}</h2><span>{statusName[task.status]}</span></div>
          <p>{task.assignment_snapshot.title} · {task.rubric_snapshot.dimensions.length} 个维度 · 模型调用 {task.model_calls} 次 · 修正 {task.repair_rounds} 轮</p>
          {task.replaced_by && <p className="v2-validation">该记录已由重试替换，仅供历史查看。<button onClick={() => void openRecord(task.replaced_by!)}>打开最新重试</button></p>}{task.security_detail && <p className="v2-error">{task.security_detail}</p>}
          {task.error && <p className="v2-error">{task.error.code}：{task.error.message}</p>}
          {task.status === "failed" && <div className="v2-actions"><button disabled={busy || !!task.replaced_by} onClick={() => void act(async () => { loadTask(await submitOnce<TaskV2>(`tasks/${task.id}/retry`)); if (batch) setBatch(await v2<BatchV2>(`batches/${batch.id}`)); })}>重试本份</button><button disabled={busy || !!task.replaced_by} onClick={() => void act(async () => loadTask(await v2<TaskV2>(`tasks/${task.id}/manual`, "POST")))}>转人工批改</button></div>}
          <details><summary>冻结标准与任务要求</summary><p>{task.assignment_snapshot.instructions}</p><p>参考说明：{task.assignment_snapshot.reference_text || "未提供"}</p><p>量表版本：{task.rubric_version_id}</p><p className="v2-hash">原文 SHA-256：{task.input_version}<br />量表 SHA-256：{task.rubric_hash}<br />上下文 SHA-256：{task.context_hash}</p></details>
          <details open={!!highlight}><summary>学生原文{highlight ? ` · 已定位第${highlight.paragraph}段` : ""}</summary><div className="v2-source" tabIndex={0}>{highlight ? <>{text.slice(0, highlight.start).join("")}<mark ref={evidenceMark}>{text.slice(highlight.start, highlight.end).join("")}</mark>{text.slice(highlight.end).join("")}</> : task.text}</div></details>
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
              {draft?.evidence.map((ref, i) => <button type="button" disabled={false} key={i} className="v2-quote" onClick={() => setHighlight({ ...ref })}>定位证据：「{ref.quote}」</button>)}
            </fieldset>;
          })}
          {task.review && <p className="v2-total">最近保存总分：<strong>{task.review.total ?? "待计算"}</strong> / 100.00</p>}
          {task.status === "pending_review" && !task.replaced_by && <div className="v2-actions"><button disabled={busy} onClick={() => void act(async () => { loadTask(await v2<TaskV2>(`tasks/${task.id}/review`, "PATCH", { ...versionFields(task), dimensions: review.map(({ dimension_id, level_id, reason, reviewed }) => ({ dimension_id, level_id, reason, reviewed })) })); await refresh(); setNotice("复核已保存，分值由后端重算。"); })}>保存复核并重算</button>
            <button className="v2-primary" disabled={busy || dirty || !review.length || review.some(row => !row.reviewed)} onClick={() => void act(async () => { loadTask(await v2<TaskV2>(`tasks/${task.id}/confirm`, "POST", versionFields(task))); if (batch) setBatch(await v2<BatchV2>(`batches/${batch.id}`)); await refresh(); setNotice("教师已确认，已写入不可变记录。"); })}>确认并归档</button></div>}
          {task.status === "confirmed" && <a href={`/api/v2/tasks/${task.id}/export`} download>下载确认记录 JSON</a>}
        </section>}

        {!task && <section className="v2-card v2-empty"><h2>等待选择学生提交</h2><p>提交文本后在此生成评分草稿，或从左侧历史记录打开复核。</p></section>}
        {task && <LearningReview key={task.id} task={task} onOpen={openRecord} reviewDirty={dirty} onCreated={async value=>{loadTask(value);await refresh();}} onDirty={learningReviewChanged} />}
      </div></div>
    </div>
    <div role="tabpanel" id="detail-results" aria-labelledby="detail-tab-results" hidden={step!=="results"}>
        <section className="v2-card"><h2>同次作业的进度与学情</h2>
          <label>历史批次<select disabled={busy} value={batch?.id || ""} onChange={e => void chooseBatch(e.target.value)}><option value="">请选择批次</option>{batches.filter(b => b.assignment_id === assignment.id).map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
          {batch && <><p>{statusName[batch.status]} · 共 {batch.total_count} 份 · 处理结束 {batch.finished_count} · 教师确认 {batch.confirmed_count} · 失败 {batch.failed_count}</p>
            <div className="v2-table-wrap"><table><thead><tr><th>匿名提交号</th><th>状态</th><th>最近保存分数</th><th>操作</th></tr></thead><tbody>{batch.items.map(item => <tr key={item.task_id}><td>{item.submission_label}</td><td>{statusName[item.status]}</td><td>{item.total ?? "—"}</td><td><button disabled={busy} onClick={() => void openRecord(item.task_id)}>打开复核</button></td></tr>)}</tbody></table></div>
            <label>统计口径<select value={basis} onChange={e => setBasis(e.target.value)}><option value="confirmed">仅教师确认结果</option><option value="working">临时预览（含未确认结果）</option></select></label>
            {analytics && <><p className={analytics.provisional ? "v2-error" : "v2-validation"}>{analytics.provisional ? "临时统计，包含未确认草稿或复核" : "确认统计，只使用不可变确认记录"} · 已分析 {analytics.analyzed} / {analytics.submitted} · 排除 {analytics.excluded} · 均分 {analytics.average_score ?? "暂无"}</p><Chart data={analytics} />
              {analytics.dimensions.map(d => <p key={d.id}>{d.name}：平均 {d.average_score ?? "暂无"} / {d.max_score}，得分率 {d.scoring_rate ?? "暂无"}%</p>)}
              {analytics.rows.map(row => <p key={row.task_id}>{row.submission_label} · 来源：{row.source === "record" ? "确认记录" : row.source === "review" ? "未确认复核" : "AI 草稿"} · {row.total}</p>)}
              <h3>常见薄弱维度（规则统计）</h3>{analytics.common_weaknesses.map(w => <details key={w.dimension_id}><summary>{w.name} · {w.affected_count} 份</summary>{w.reasons.map((r, i) => <p key={i}>{r.submission_label}：{r.reason}</p>)}</details>)}
            </>}
            {batch.confirmed_count > 0 ? <a href={`/api/v2/batches/${batch.id}/export-csv`} download>导出已确认 {batch.confirmed_count} 份 CSV（其他提交不导出）</a> : <p>暂无确认成绩，完成教师复核后可导出 CSV。</p>}
          </>}
        </section>
      {!batch && <p className="v2-validation">请选择当前作业的一个批次查看统计。单份评分与确认JSON可在“提交与复核”中查看。</p>}
      {step === "results" && <LearningResults assignmentId={assignment.id} version={`${task?.id}:${task?.status}:${task?.review_revision}:${records.length}`} onOpen={openRecord} />}
    </div>
    <div role="tabpanel" id="detail-evaluation" aria-labelledby="detail-tab-evaluation" hidden={step!=="evaluation"}>
      <LearningEvaluation key={assignment.id} assignment={assignment} records={records} onDirty={evaluationChanged} />
    </div>
  </>;
}
