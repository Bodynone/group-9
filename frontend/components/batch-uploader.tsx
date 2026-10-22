"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import {
  ArrowDownToLine, ArrowRight, CircleAlert, FileText, FolderOpen, LoaderCircle,
  RefreshCw, Trash2, UploadCloud,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  batchCsvUrl, createBatch, errorMessage, getBatch, getBatches, request,
  type Batch, type BatchStatus, type BatchSummary, type Rubric, type Task,
} from "@/lib/grading";

type SelectedFile = { filename: string; text: string; characters: number };
type Props = {
  active: boolean;
  selectedBatchId: string | null;
  onSelectBatch: (batchId: string) => void;
  onOpenTask: (taskId: string) => void;
  onShowAnalytics: () => void;
};

const batchLabels: Record<BatchStatus, string> = {
  queued: "排队中", running: "批改中", completed: "批改完成",
  partial_failed: "部分失败", failed: "全部失败",
};
const taskLabels: Record<Task["status"], string> = {
  queued: "排队中", running: "分析中", pending_review: "待复核",
  failed: "失败", confirmed: "已确认",
};

function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        resolve(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(reader.result as ArrayBuffer));
      } catch {
        reject(new Error(`${file.name}：不是有效的 UTF-8 文本，请转换编码后重试`));
      }
    };
    reader.onerror = () => reject(new Error(`${file.name} 读取失败`));
    reader.onabort = () => reject(new Error(`${file.name} 读取已取消`));
    reader.readAsArrayBuffer(file);
  });
}

function shortDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function BatchUploader({ active, selectedBatchId, onSelectBatch, onOpenTask, onShowAnalytics }: Props) {
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [rubricError, setRubricError] = useState<string | null>(null);
  const [rubricRevision, setRubricRevision] = useState(0);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<SelectedFile[]>([]);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [fileNotice, setFileNotice] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [history, setHistory] = useState<BatchSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyRevision, setHistoryRevision] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void request<Rubric>("/api/rubric").then((next) => {
      if (!cancelled) { setRubric(next); setRubricError(null); }
    }).catch((error: unknown) => {
      if (!cancelled) setRubricError(errorMessage(error));
    });
    return () => { cancelled = true; };
  }, [active, rubricRevision]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    void getBatches().then((result) => {
      if (!cancelled) { setHistory(result.items); setHistoryError(null); }
    }).catch((error: unknown) => {
      if (!cancelled) setHistoryError(errorMessage(error));
    });
    return () => { cancelled = true; };
  }, [active, historyRevision]);

  useEffect(() => {
    if (!active || !selectedBatchId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getBatch(selectedBatchId!);
        if (cancelled) return;
        setBatch(next);
        setBatchError(null);
        setHistory((current) => current.map((item) => item.batch_id === next.batch_id
          ? { ...item, status: next.status, completed_count: next.completed_count, failed_count: next.failed_count, updated_at: next.updated_at }
          : item));
        if (next.status !== "queued" && next.status !== "running") return;
      } catch (error) {
        if (cancelled) return;
        setBatchError(errorMessage(error));
      }
      if (!cancelled) timer = setTimeout(poll, 1500);
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active, selectedBatchId, refreshRevision]);

  async function addFiles(incoming: FileList | File[]) {
    if (reading || submitting || !incoming.length) return;
    setReading(true);
    const known = new Set(files.map((file) => file.filename.toLocaleLowerCase()));
    const rejected: string[] = [];
    const candidates = Array.from(incoming).filter((file) => {
      if (!/\.(txt|md)$/i.test(file.name)) { rejected.push(`${file.name}：仅支持 TXT、MD`); return false; }
      if (file.size > 200_000) { rejected.push(`${file.name}：文件过大，超过 50,000 字符的 UTF-8 容量`); return false; }
      const key = file.name.toLocaleLowerCase();
      if (known.has(key)) { rejected.push(`${file.name}：文件名重复`); return false; }
      known.add(key);
      return true;
    });
    const results = await Promise.allSettled(candidates.map(readText));
    const accepted: SelectedFile[] = [];
    results.forEach((result, index) => {
      const filename = candidates[index].name;
      if (result.status === "rejected") { rejected.push(errorMessage(result.reason)); return; }
      const text = result.value;
      const characters = Array.from(text).length;
      if (!text.trim()) rejected.push(`${filename}：正文为空`);
      else if (characters > 50_000) rejected.push(`${filename}：超过 50,000 字符`);
      else accepted.push({ filename, text, characters });
    });
    setFiles((current) => [...current, ...accepted]);
    setFileNotice(rejected.length ? `${rejected.slice(0, 3).join("；")}${rejected.length > 3 ? `；另有 ${rejected.length - 3} 个文件未加入` : ""}` : null);
    setReading(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void addFiles(event.dataTransfer.files);
  }

  async function submit() {
    if (!rubric || !name.trim() || !files.length || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await createBatch(name.trim(), rubric.version, files.map(({ filename, text }) => ({ filename, text })));
      onSelectBatch(created.batch_id);
      setName("");
      setFiles([]);
      setFileNotice(null);
      setHistoryRevision((value) => value + 1);
    } catch (error) {
      setSubmitError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  const visibleBatch = batch?.batch_id === selectedBatchId ? batch : null;
  const processed = visibleBatch ? visibleBatch.completed_count + visibleBatch.failed_count : 0;
  const percent = visibleBatch ? Math.round(processed / visibleBatch.total_count * 100) : 0;
  const characters = files.reduce((total, file) => total + file.characters, 0);

  return (
    <main className="workspace batch-page">
      <section className="page-intro"><div><div className="eyebrow">班级作业 / 批次管理</div><h1>批量摄取与队列</h1><p>集中查看每份作业的批改进度与复核状态。</p></div></section>

      <div className="batch-layout">
        <section className="batch-composer" aria-labelledby="batch-create-title">
          <div className="surface-heading"><div><span className="section-kicker">01 / 新建批次</span><h2 id="batch-create-title">导入作业</h2></div><span className="surface-meta">{files.length} 份 · {characters.toLocaleString("zh-CN")} 字符</span></div>
          <label className="field-label" htmlFor="batch-name">批次名称</label>
          <input id="batch-name" className="text-field" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：软件工程班 · 第二次作业" maxLength={120} />
          <div className={`batch-dropzone ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={onDrop}>
            <input id="batch-files" ref={inputRef} className="sr-only" type="file" accept=".txt,.md,text/plain,text/markdown" multiple disabled={reading || submitting} onChange={(event) => { if (event.target.files) void addFiles(event.target.files); }} />
            <label htmlFor="batch-files"><UploadCloud size={25} /><strong>{reading ? "正在读取文件…" : "选择文件或拖入"}</strong><span>TXT / MD · 单份不超过 50,000 字符</span></label>
          </div>
          {fileNotice && <p className="inline-alert" role="status"><CircleAlert size={15} />{fileNotice}</p>}
          {files.length > 0 && <ul className="selected-files" aria-label="待提交文件">{files.map((file) => <li key={file.filename}><FileText size={16} /><span title={file.filename}>{file.filename}</span><small>{file.characters.toLocaleString("zh-CN")} 字</small><button type="button" title={`移除 ${file.filename}`} aria-label={`移除 ${file.filename}`} onClick={() => setFiles((current) => current.filter((item) => item.filename !== file.filename))} disabled={submitting}><Trash2 size={15} /></button></li>)}</ul>}
          {rubricError && <p className="inline-alert" role="alert"><CircleAlert size={15} />量表读取失败：{rubricError}<button type="button" onClick={() => setRubricRevision((value) => value + 1)}>重试</button></p>}
          {submitError && <p className="inline-alert" role="alert"><CircleAlert size={15} />{submitError}</p>}
          <div className="composer-actions"><span>量表 {rubric?.version ?? "读取中"}</span><Button size="lg" onClick={() => void submit()} disabled={!rubric || !name.trim() || !files.length || reading || submitting}>{submitting ? <LoaderCircle className="spinning" size={17} /> : <UploadCloud size={17} />}创建批次</Button></div>
        </section>

        <aside className="batch-history" aria-labelledby="batch-history-title">
          <div className="surface-heading"><div><span className="section-kicker">02 / 历史记录</span><h2 id="batch-history-title">最近批次</h2></div><button className="icon-action" title="刷新批次列表" aria-label="刷新批次列表" onClick={() => setHistoryRevision((value) => value + 1)}><RefreshCw size={17} /></button></div>
          {historyError ? <p className="inline-alert" role="alert"><CircleAlert size={15} />{historyError}</p> : history.length ? <div className="history-list">{history.map((item) => <button type="button" key={item.batch_id} className={item.batch_id === selectedBatchId ? "is-selected" : ""} onClick={() => onSelectBatch(item.batch_id)}><span className="history-main"><strong>{item.name}</strong><small>{shortDate(item.created_at)}</small></span><span className="history-tail"><span className={`status-pill batch-${item.status}`}>{batchLabels[item.status]}</span><small>{item.total_count} 份</small></span></button>)}</div> : <div className="quiet-empty"><FolderOpen size={25} /><p>暂无批次</p></div>}
        </aside>
      </div>

      <section className="batch-monitor" aria-labelledby="batch-monitor-title">
        <div className="surface-heading monitor-heading"><div><span className="section-kicker">03 / 进度监控</span><h2 id="batch-monitor-title">{visibleBatch?.name ?? "当前批次"}</h2></div>{selectedBatchId && <div className="monitor-actions"><button className="icon-action" title="刷新进度" aria-label="刷新进度" onClick={() => setRefreshRevision((value) => value + 1)}><RefreshCw size={17} /></button>{visibleBatch && <><a className="secondary-link" href={batchCsvUrl(selectedBatchId)}><ArrowDownToLine size={16} />下载班级成绩单</a><Button onClick={onShowAnalytics}><ArrowRight size={16} />查看学情</Button></>}</div>}</div>
        {batchError && <p className="inline-alert" role="status"><CircleAlert size={15} />进度读取失败：{batchError}</p>}
        {visibleBatch ? <>
          <div className="progress-summary"><div><strong className={`status-pill batch-${visibleBatch.status}`}>{batchLabels[visibleBatch.status]}</strong><span>已完成批改 {visibleBatch.completed_count} / {visibleBatch.total_count}</span>{visibleBatch.failed_count > 0 && <span className="failed-count">失败 {visibleBatch.failed_count}</span>}</div><strong>{percent}%</strong></div>
          <div className="progress-track" role="progressbar" aria-label="批次处理进度" aria-valuenow={processed} aria-valuemin={0} aria-valuemax={visibleBatch.total_count}><span style={{ width: `${percent}%` }} /></div>
          <div className="table-scroll"><table className="batch-table"><thead><tr><th scope="col">作业文件</th><th scope="col">状态</th><th scope="col">得分</th><th scope="col">提示</th><th scope="col">操作</th></tr></thead><tbody>{visibleBatch.tasks.map((item) => <tr key={item.task_id}><td className="filename-cell" title={item.filename}>{item.filename}</td><td className="status-cell"><span className={`status-pill task-${item.status}`}>{taskLabels[item.status]}</span></td><td className="score-cell">{item.total_score === null ? "—" : item.total_score.toFixed(1)}</td><td className="hint-cell">{item.security_flag !== "none" ? <span className="table-warning"><CircleAlert size={14} />安全告警</span> : item.needs_review ? <span className="table-warning"><CircleAlert size={14} />重点复核</span> : "—"}</td><td className="row-action-cell"><button className="text-action" onClick={() => onOpenTask(item.task_id)}>打开作业<ArrowRight size={14} /></button></td></tr>)}</tbody></table></div>
        </> : <div className="quiet-empty monitor-empty"><FolderOpen size={29} /><p>{selectedBatchId ? "正在加载批次…" : "选择或新建批次"}</p></div>}
      </section>
      <footer className="workspace-footer"><span>阅见 · 批次管理</span><span>导出表包含草稿，每份作业仍需教师复核确认</span></footer>
    </main>
  );
}
