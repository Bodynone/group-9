import type { Evidence, TaskV2 } from "./grading-v2";

export async function v3<T>(path: string, method = "GET", body?: unknown, key?: string): Promise<T> {
  const response = await fetch(`/api/v3/${path}`, { method, cache: "no-store", headers: { "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `请求失败（${response.status}）`);
  return data as T;
}
export type Material = { id: string; title: string; filename: string; revision: number; version_no: number; archived: boolean; characters: number; content_hash: string; file_hash: string; text?: string };
export type Policy = { revision: number; retrieval_enabled: boolean; audit_enabled: boolean };
export type MaterialMatch = { document_id: string; title: string; content_hash: string; start: number; end: number; quote: string; retrieval_score: number };
export type Audit = { status: string; total?: string; blind?: boolean; disputed_count?: number; message?: string; acknowledgment?: { note: string; review_revision: number } | null; dimensions?: { dimension_id: string; level_id: string; primary_level_id: string; disputed: boolean; reason: string; score: string; evidence: Evidence[] }[] };
export type LearningDetail = { task_id: string; snapshot: null | { snapshot_hash: string; retrieval_enabled: boolean; audit_enabled: boolean }; retrievals: { dimension_id: string; query: string; matches: MaterialMatch[] }[]; audit?: Audit; feedback: { dimension_id: string; name: string; reason: string; current_criterion: string; target_level: string; target_criterion: string; source: string }[]; provisional: boolean; revision: null | { previous_task_id: string; version_no: number } };
export type Comparison = { previous_task_id: string; version_no: number; comparable: boolean; provisional: boolean; total_delta: string | null; dimensions: { id: string; name: string; before: string | null; after: string | null; delta: string | null }[]; changes: { kind: string; before_start: number; before_end: number; after_start: number; after_end: number; before_text: string; after_text: string; snippet_truncated: boolean }[]; changes_truncated: boolean };
export type LabelChoice = { dimension_id: string; level_id: string };
export type HumanLabel = { reviewer_id: string; dimensions: LabelChoice[]; total: string; note: string };
export type Suite = { id: string; name: string; revision: number; library: { documents: unknown[] }; samples: { task_id: string; submission_label: string; ballots: HumanLabel[]; reference: HumanLabel | null }[] };
export type Experiment = { id: string; status: string; eligible: number; excluded: number; planned_trials: number; rows: { task_id: string; condition: string; success: boolean; seconds: number; model_calls: number; absolute_score_error: string | null; prompt_tokens: number; completion_tokens: number; cost_cny: string | null; learning?: { audit?: Audit } }[]; summary: Record<string, { attempted: number; completed: number; failed: number; agreement_all_attempts_percent: string | null; mean_absolute_error_successes: string | null; mae_denominator: number; mean_seconds: number; audit_disputed_trials?: number; audit_failures?: number }>; error?: string };
export type Metrics = { total: number; failed: number; confirmed: number; rows: { task_id: string; status: string; model_calls: number; prompt_tokens: number; completion_tokens: number; cost_cny: string | null; retrieval_count: number; audit_status: string; teacher_changed_dimensions: number | null; queue_seconds?: number | null; runtime_seconds?: number | null }[] };
export type RiskItem = { id: string; submission_label: string; priority: string; disputed_count: number; needs_review_count: number; audit_status: string };
export const terminal = (task: TaskV2) => ["pending_review", "confirmed"].includes(task.status);
