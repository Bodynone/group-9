import { v2 } from "@/lib/grading-v2";

export async function allV2<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await v2<{ items: T[]; total: number }>(`${path}${path.includes("?") ? "&" : "?"}limit=100&offset=${offset}`);
    items.push(...page.items);
    if (!page.items.length || items.length >= page.total) return items;
  }
}
