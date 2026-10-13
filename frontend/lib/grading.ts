export type DimensionId = "A" | "B" | "C" | "D" | "E" | "F";
export type Level = 100 | 70 | 30 | 0;
export type Rubric = {
  version: string;
  dimensions: { id: DimensionId; name: string; max_score: number; criteria: string | Record<string, string> }[];
  levels: Level[];
};
export type Evidence = { quote: string; paragraph: number; start: number; end: number };
export type ReviewDimension = {
  id: DimensionId;
  level: Level | null;
  score: number | null;
  reason: string;
  reviewed: boolean;
};
export type Task = {
  id: string;
  status: "queued" | "running" | "pending_review" | "failed" | "confirmed";
  source: "agent" | "manual";
  text: string;
  input_version: string;
  rubric_version: string;
  created_at: string;
  updated_at: string;
  parent_id: string | null;
  draft: null | {
    dimensions: {
      id: DimensionId; level: Level; score: number; reason: string; evidence: Evidence[];
      needs_review: boolean; review_note: string;
    }[];
    total: number;
    status: "draft";
    rubric_version: string;
    input_version: string;
  };
  review: null | { dimensions: ReviewDimension[]; total: number | null };
  trace: {
    sequence: number; kind: string; tool: string | null; round: number;
    validation_count: number; model_calls: number; details: Record<string, unknown>; created_at: string;
  }[];
  error: null | { code: string; message: string; tool?: string };
  repair_rounds: number;
  validation_count: number;
  model_calls: number;
  record_id: string | null;
};

export const dimensionIds: DimensionId[] = ["A", "B", "C", "D", "E", "F"];

export function reviewForTask(task: Task): ReviewDimension[] {
  return dimensionIds.map((id) => {
    const saved = task.review?.dimensions.find((dimension) => dimension.id === id);
    if (saved) return { ...saved };
    const suggestion = task.draft?.dimensions.find((dimension) => dimension.id === id);
    return { id, level: suggestion?.level ?? null, score: suggestion?.score ?? null, reason: suggestion?.reason ?? "", reviewed: false };
  });
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}），请稍后重试。`;
    try {
      const error = await response.json();
      if (typeof error.detail === "string") message = error.detail;
      else if (typeof error.message === "string") message = error.message;
      else if (Array.isArray(error.detail)) message = "提交内容不完整，请检查各维度的档位和理由。";
    } catch { /* A proxy may return a non-JSON response. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "连接失败，请检查服务后重试。";
}

/** Server offsets count Unicode codepoints; DOM text selection counts UTF-16 units. */
export function selectionOffset(text: string, offset: number): number {
  return Array.from(text).slice(0, offset).join("").length;
}
