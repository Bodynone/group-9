"use client";

import { useEffect, useState } from "react";
import { v3, type Metrics, type RiskItem } from "@/lib/learning";

export function LearningResults({assignmentId,version,onOpen}:{assignmentId:string;version:string;onOpen:(id:string)=>Promise<void>}){
  const [metrics,setMetrics]=useState<Metrics|null>(null),[queue,setQueue]=useState<RiskItem[]>([]),[error,setError]=useState("");
  useEffect(()=>{let cancelled=false;Promise.all([v3<Metrics>(`assignments/${assignmentId}/metrics`),v3<{items:RiskItem[]}>(`assignments/${assignmentId}/review-queue`)]).then(([m,q])=>{if(!cancelled){setMetrics(m);setQueue(q.items);}}).catch(e=>{if(!cancelled)setError(e.message);});return()=>{cancelled=true;};},[assignmentId,version]);
  return <section className="v2-card" aria-label="争议队列与运行分析"><h2>争议队列与运行分析</h2>{error&&<p role="alert" className="v2-error">{error}</p>}<p>优先处理审校有分歧或失败的提交。排序只辅助教师安排复核，不改变任何分数。</p>
    <div className="v2-table-wrap"><table><thead><tr><th>待复核提交</th><th>优先级</th><th>审校分歧</th><th>待核查维度</th><th>操作</th></tr></thead><tbody>{queue.map(q=><tr key={q.id}><td>{q.submission_label}</td><td>{q.priority==="high"?"优先核查":"常规"}</td><td>{q.disputed_count}</td><td>{q.needs_review_count}</td><td><button onClick={()=>void onOpen(q.id)}>处理本份争议</button></td></tr>)}</tbody></table></div>{!queue.length&&<p>暂无待复核提交。</p>}
    {metrics&&<><h3>运行记录 · {metrics.total} 次任务，失败 {metrics.failed}，已确认 {metrics.confirmed}</h3><p>包含重试与修改稿。未配置模型单价时费用显示未知，教师改档数仅在保存复核后计算。</p><div className="v2-table-wrap"><table><thead><tr><th>任务</th><th>模型调用</th><th>输入 / 输出Token</th><th>检索次数</th><th>审校状态</th><th>教师改档数</th><th>排队 / 执行秒数</th><th>费用估算</th></tr></thead><tbody>{metrics.rows.map(r=><tr key={r.task_id}><td>{r.task_id.slice(0,8)}</td><td>{r.model_calls}</td><td>{r.prompt_tokens} / {r.completion_tokens}</td><td>{r.retrieval_count}</td><td>{r.audit_status}</td><td>{r.teacher_changed_dimensions??"尚未保存"}</td><td>{r.queue_seconds??"暂无"} / {r.runtime_seconds??"暂无"}</td><td>{r.cost_cny??"未知"}</td></tr>)}</tbody></table></div></>}
  </section>;
}
