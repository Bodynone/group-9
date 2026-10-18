"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine, ArrowRight, BookOpenCheck, Check, CheckCircle2, ChevronDown,
  CircleAlert, ClipboardCheck, FileText, Fingerprint, LoaderCircle, LocateFixed,
  RotateCcw, ShieldCheck, Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  dimensionIds, errorMessage, request, reviewForTask, selectionOffset,
  type DimensionId, type Evidence, type Level, type ReviewDimension, type Rubric, type Task,
} from "@/lib/grading";

const TASK_KEY = "yuejian.latest-task";
const INPUT_KEY = "yuejian.input";
const statusLabels: Record<Task["status"], string> = {
  queued: "等待开始", running: "正在生成评分草稿", pending_review: "待教师确认", failed: "生成未完成", confirmed: "已确认保存",
};
const levelLabels: Record<Level, string> = { 100: "充分达成 · 100%", 70: "基本达成 · 70%", 30: "部分达成 · 30%", 0: "整体缺失 · 0%" };
const toolLabels: Record<string, string> = {
  read_rubric: "读取量表", get_rubric: "读取量表", locate_evidence: "定位原文", calculate_score: "精确计分",
  calculate_scores: "精确计分", validate_draft: "校验草稿",
};

function persist(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* Grading still works when browser storage is unavailable. */ }
}

function criteriaText(criteria: Rubric["dimensions"][number]["criteria"]) {
  if (typeof criteria === "string") return criteria;
  return Object.entries(criteria).map(([key, value]) => `${key}：${value}`).join("\n");
}

export function GradingWorkspace() {
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [text, setText] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [review, setReview] = useState<ReviewDimension[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rubricError, setRubricError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [focusedEvidence, setFocusedEvidence] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const generationRef = useRef(0);
  const historical = !!task && !!rubric && task.rubric_version !== rubric.version;

  const receiveTask = useCallback((next: Task) => {
    setTask(next);
    setText(next.text);
    setReview(reviewForTask(next));
    setDirty(false);
    persist(TASK_KEY, next.id);
    persist(INPUT_KEY, next.text);
  }, []);

  const loadRubric = useCallback(async () => {
    try {
      const next = await request<Rubric>("/api/rubric");
      setRubric(next);
      setRubricError(null);
    } catch (error) { setRubricError(errorMessage(error)); }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const generation = generationRef.current;
    async function restore() {
      try {
        const savedInput = localStorage.getItem(INPUT_KEY);
        const savedId = localStorage.getItem(TASK_KEY);
        if (savedInput && !cancelled && generation === generationRef.current) setText(savedInput);
        if (savedId) {
          const restored = await request<Task>(`/api/tasks/${encodeURIComponent(savedId)}`);
          if (!cancelled && generation === generationRef.current) receiveTask(restored);
        }
      } catch (error) {
        if (!cancelled && generation === generationRef.current) setNotice(`上次任务暂未恢复：${errorMessage(error)}`);
      } finally { if (!cancelled) setRestoring(false); }
    }
    const startup = setTimeout(() => { void loadRubric(); void restore(); }, 0);
    return () => { cancelled = true; clearTimeout(startup); };
  }, [loadRubric, receiveTask]);

  useEffect(() => {
    if (!task || !rubric || historical || (task.status !== "queued" && task.status !== "running")) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const generation = generationRef.current;
    const taskId = task.id;
    async function poll() {
      try {
        const next = await request<Task>(`/api/tasks/${encodeURIComponent(taskId)}`);
        if (cancelled || generation !== generationRef.current) return;
        receiveTask(next);
        setNotice(null);
        if (next.status !== "queued" && next.status !== "running") return;
      } catch (error) {
        if (cancelled || generation !== generationRef.current) return;
        setNotice(`任务状态暂时无法更新，将继续尝试连接。${errorMessage(error)}`);
      }
      if (!cancelled) timer = setTimeout(poll, 1000);
    }
    timer = setTimeout(poll, 1000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [task?.id, task?.status, receiveTask, task, rubric, historical]);

  function changeText(value: string) {
    generationRef.current += 1;
    setText(value);
    setTask(null);
    setReview([]);
    setDirty(false);
    setBusy(null);
    setNotice(task ? "原文已修改，之前的评分已清除。请重新生成草稿。" : null);
    setFocusedEvidence(null);
    persist(TASK_KEY, null);
    persist(INPUT_KEY, value);
  }

  async function startTask() {
    if (!rubric || !text.trim()) return;
    if (historical && task?.status !== "confirmed") {
      await taskAction("retry");
      return;
    }
    const generation = ++generationRef.current;
    setBusy("生成");
    setNotice(null);
    setFocusedEvidence(null);
    try {
      const next = await request<Task>("/api/tasks", {
        method: "POST", body: JSON.stringify({ text, rubric_version: rubric.version }),
      });
      if (generation === generationRef.current) receiveTask(next);
    } catch (error) {
      if (generation === generationRef.current) setNotice(errorMessage(error));
    } finally { if (generation === generationRef.current) setBusy(null); }
  }

  async function taskAction(action: "retry" | "manual") {
    if (!task || !rubric || (historical && action === "manual")) return;
    const generation = ++generationRef.current;
    setBusy(action);
    setNotice(null);
    try {
      const next = await request<Task>(`/api/tasks/${task.id}/${action}`, { method: "POST" });
      if (generation === generationRef.current) receiveTask(next);
    } catch (error) {
      if (generation === generationRef.current) setNotice(errorMessage(error));
    } finally { if (generation === generationRef.current) setBusy(null); }
  }

  function editReview(id: DimensionId, change: Partial<ReviewDimension>) {
    if (!editable) return;
    setReview((current) => current.map((dimension) => dimension.id === id
      ? { ...dimension, ...change, ...(change.level !== undefined || change.reason !== undefined ? { reviewed: false, score: null } : {}) }
      : dimension));
    setDirty(true);
    setNotice(null);
  }

  async function saveReview(confirm = false) {
    if (!task || !rubric || historical) return;
    const generation = ++generationRef.current;
    setBusy(confirm ? "confirm" : "review");
    setNotice(null);
    try {
      const saved = await request<Task>(`/api/tasks/${task.id}/review`, {
        method: "PATCH", body: JSON.stringify({ input_version: task.input_version, dimensions: review.map(({ id, level, reason, reviewed }) => ({ id, level, reason, reviewed })) }),
      });
      if (generation !== generationRef.current) return;
      receiveTask(saved);
      if (confirm) {
        const confirmed = await request<Task>(`/api/tasks/${task.id}/confirm`, { method: "POST" });
        if (generation === generationRef.current) receiveTask(confirmed);
      } else setNotice("复核已保存，分数已重新计算。");
    } catch (error) {
      if (generation === generationRef.current) setNotice(errorMessage(error));
    } finally { if (generation === generationRef.current) setBusy(null); }
  }

  function locate(evidence: Evidence) {
    const input = inputRef.current;
    if (!input || !task || task.text !== text) return;
    const start = selectionOffset(text, evidence.start);
    const end = selectionOffset(text, evidence.end);
    input.focus();
    input.setSelectionRange(start, end);
    const lineCount = text.slice(0, start).split("\n").length;
    input.scrollTop = Math.max(0, (lineCount - 3) * 25);
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    setFocusedEvidence(`已定位第 ${evidence.paragraph} 段：“${evidence.quote}”`);
  }

  const running = !historical && (task?.status === "queued" || task?.status === "running");
  const editable = !!rubric && !historical && task?.status === "pending_review" && !busy;
  const complete = review.length === 6 && review.every((dimension) => dimension.level !== null && dimension.reason.trim());
  const reviewedCount = review.filter((dimension) => dimension.reviewed).length;
  const readyToConfirm = complete && reviewedCount === 6;
  const confirmed = task?.status === "confirmed";
  const total = dirty ? null : task?.review?.total ?? task?.draft?.total;

  return (
    <div className="workspace-shell">
      <header className="site-header">
        <div className="brand"><span className="brand-symbol"><BookOpenCheck size={24} /></span><span>阅见 <span className="brand-divider">/</span> <span className="brand-subtitle">教师工作台</span></span></div>
        <div className="header-caption"><span className="live-dot" />单份作业批改</div>
      </header>
      <main className="workspace">
        <section className="page-intro">
          <div><div className="eyebrow">有据可查 · 教师把关</div><h1>把每一分，落在证据上。</h1><p>六维评分建议与原文一起复核，由您完成最终确认。</p></div>
          <div className="process-strip" aria-label="批改步骤">
            <span className={!task ? "current" : "complete"}><span>1</span>输入作业</span><ArrowRight size={14} />
            <span className={running ? "current" : task?.draft ? "complete" : ""}><span>2</span>生成草稿</span><ArrowRight size={14} />
            <span className={task?.status === "pending_review" ? "current" : confirmed ? "complete" : ""}><span>3</span>复核确认</span>
          </div>
        </section>

        {notice && <div className="notice" role="status"><CircleAlert size={18} /><span>{notice}</span></div>}

        <div className="workspace-grid">
          <aside className="source-column">
            <section className="panel source-panel">
              <div className="panel-heading"><div className="section-label"><FileText size={19} /><h2>匿名作业原文</h2></div><span className="small-badge">单份作业</span></div>
              <p className="panel-description">粘贴待批改内容，请先移除姓名、学号等身份信息。</p>
              <label htmlFor="assignment" className="sr-only">匿名作业原文</label>
              <textarea id="assignment" ref={inputRef} className="source-input" value={text} onChange={(event) => changeText(event.target.value)} placeholder={"在这里粘贴匿名作业…\n\n保留标题与段落，便于定位评分证据。"} spellCheck={false} disabled={restoring} />
              <div className="input-meta"><span>{Array.from(text).length.toLocaleString("zh-CN")} 字符</span><span>{task ? "原文已保存" : "输入自动保留在本机"}</span></div>
              {focusedEvidence && <p className="evidence-location" role="status"><LocateFixed size={15} />{focusedEvidence}</p>}
              <Button className="primary-action" size="lg" onClick={() => void startTask()} disabled={!rubric || !text.trim() || !!busy || running || restoring}>
                {busy === "生成" || running ? <LoaderCircle className="spinning" size={18} /> : <Sparkles size={18} />}
                {running ? "正在生成评分草稿" : historical && !confirmed ? "按当前量表重新生成" : "生成评分草稿"}<ArrowRight size={16} />
              </Button>
              <p className="source-footnote"><ShieldCheck size={14} />草稿通过校验后，仍需逐维复核与确认。</p>
            </section>

            <section className="panel rubric-panel">
              <div className="panel-heading"><div className="section-label"><ClipboardCheck size={19} /><h2>固定评分量表</h2></div><strong className="rubric-total">100 <small>分</small></strong></div>
              {rubricError ? <div className="rubric-error"><p>{rubricError}</p><Button variant="outline" onClick={() => void loadRubric()}>重新加载量表</Button></div> : rubric ? <>
                <div className="rubric-list">{rubric.dimensions.map((dimension) => <details key={dimension.id}><summary><span className="dimension-letter">{dimension.id}</span><span>{dimension.name}</span><strong>{dimension.max_score} 分</strong><ChevronDown size={14} /></summary><p>{criteriaText(dimension.criteria)}</p></details>)}</div>
                <div className="rubric-footer"><span>版本 {rubric.version}</span><span>档位 100% / 70% / 30% / 0%</span></div>
              </> : <p className="loading-label"><LoaderCircle size={16} className="spinning" />正在读取量表…</p>}
            </section>
          </aside>

          <section className="results-column" aria-label="评分与复核">
            {!task ? <section className="panel empty-state"><div className="empty-illustration"><FileText size={48} strokeWidth={1.2} /><span><Check size={21} /></span></div><span className="eyebrow">从一份作业开始</span><h2>{restoring ? "正在恢复工作进度…" : "评分建议将在这里呈现"}</h2><p>粘贴原文并生成草稿，即可逐维查看评分理由、定位原文证据，再完成教师复核。</p><div className="empty-features"><span><LocateFixed size={16} />原文证据</span><span><ShieldCheck size={16} />程序校验</span><span><ClipboardCheck size={16} />教师确认</span></div></section> : <>
              <section className={`panel result-summary status-${task.status}`}>
                {historical && <div className="notice historical-task" role="status"><CircleAlert size={18} /><span>此任务使用历史量表 {task.rubric_version}，仅供查看。当前量表为 {rubric?.version}；历史维度满分请参考原始 JSON 记录。{!confirmed && "点击左侧“按当前量表重新生成”可创建关联的新任务。"}</span></div>}
                <div className="summary-top"><div className="section-label">{running ? <LoaderCircle className="spinning" size={21} /> : confirmed ? <CheckCircle2 size={21} /> : task.status === "failed" ? <CircleAlert size={21} /> : <ClipboardCheck size={21} />}<h2>{statusLabels[task.status]}</h2></div><span className="small-badge">{task.source === "manual" ? "人工批改" : "Agent 评分建议"}</span></div>
                <div className="summary-body"><div><p>{running ? "正在查证原文并校验草稿，请稍候。" : confirmed ? "教师已完成六维复核，批改记录已保存。" : task.status === "failed" ? "原文与量表已保留，可重试或继续人工批改。" : task.source === "manual" ? "填写六维档位与理由，再逐维勾选确认。" : "请查证评分依据，逐维采纳或调整建议。"}</p><div className="summary-meta"><span>量表 {task.rubric_version}</span><span>{confirmed ? `记录 ${task.record_id}` : `已复核 ${reviewedCount} / 6 维`}</span></div></div>{!running && task.status !== "failed" && <div className="score-total"><strong>{total ?? "—"}</strong><span>/ 100</span><small>{dirty ? "保存后重新计分" : confirmed ? "最终得分" : "待确认得分"}</small></div>}</div>
                {running && <div className="run-progress"><span /> <small>已执行 {task.trace.filter((item) => item.kind === "tool_result").length} 次工具操作 · 已校验 {task.validation_count} 次</small></div>}
                {task.status === "failed" && task.error && <div className="task-error"><strong>{task.error.message}</strong><span>错误编号：{task.error.code}</span>{!historical && <div className="error-actions"><Button size="lg" onClick={() => void taskAction("retry")} disabled={!!busy}><RotateCcw size={16} />重新尝试</Button><Button size="lg" variant="outline" onClick={() => void taskAction("manual")} disabled={!!busy}><ClipboardCheck size={16} />进入人工批改</Button></div>}</div>}
              </section>

              {(task.status === "pending_review" || confirmed) && rubric && <div className="dimension-cards">{dimensionIds.map((id) => {
                const definition = rubric.dimensions.find((dimension) => dimension.id === id);
                const suggestion = task.draft?.dimensions.find((dimension) => dimension.id === id);
                const dimension = review.find((item) => item.id === id);
                if (!definition || !dimension) return null;
                return <article className={`panel dimension-card ${dimension.reviewed ? "is-reviewed" : ""}`} key={id}>
                  <div className="dimension-heading"><div><span className="dimension-letter">{id}</span><h3>{historical ? `维度 ${id}（历史记录）` : definition.name}</h3></div><div className="dimension-score"><strong>{dimension.score ?? "—"}</strong>{!historical && <span>/ {definition.max_score}</span>}</div></div>
                  {suggestion?.needs_review && <p className="review-flag"><CircleAlert size={14} />待核查：{suggestion.review_note || "请核实此维度的评分依据。"}</p>}
                  {suggestion && <div className="suggestion-line"><span>Agent 建议</span><strong>{suggestion.score} 分 · {suggestion.level}%</strong><details><summary>查看原始理由</summary><p>{suggestion.reason}</p></details></div>}
                  <div className="review-fields"><label htmlFor={`level-${id}`}>教师档位<select id={`level-${id}`} value={dimension.level ?? ""} onChange={(event) => editReview(id, { level: Number(event.target.value) as Level })} disabled={!editable}><option value="" disabled>选择档位</option>{([100, 70, 30, 0] as Level[]).map((level) => <option value={level} key={level}>{levelLabels[level]}</option>)}</select></label><label htmlFor={`reason-${id}`}>评分理由<textarea id={`reason-${id}`} value={dimension.reason} onChange={(event) => editReview(id, { reason: event.target.value })} disabled={!editable} placeholder="说明此档位的依据…" rows={3} /></label></div>
                  <div className="evidence-section"><span className="field-caption">原文证据</span>{suggestion?.evidence.length ? suggestion.evidence.map((evidence, index) => <button className="evidence-button" key={`${evidence.start}-${index}`} onClick={() => locate(evidence)} title="在左侧原文中定位"><span>“{evidence.quote}”</span><small>第 {evidence.paragraph} 段<LocateFixed size={13} /></small></button>) : <p className="no-evidence">{task.source === "manual" ? "人工批改，请结合左侧原文填写理由。" : "未引用证据，请结合原文核查整体缺失判定。"}</p>}</div>
                  <label className="review-checkbox"><input type="checkbox" checked={dimension.reviewed} onChange={(event) => editReview(id, { reviewed: event.target.checked })} disabled={!editable || dimension.level === null || !dimension.reason.trim()} /><span>{confirmed ? "教师已复核" : "我已核查此维度的档位与理由"}</span>{dimension.reviewed && <CheckCircle2 size={16} />}</label>
                </article>;
              })}</div>}

              {task.trace.length > 0 && <details className="panel trace-panel"><summary><span><Fingerprint size={17} />执行摘要</span><span>{task.validation_count} 次校验 · {task.repair_rounds} 轮修正<ChevronDown size={16} /></span></summary><div className="trace-content"><p className="trace-meta">任务 {task.id}<br />输入版本 {task.input_version}<br />模型请求 {task.model_calls} 次</p><ol>{task.trace.map((item) => <li key={item.sequence}><span className="trace-dot" /><div><strong>{item.tool ? toolLabels[item.tool] || item.tool : item.kind}</strong><small>第 {item.round} 轮 · 校验累计 {item.validation_count} 次</small><pre>{JSON.stringify(item.details, null, 2)}</pre></div></li>)}</ol></div></details>}

              {(task.status === "pending_review" || confirmed) && <section className="panel confirm-panel"><div><strong>{confirmed ? "批改记录已保存" : historical ? "历史任务仅供查看" : `教师复核 ${reviewedCount} / 6 维`}</strong><p>{confirmed ? `记录编号 ${task.record_id}` : historical ? "请按当前量表重新生成后复核。" : "全部维度复核完成后，确认保存最终批改记录。"}</p></div><div className="confirm-actions">{confirmed ? <a className="download-action" href={`/api/tasks/${task.id}/export`} download><ArrowDownToLine size={17} />导出 JSON 记录</a> : !historical && <><Button variant="outline" size="lg" onClick={() => void saveReview()} disabled={!complete || !!busy}>{busy === "review" && <LoaderCircle className="spinning" size={16} />}保存复核</Button><Button size="lg" onClick={() => void saveReview(true)} disabled={!readyToConfirm || !!busy}>{busy === "confirm" ? <LoaderCircle className="spinning" size={16} /> : <CheckCircle2 size={16} />}确认保存批改记录</Button></>}</div></section>}
            </>}
          </section>
        </div>
        <footer className="workspace-footer"><span>阅见 · 每次批改都有依据</span><span>单份作业 / 固定量表 / 教师确认</span></footer>
      </main>
    </div>
  );
}
