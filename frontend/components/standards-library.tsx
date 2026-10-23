"use client";

import { useEffect, useState } from "react";
import { RubricEditor } from "@/components/rubric-editor";
import { RubricLifecycle, type RubricAction } from "@/components/rubric-lifecycle";
import { RubricPreview } from "@/components/rubric-preview";
import { databaseExample, v2, type Definition, type RubricVersion } from "@/lib/grading-v2";

export function StandardsLibrary({ versions, reload, onDirty, onTasks, initialVersion }: {
  versions: RubricVersion[]; reload: () => Promise<void>; onDirty: (value: boolean) => void; onTasks: (versionId?: string) => void; initialVersion?: string;
}) {
  const [version, setVersion] = useState<RubricVersion | null>(null);
  const [definition, setDefinition] = useState<Definition | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const dirty = !!version && !!definition && JSON.stringify(version.definition) !== JSON.stringify(definition);
  useEffect(() => { let cancelled = false; if (initialVersion) void v2<RubricVersion>(`rubric-versions/${initialVersion}`).then(item => { if (!cancelled) { setVersion(item); setDefinition(item.definition); } }).catch(e => { if (!cancelled) setError(e.message); }); return () => { cancelled = true; }; }, [initialVersion]);
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  async function act(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); return true; } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); return false; } finally { setBusy(false); }
  }
  async function select(id: string) {
    const item = await v2<RubricVersion>(`rubric-versions/${id}`); setVersion(item); setDefinition(item.definition); setConfirming(false);
  }
  function selectSafely(id: string) {
    if (dirty && !window.confirm("当前标准有未保存修改，放弃修改并切换？")) return;
    void act(() => select(id));
  }
  async function manage(action: RubricAction) {
    if (!version) return false;
    return act(async () => {
      const series = action.endsWith("series"), path = series ? `rubrics/${version.rubric_id}` : `rubric-versions/${version.id}`;
      await v2(action === "delete" ? path : `${path}/${action.split("-")[0]}`, action === "delete" ? "DELETE" : "POST", { expected_revision: series ? version.rubric_revision : version.revision });
      await reload();
      if (action === "delete") { setVersion(null); setDefinition(null); setNotice("量表草稿已删除，历史评分未改动。"); }
      else { setShowArchived(true); await select(version.id); setNotice(action.startsWith("archive") ? "已归档，已有作业和评分记录保持不变。" : "已恢复，请按版本状态选择使用。"); }
    });
  }
  return <>
    <div className="v2-page-heading"><div><h1>评分标准库</h1><p>标准可复用到多个作业任务。这里查看或修改标准，不会改变已发布任务的绑定。</p></div>
      <button className="v2-primary" disabled={busy} onClick={() => setCreating(!creating)}>新建评分标准</button></div>
    <div role="status">{notice}</div>{error && <p role="alert" className="v2-error">{error}</p>}
    {creating && <section className="v2-card"><form onSubmit={e => { e.preventDefault(); if (dirty && !window.confirm("当前标准有未保存修改，放弃修改并新建？")) return; const title = String(new FormData(e.currentTarget).get("title")); void act(async () => { const item = await v2<{ draft: RubricVersion }>("rubrics", "POST", { title }); setVersion(item.draft); setDefinition(item.draft.definition); setCreating(false); await reload(); }); }}>
      <label>新量表名称<input name="title" required maxLength={200} placeholder="例如：数据库实验报告" /></label><button disabled={busy}>创建标准草稿</button></form></section>}
    <section className="v2-card" aria-label="评分标准列表"><label className="v2-checkbox"><input type="checkbox" disabled={busy} checked={showArchived} onChange={e => { setShowArchived(e.target.checked); if (!e.target.checked && (version?.archived || version?.rubric_archived)) { setVersion(null); setDefinition(null); } }} />显示已归档量表</label>
      <div className="v2-table-wrap"><table><thead><tr><th>标准名称</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>
        {versions.filter(v => showArchived || (!v.archived && !v.rubric_archived)).map(v => <tr key={v.id} data-version-id={v.id} className={version?.id === v.id ? "is-current" : undefined}><td>{v.definition.title}</td><td>v{v.version_no}</td><td>{v.archived || v.rubric_archived ? "已归档" : v.state === "published" ? "已发布" : "草稿"}</td><td><button disabled={busy} onClick={() => selectSafely(v.id)}>{version?.id === v.id ? "正在查看" : v.state === "draft" ? "编辑草稿" : "查看标准"}</button></td></tr>)}
      </tbody></table></div>
    </section>
    {version && definition && <>
      <div className="v2-editor-heading"><h2>当前标准：{definition.title} · v{version.version_no}</h2><span role="status">{dirty ? "有未保存修改" : "已保存"}</span></div>
      {version.state === "published" && <div className="v2-actions"><button disabled={busy || version.archived || version.rubric_archived} onClick={() => void act(async () => { const copied = await v2<RubricVersion>(`rubrics/${version.rubric_id}/versions`, "POST", { source_version_id: version.id }); setVersion(copied); setDefinition(copied.definition); await reload(); })}>复制为新版本</button><button disabled={busy || version.archived || version.rubric_archived} onClick={() => onTasks(version.id)}>前往作业任务使用此标准</button></div>}
      <div className="v2-detail-grid"><RubricEditor version={version} definition={definition} busy={busy} dirty={dirty} onChange={setDefinition}
        onSave={() => void act(async () => { const saved = await v2<RubricVersion>(`rubric-versions/${version.id}`, "PATCH", { expected_revision: version.revision, definition }); setVersion(saved); setDefinition(saved.definition); await reload(); setNotice(saved.publishable ? "标准已保存，校验通过，可以预览发布。" : "草稿已保存，请根据提示完善判据与分值。"); })}
        onPublish={() => setConfirming(true)} onExample={() => setDefinition(structuredClone(databaseExample))} />
        <RubricPreview definition={definition} total={version.total_score} dirty={dirty} /></div>
      {confirming && <section role="dialog" aria-label="发布标准前确认" className="v2-card"><h2>确认发布评分标准</h2><p>{definition.title} · v{version.version_no}，发布后内容只读。已有任务继续使用各自原版本。</p>
        <div className="v2-actions"><button disabled={busy || dirty || !version.publishable} onClick={() => void act(async () => { const saved = await v2<RubricVersion>(`rubric-versions/${version.id}/publish`, "POST", { expected_revision: version.revision }); setVersion(saved); setDefinition(saved.definition); setConfirming(false); await reload(); setNotice("量表已发布，已有任务快照不会随新版本变化。"); })}>确认发布标准</button><button disabled={busy} onClick={() => setConfirming(false)}>返回编辑</button></div></section>}
      <details className="v2-card"><summary>更多管理操作</summary><RubricLifecycle key={version.id} version={version} busy={busy || dirty} onAction={manage} /></details>
    </>}
  </>;
}
