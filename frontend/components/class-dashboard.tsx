"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight, BarChart3, CircleAlert, ClipboardList, RefreshCw, ShieldAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { errorMessage, getBatch, getClassAnalytics, type ClassAnalytics, type RadarDimension } from "@/lib/grading";

type Props = {
  active: boolean;
  selectedBatchId: string | null;
  onShowUploader: () => void;
  onOpenTask: (taskId: string) => void;
};

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function score(value: number | null) {
  return value === null ? "—" : value.toFixed(1);
}

function radarPoint(index: number, ratio: number) {
  const angle = index * Math.PI / 3 - Math.PI / 2;
  return { x: 200 + Math.cos(angle) * 132 * ratio, y: 200 + Math.sin(angle) * 132 * ratio };
}

function points(ratios: number[]) {
  return ratios.map((ratio, index) => {
    const point = radarPoint(index, ratio);
    return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
  }).join(" ");
}

function RadarChart({ dimensions, hasScores }: { dimensions: RadarDimension[]; hasScores: boolean }) {
  const ordered = ["A", "B", "C", "D", "E", "F"].map((id) => dimensions.find((item) => item.dimension === id));
  const rates = ordered.map((item) => Math.max(0, Math.min(1, item?.scoring_rate ?? 0)));
  return (
    <div className="radar-layout">
      <div className="radar-plot">
        <svg viewBox="0 0 400 400" role="img" aria-label={hasScores ? "班级六维能力平均得分率雷达图" : "等待评分数据的六维雷达图"}>
          <title>六维能力得分率</title>
          <defs><linearGradient id="class-radar-fill" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stopColor="#8dc9d7" stopOpacity="0.55" /><stop offset="100%" stopColor="#497fa4" stopOpacity="0.23" /></linearGradient></defs>
          {[0.25, 0.5, 0.75, 1].map((ratio) => <polygon key={ratio} points={points(Array(6).fill(ratio))} className="radar-ring" />)}
          {ordered.map((item, index) => { const end = radarPoint(index, 1); return <line key={item?.dimension ?? index} x1="200" y1="200" x2={end.x} y2={end.y} className="radar-axis" />; })}
          {hasScores && <><polygon points={points(rates)} className="radar-data" />{rates.map((ratio, index) => { const point = radarPoint(index, ratio); return <circle key={index} cx={point.x} cy={point.y} r="4" className="radar-dot" />; })}</>}
          {ordered.map((item, index) => { const label = radarPoint(index, 1.23); return <text key={item?.dimension ?? index} x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" className="radar-label">{item?.dimension ?? ""}</text>; })}
        </svg>
        {!hasScores && <span className="radar-empty-label">等待批改结果</span>}
      </div>
      <ul className="radar-legend">{ordered.map((item) => item && <li key={item.dimension}><span className="dimension-letter">{item.dimension}</span><span className="radar-dimension-name">{item.name}<small>均分 {hasScores ? score(item.average_score) : "—"} / {item.full_score}</small></span><strong>{hasScores ? percent(item.scoring_rate) : "—"}</strong></li>)}</ul>
    </div>
  );
}

export function ClassDashboard({ active, selectedBatchId, onShowUploader, onOpenTask }: Props) {
  const [analytics, setAnalytics] = useState<ClassAnalytics | null>(null);
  const [batchName, setBatchName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!active || !selectedBatchId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const [next, batch] = await Promise.all([getClassAnalytics(selectedBatchId!), getBatch(selectedBatchId!)]);
        if (cancelled) return;
        setAnalytics(next);
        setBatchName(batch.name);
        setError(null);
        if (batch.status !== "queued" && batch.status !== "running") return;
      } catch (reason) {
        if (cancelled) return;
        setError(errorMessage(reason));
      }
      if (!cancelled) timer = setTimeout(refresh, 1500);
    }
    void refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [active, selectedBatchId, revision]);

  const data = analytics?.batch_id === selectedBatchId ? analytics : null;
  const hasScores = !!data && data.summary.analyzed_count > 0;
  const metrics = data ? [
    { label: "班级均分", value: score(data.summary.average_score), suffix: "/ 100" },
    { label: "及格率", value: hasScores ? percent(data.summary.pass_rate) : "—", suffix: "" },
    { label: "优秀率", value: hasScores ? percent(data.summary.excellent_rate) : "—", suffix: "" },
    { label: "最高分", value: score(data.summary.max_score), suffix: "" },
    { label: "最低分", value: score(data.summary.min_score), suffix: "" },
  ] : [];

  return (
    <main className="workspace analytics-page">
      <section className="page-intro analytics-intro"><div><div className="eyebrow">班级作业 / 学情诊断</div><h1>班级学情大屏</h1><p>{data ? `${batchName ?? "当前批次"} · 已分析 ${data.summary.analyzed_count} / ${data.summary.total_submitted} 份` : "汇总六维能力、共性问题与安全告警。"}</p></div><div className="intro-actions"><Button variant="outline" onClick={onShowUploader}><ClipboardList size={16} />选择批次</Button>{selectedBatchId && <button className="icon-action" title="刷新学情" aria-label="刷新学情" onClick={() => setRevision((value) => value + 1)}><RefreshCw size={17} /></button>}</div></section>

      {error && <p className="inline-alert" role="alert"><CircleAlert size={16} />学情读取失败：{error}<button onClick={() => setRevision((value) => value + 1)}>重试</button></p>}
      {!selectedBatchId ? <section className="dashboard-empty"><BarChart3 size={38} /><h2>尚未选择批次</h2><Button onClick={onShowUploader}>前往批次管理<ArrowRight size={16} /></Button></section> : !data ? <section className="dashboard-empty"><BarChart3 size={38} /><h2>{error ? "暂时无法显示学情" : "正在读取学情…"}</h2></section> : <>
        <section className="metric-band" aria-label="班级统计指标">{metrics.map((item) => <div key={item.label} className="metric-item"><span>{item.label}</span><strong>{item.value}<small>{item.suffix}</small></strong></div>)}</section>

        <section className="radar-section" aria-labelledby="radar-title"><div className="surface-heading"><div><span className="section-kicker">01 / 能力分布</span><h2 id="radar-title">六维能力得分率</h2></div><span className="surface-meta">基于 {data.summary.analyzed_count} 份已分析作业</span></div><RadarChart dimensions={data.radar} hasScores={hasScores} /></section>

        <div className="diagnosis-grid">
          <section className="diagnosis-section" aria-labelledby="weakness-title"><div className="surface-heading"><div><span className="section-kicker">02 / 教学诊断</span><h2 id="weakness-title">共性薄弱项</h2></div><span className="surface-meta">TOP 3</span></div>{data.common_weaknesses.length ? <ol className="weakness-list">{data.common_weaknesses.slice(0, 3).map((item) => <li key={`${item.rank}-${item.title}`} className={`weakness-rank-${item.rank}`}><span className="weakness-rank">{String(item.rank).padStart(2, "0")}</span><div><div className="weakness-title"><strong>{item.title}</strong><span>{item.dimension} 维 · {item.affected_count} 人 / {percent(item.percentage)}</span></div><p>{item.recommendation}</p></div></li>)}</ol> : <div className="quiet-empty"><p>{hasScores ? "暂无聚合出的共性薄弱项" : "待作业分析后生成诊断"}</p></div>}</section>

          <section className="diagnosis-section security-section" aria-labelledby="security-title"><div className="surface-heading"><div><span className="section-kicker">03 / 安全核查</span><h2 id="security-title">作业安全告警</h2></div><span className="alert-count">{data.security_alerts.length}</span></div>{data.security_alerts.length ? <ul className="security-list">{data.security_alerts.map((item) => <li key={item.task_id}><ShieldAlert size={18} /><div><strong>{item.filename}</strong><p>{item.detail}</p><button className="text-action" onClick={() => onOpenTask(item.task_id)}>打开作业<ArrowRight size={14} /></button></div></li>)}</ul> : <div className="quiet-empty"><p>当前无安全告警</p></div>}</section>
        </div>
      </>}
      <footer className="workspace-footer"><span>阅见 · 班级学情</span><span>临时统计包含待确认草稿，随教师复核更新</span></footer>
    </main>
  );
}
