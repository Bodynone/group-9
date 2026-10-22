"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { BarChart3, BookOpenCheck, Files } from "lucide-react";
import { BatchUploader } from "@/components/batch-uploader";
import { ClassDashboard } from "@/components/class-dashboard";
import { GradingWorkspace } from "@/components/grading-workspace";

type Tab = "single" | "batch" | "analytics";
const tabs = [
  { id: "single", label: "单份精细批改", icon: BookOpenCheck },
  { id: "batch", label: "批量摄取与队列", icon: Files },
  { id: "analytics", label: "班级学情大屏", icon: BarChart3 },
] as const;
const TAB_KEY = "yuejian.active-tab";
const BATCH_KEY = "yuejian.latest-batch";

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("single");
  const [ready, setReady] = useState(false);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskOpenRevision, setTaskOpenRevision] = useState(0);

  useEffect(() => {
    const restore = setTimeout(() => {
      try {
        const savedTab = localStorage.getItem(TAB_KEY);
        if (savedTab === "single" || savedTab === "batch" || savedTab === "analytics") setActiveTab(savedTab);
        setSelectedBatchId(localStorage.getItem(BATCH_KEY));
      } catch { /* Browser storage is optional. */ }
      setReady(true);
    }, 0);
    return () => clearTimeout(restore);
  }, []);

  useEffect(() => {
    if (!ready) return;
    try { localStorage.setItem(TAB_KEY, activeTab); } catch { /* Navigation still works. */ }
  }, [activeTab, ready]);

  function selectBatch(batchId: string) {
    setSelectedBatchId(batchId);
    try { localStorage.setItem(BATCH_KEY, batchId); } catch { /* In-memory selection still works. */ }
  }

  function openTask(taskId: string) {
    setSelectedTaskId(taskId);
    setTaskOpenRevision((value) => value + 1);
    setActiveTab("single");
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, current: number) {
    const next = event.key === "ArrowRight" ? (current + 1) % tabs.length
      : event.key === "ArrowLeft" ? (current + tabs.length - 1) % tabs.length
        : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    setActiveTab(tabs[next].id);
    document.getElementById(`tab-${tabs[next].id}`)?.focus();
  }

  return (
    <div className="workspace-shell">
      <header className="site-header app-header">
        <div className="brand"><span className="brand-symbol"><BookOpenCheck size={24} /></span><span>阅见 <span className="brand-divider">/</span> <span className="brand-subtitle">教师工作台</span></span></div>
        <nav className="app-tabs" role="tablist" aria-label="教师工作台视图">{tabs.map((tab, index) => { const Icon = tab.icon; return <button type="button" role="tab" id={`tab-${tab.id}`} aria-controls={`panel-${tab.id}`} aria-selected={activeTab === tab.id} tabIndex={activeTab === tab.id ? 0 : -1} className={activeTab === tab.id ? "is-active" : ""} key={tab.id} onClick={() => setActiveTab(tab.id)} onKeyDown={(event) => onTabKeyDown(event, index)}><Icon size={17} /><span>{tab.label}</span></button>; })}</nav>
        <Link href="/v2" className="brand-subtitle">课程与评分标准 →</Link>
      </header>
      <div id="panel-single" role="tabpanel" aria-labelledby="tab-single" hidden={activeTab !== "single"}><GradingWorkspace selectedTaskId={selectedTaskId} taskOpenRevision={taskOpenRevision} /></div>
      <div id="panel-batch" role="tabpanel" aria-labelledby="tab-batch" hidden={activeTab !== "batch"}><BatchUploader active={activeTab === "batch"} selectedBatchId={selectedBatchId} onSelectBatch={selectBatch} onOpenTask={openTask} onShowAnalytics={() => setActiveTab("analytics")} /></div>
      <div id="panel-analytics" role="tabpanel" aria-labelledby="tab-analytics" hidden={activeTab !== "analytics"}><ClassDashboard active={activeTab === "analytics"} selectedBatchId={selectedBatchId} onShowUploader={() => setActiveTab("batch")} onOpenTask={openTask} /></div>
    </div>
  );
}
