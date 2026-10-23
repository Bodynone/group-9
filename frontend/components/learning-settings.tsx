"use client";

import { useEffect, useState } from "react";
import type { Assignment } from "@/lib/grading-v2";
import { v3, type Material, type Policy } from "@/lib/learning";

export function LearningSettings({ assignment, onDirty }: { assignment: Assignment; onDirty: (value: boolean) => void }) {
  const [documents, setDocuments] = useState<Material[]>([]), [policy, setPolicy] = useState<Policy | null>(null);
  const [saved, setSaved] = useState<Policy | null>(null), [file, setFile] = useState<File | null>(null), [title, setTitle] = useState("");
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false), [preview, setPreview] = useState<Material | null>(null);
  const [replace, setReplace] = useState("");
  useEffect(() => { let cancelled = false; Promise.all([v3<{items: Material[]}>(`courses/${assignment.course_id}/materials?include_archived=true`), v3<Policy>(`assignments/${assignment.id}/policy`)]).then(([d,p]) => { if (!cancelled) { setDocuments(d.items); setPolicy(p); setSaved(p); } }).catch(e => { if (!cancelled) setError(e.message); }); return () => { cancelled = true; }; }, [assignment.id, assignment.course_id]);
  useEffect(() => { onDirty(!!file || !!title || !!policy && !!saved && (policy.retrieval_enabled !== saved.retrieval_enabled || policy.audit_enabled !== saved.audit_enabled)); return () => onDirty(false); }, [file,title,policy,saved,onDirty]);
  async function act(work: () => Promise<void>) { setBusy(true); setError(""); setNotice(""); try { await work(); } catch(e) { setError(e instanceof Error ? e.message : "请求失败"); } finally { setBusy(false); } }
  async function refresh() { setDocuments((await v3<{items: Material[]}>(`courses/${assignment.course_id}/materials?include_archived=true`)).items); }
  return <section className="v2-card" aria-label="课程资料与批改策略"><h2>课程资料与批改策略</h2><p>先导入老师认可的课程资料，再按需开启检索和独立审校。策略只影响之后的新提交，历史任务保留原资料快照。</p>
    {error && <p role="alert" className="v2-error">{error}</p>}<p role="status">{notice}</p>
    <details><summary>管理本课程的教学资料 · {documents.filter(d=>!d.archived).length} 份在用</summary>
      <p>支持UTF-8 TXT / MD、DOCX、文本PDF。每份最多2MB、提取文本10万字符，PDF最多30页。扫描图片需先转换为文本。</p>
      <label>资料名称<input value={title} maxLength={200} onChange={e=>setTitle(e.target.value)} placeholder="留空时使用文件名" /></label>
      <label>导入教学资料<input type="file" accept=".txt,.md,.docx,.pdf" disabled={busy} onChange={e=>{setFile(e.target.files?.[0] || null);e.target.value="";}} /></label>{file&&<p>已选择：{file.name}</p>}
      <label>资料版本<select value={replace} onChange={e=>setReplace(e.target.value)}><option value="">作为新资料导入</option>{documents.filter(d=>!d.archived).map(d=><option key={d.id} value={d.id}>替换 {d.title} · v{d.version_no}（旧版本归档保留）</option>)}</select></label>
      <button disabled={busy || !file} onClick={()=>void act(async()=>{ if(!file) return; if(file.size>2000000) throw new Error("资料文件最多2MB"); const bytes=new Uint8Array(await file.arrayBuffer()); let binary=""; for(let i=0;i<bytes.length;i+=16384) binary+=String.fromCharCode(...bytes.subarray(i,i+16384)); await v3(`courses/${assignment.course_id}/materials`,"POST",{title:title || file.name, filename:file.name,content_base64:btoa(binary),replaces_id:replace || null}); setFile(null);setTitle("");setReplace("");await refresh();setNotice("资料已导入。可查看提取文本，检查后用于新提交。"); })}>导入课程资料</button>
      <div className="v2-table-wrap"><table><thead><tr><th>资料</th><th>版本与状态</th><th>操作</th></tr></thead><tbody>{documents.map(d=><tr key={d.id}><td>{d.title}<small>{d.characters} 字符</small></td><td>v{d.version_no} · {d.archived?"已归档":"在用"}</td><td><button disabled={busy} onClick={()=>void act(async()=>setPreview(await v3<Material>(`materials/${d.id}`)))}>查看资料</button> <button disabled={busy} onClick={()=>void act(async()=>{await v3(`materials/${d.id}`,"PATCH",{expected_revision:d.revision,archived:!d.archived});await refresh();})}>{d.archived?"恢复资料":"归档资料"}</button></td></tr>)}</tbody></table></div>
      {preview && <section className="learning-source"><h3>{preview.title} · 提取文本</h3><p className="v2-hash">文本SHA-256：{preview.content_hash}</p><p className="v2-hash">原文件SHA-256：{preview.file_hash}</p><a href={`/api/v3/materials/${preview.id}/file`} download>下载原始资料</a><pre className="v2-source">{preview.text}</pre><button onClick={()=>setPreview(null)}>关闭资料预览</button></section>}
    </details>
    {policy && <fieldset disabled={busy}><label className="v2-checkbox"><input type="checkbox" checked={policy.retrieval_enabled} onChange={e=>setPolicy({...policy,retrieval_enabled:e.target.checked})} />按评分维度检索课程资料（BM25）</label><label className="v2-checkbox"><input type="checkbox" checked={policy.audit_enabled} onChange={e=>setPolicy({...policy,audit_enabled:e.target.checked})} />启用独立审校，优先复核档位分歧</label>
      <button onClick={()=>void act(async()=>{const p=await v3<Policy>(`assignments/${assignment.id}/policy`,"PUT",{expected_revision:policy.revision,retrieval_enabled:policy.retrieval_enabled,audit_enabled:policy.audit_enabled});setPolicy(p);setSaved(p);setNotice("策略已保存，仅用于之后的新提交。");})}>保存批改策略</button></fieldset>}
  </section>;
}
