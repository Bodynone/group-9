"use client";

import { useEffect, useRef, useState } from "react";
import { versionFields, type TaskV2 } from "@/lib/grading-v2";
import { v3, terminal, type Comparison, type LearningDetail, type Material, type MaterialMatch } from "@/lib/learning";

export function LearningReview({ task, onOpen, onCreated, reviewDirty, onDirty }: { task: TaskV2; onOpen: (id:string)=>Promise<void>; onCreated:(task:TaskV2)=>Promise<void>; reviewDirty:boolean; onDirty:(value:boolean)=>void }) {
  const [data,setData]=useState<LearningDetail|null>(null), [comparison,setComparison]=useState<Comparison|null>(null);
  const [note,setNote]=useState(""),[text,setText]=useState(""),[error,setError]=useState(""),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false);
  const [source,setSource]=useState<{doc:Material;match:MaterialMatch}|null>(null);
  const keys=useRef(new Map<string,string>());
  useEffect(()=>{ let cancelled=false; v3<LearningDetail>(`tasks/${task.id}/learning`).then(async value=>{if(cancelled)return;setData(value);if(value.revision){const c=await v3<Comparison>(`tasks/${task.id}/comparison`);if(!cancelled)setComparison(c);}else setComparison(null);}).catch(e=>{if(!cancelled)setError(e.message);});return()=>{cancelled=true;};},[task.id,task.status,task.review_revision]);
  useEffect(()=>{onDirty(!!note.trim()||!!text.trim());return()=>onDirty(false);},[note,text,onDirty]);
  async function act(work:()=>Promise<void>){setBusy(true);setError("");setNotice("");try{await work();}catch(e){setError(e instanceof Error?e.message:"请求失败");}finally{setBusy(false);}}
  if(!data) return null;
  const audit=data.audit, writable=task.status==="pending_review"&&!task.replaced_by;
  const name=(id:string)=>task.rubric_snapshot.dimensions.find(d=>d.id===id)?.name || id;
  const level=(id:string)=>task.rubric_snapshot.levels.find(d=>d.id===id)?.label || id;
  return <section className="v2-card" aria-label="审校与学习改进"><h2>审校与学习改进</h2>{error&&<p role="alert" className="v2-error">{error}</p>}<p role="status">{notice}</p>
    <p>{data.snapshot?`本提交：${data.snapshot.retrieval_enabled?"检索已开启":"检索未开启"}，${data.snapshot.audit_enabled?"独立审校已开启":"独立审校未开启"}`:"本提交使用原批改流程。可在任务设置中为之后的新提交开启资料检索和独立审校。"}</p>
    {audit&&<section className={audit.status==="failed"||audit.disputed_count?"v2-error":"v2-validation"}><h3>独立审校</h3><p>{audit.status==="completed"?`审校未读取首轮分数 · ${audit.disputed_count}项档位分歧 · 独立建议总分 ${audit.total}`:audit.message || "审校处理中"}</p>
      {audit.dimensions?.map(d=><details key={d.dimension_id}><summary>{name(d.dimension_id)} · {d.disputed?"有分歧":"档位一致"}</summary><p>首轮：{level(d.primary_level_id)}；审校：{level(d.level_id)}，{d.score}分</p><p>{d.reason}</p>{d.evidence.map((e,i)=><blockquote key={i}>学生原文：{e.quote}</blockquote>)}</details>)}
      {audit.acknowledgment&&<p>教师处理记录：{audit.acknowledgment.note}（复核修订 {audit.acknowledgment.review_revision}）</p>}
      {writable&&(audit.status==="failed"||!!audit.disputed_count)&&<><label>审校处理说明<textarea rows={3} maxLength={10000} value={note} onChange={e=>setNote(e.target.value)} placeholder="先保存逐项复核，再说明为何保留或调整档位" /></label><button disabled={busy||!note.trim()} onClick={()=>void act(async()=>{setData(await v3<LearningDetail>(`tasks/${task.id}/audit-acknowledgment`,"POST",{...versionFields(task),note}));setNote("");setNotice("审校处理已保存，若再修改复核档位，需要重新记录处理说明。");})}>保存审校处理说明</button></>}
    </section>}
    {data.retrievals.length>0&&<details><summary>查看课程资料检索依据（与学生证据分开）</summary>{data.retrievals.map((r,i)=><div key={i} className="learning-evidence"><h3>{name(r.dimension_id)} · 检索词：{r.query}</h3>{!r.matches.length&&<p>未找到相关片段，需教师核查专业结论。</p>}{r.matches.map((m,j)=><blockquote key={j}><p>{m.title} · 字符 {m.start}–{m.end}</p><p>{m.quote}</p><button disabled={busy} onClick={()=>void act(async()=>setSource({doc:await v3<Material>(`materials/${m.document_id}`),match:m}))}>定位课程资料</button></blockquote>)}</div>)}</details>}
    {source&&<section className="learning-source"><h3>{source.doc.title} · 课程资料原文</h3><pre className="v2-source">{Array.from(source.doc.text||"").slice(0,source.match.start).join("")}<mark>{Array.from(source.doc.text||"").slice(source.match.start,source.match.end).join("")}</mark>{Array.from(source.doc.text||"").slice(source.match.end).join("")}</pre><p className="v2-hash">文本版本：{source.match.content_hash}</p><button onClick={()=>setSource(null)}>关闭资料定位</button></section>}
    {terminal(task)&&<><h3>按评分判据整理的修改建议</h3><p>{data.provisional?"基于尚未确认的复核或草稿，建议仍需教师核查。":"基于教师确认结果。"}</p>{data.feedback.length?data.feedback.map(f=><details key={f.dimension_id}><summary>{f.name} · 下一档目标：{f.target_level}</summary><p>当前问题：{f.reason}</p><p>当前判据：{f.current_criterion}</p><p>修改时对照：{f.target_criterion}</p></details>):<p>当前没有可计算的下一档建议；教师仍可检查内容是否充分。</p>}
      {!task.replaced_by&&<details><summary>导入修改稿，比较两次提交</summary><p>沿用本提交的任务、评分标准和资料快照，原文及历史成绩继续保留。请先保存当前复核修改。</p><label>修改稿正文<textarea rows={7} maxLength={50000} value={text} onChange={e=>setText(e.target.value)} /></label><button disabled={busy||reviewDirty||!text.trim()} onClick={()=>void act(async()=>{const signature=task.id+text,key=keys.current.get(signature)||crypto.randomUUID();keys.current.set(signature,key);const next=await v3<TaskV2>(`tasks/${task.id}/revisions`,"POST",{text},key);keys.current.delete(signature);setText("");await onCreated(next);})}>提交修改稿并生成草稿</button></details>}
    </>}
    {comparison&&<section><h3>第{comparison.version_no}稿与上一稿对比</h3><button onClick={()=>void onOpen(comparison.previous_task_id)}>打开上一稿</button><p>{comparison.provisional?"含未确认评分，仅作临时比较":"两稿均为教师确认成绩"} · {comparison.comparable?`总分变化 ${comparison.total_delta??"尚无结果"}`:"评分依据不同，不能直接比较分数"}</p>
      <div className="v2-table-wrap"><table><thead><tr><th>维度</th><th>上一稿</th><th>当前稿</th><th>变化</th></tr></thead><tbody>{comparison.dimensions.map(d=><tr key={d.id}><td>{d.name}</td><td>{d.before}</td><td>{d.after}</td><td>{d.delta}</td></tr>)}</tbody></table></div>
      {comparison.changes.map((c,i)=><details key={i}><summary>{c.kind} · 原文{c.before_start}–{c.before_end}，修改稿{c.after_start}–{c.after_end}</summary><pre className="learning-before">{c.before_text||"（无）"}</pre><pre className="learning-after">{c.after_text||"（无）"}</pre>{c.snippet_truncated&&<p>本处只展示前2000字符，完整内容请打开对应提交。</p>}</details>)}{comparison.changes_truncated&&<p>仅展示前100处修改。</p>}</section>}
  </section>;
}
