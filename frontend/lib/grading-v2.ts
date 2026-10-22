export type Definition = {
  title: string; total_score: string;
  levels: { id: string; label: string; percent: string }[];
  dimensions: { id: string; name: string; description: string; max_score: string; criteria: Record<string, string> }[];
};
export type RubricVersion = {
  id: string; rubric_id: string; state: "draft" | "published"; revision: number; version_no: number;
  definition: Definition; content_hash: string | null; publishable: boolean;
  total_score: string; field_errors: { field: string; message: string }[];
};
export type Course = { id: string; name: string };
export type Assignment = {
  id: string; course_id: string; title: string; instructions: string; reference_text: string;
  rubric_version_id: string; state: "draft" | "published"; revision: number;
};
export type Review = { dimension_id: string; level_id: string | null; score: string | null; reason: string; reviewed: boolean };
export type Evidence = { quote: string; start: number; end: number; paragraph: number };
export type TaskV2 = {
  id: string; status: "queued" | "running" | "pending_review" | "failed" | "confirmed";
  text: string; submission_label: string; input_version: string; rubric_hash: string; context_hash: string;
  rubric_version_id: string; rubric_snapshot: Definition; assignment_snapshot: { id?: string; course_id?: string; title: string; instructions: string; reference_text: string };
  review_revision: number; source: string; model_calls: number; repair_rounds: number;
  security_detail?: string; error: null | { code: string; message: string };
  draft: null | { total: string; dimensions: (Review & { evidence: Evidence[]; needs_review: boolean; review_note: string })[] };
  review: null | { total: string | null; dimensions: Review[] };
};
export type BatchV2 = {
  id: string; name: string; status: string; assignment_id: string; total_count: number; finished_count: number;
  confirmed_count: number; failed_count: number;
  items: { task_id: string; submission_label: string; filename: string; status: string; total: string | null }[];
};
export type AnalyticsV2 = {
  basis: string; provisional: boolean; submitted: number; analyzed: number; confirmed: number; excluded: number;
  average_score: string | null;
  dimensions: { id: string; name: string; max_score: string; average_score: string | null; scoring_rate: string | null }[];
  rows: { task_id: string; submission_label: string; source: string; total: string }[];
  common_weaknesses: { dimension_id: string; name: string; affected_count: number; reasons: { submission_label: string; reason: string }[] }[];
};

export async function v2<T>(path: string, method = "GET", body?: unknown, key?: string): Promise<T> {
  const response = await fetch(`/api/v2/${path}`, {
    method, cache: "no-store", headers: { "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || `请求失败（${response.status}）`);
  return result as T;
}

export function versionFields(task: TaskV2) {
  return { input_version: task.input_version, rubric_hash: task.rubric_hash, context_hash: task.context_hash, expected_review_revision: task.review_revision };
}

export const databaseExample: Definition = {
  title: "数据库实验报告（教学示例，需教师确认）", total_score: "100.00",
  levels: [{ id: "excellent", label: "充分达成", percent: "100.00" }, { id: "basic", label: "基本达成", percent: "70.00" },
    { id: "partial", label: "部分达成", percent: "30.00" }, { id: "missing", label: "未达成", percent: "0.00" }],
  dimensions: [
    { id: "sql_correctness", name: "SQL 正确性", description: "按查询要求评价文本逻辑；不执行 SQL", max_score: "40.00", criteria: { excellent: "查询齐全、逻辑与结果说明一致，包含边界说明", basic: "主要查询成立，局部边界遗漏", partial: "仅部分查询可解释，关键逻辑缺项", missing: "未提供查询正确性内容" } },
    { id: "procedure", name: "实验过程", description: "步骤与关键操作的可复现程度", max_score: "30.00", criteria: { excellent: "环境、步骤、关键操作完整可复现", basic: "主流程完整，少量步骤缺说明", partial: "步骤零散，无法完整复现", missing: "未提供实验过程" } },
    { id: "analysis", name: "结果分析", description: "分析与结果对应并解释限制", max_score: "20.00", criteria: { excellent: "有结果对应、原因解释和限制分析", basic: "结果对应，解释深度不足", partial: "主要复述现象，依据不足", missing: "未提供结果分析" } },
    { id: "writing", name: "表达规范", description: "结构与术语是否清楚", max_score: "10.00", criteria: { excellent: "结构清楚、术语一致、引用完整", basic: "整体清楚，局部不一致", partial: "表达明显影响理解", missing: "没有可判读的报告" } },
  ],
};
