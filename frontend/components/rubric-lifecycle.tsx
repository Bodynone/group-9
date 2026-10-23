"use client";

import { useState } from "react";
import type { RubricVersion } from "@/lib/grading-v2";

export type RubricAction = "delete" | "archive" | "restore" | "archive-series" | "restore-series";
const labels: Record<RubricAction, string> = {
  delete: "删除当前草稿", archive: "归档当前版本", restore: "恢复当前版本",
  "archive-series": "归档整个量表系列", "restore-series": "恢复整个量表系列",
};

export function RubricLifecycle({ version, busy, onAction }: {
  version: RubricVersion; busy: boolean; onAction: (action: RubricAction) => Promise<boolean>;
}) {
  const [pending, setPending] = useState<RubricAction | null>(null);
  return <div className="v2-lifecycle">
    <p>操作范围：当前版本 v{version.version_no}，或包含全部版本的量表系列。</p>
    {(version.archived || version.rubric_archived) && <p className="v2-error">
      {version.rubric_archived ? "整个量表系列已归档，请先恢复系列。" : "当前版本已归档。"}归档标准不用于新建作业，已有作业与评分记录保留。
    </p>}
    <div className="v2-actions">
      {version.state === "draft" && <button type="button" disabled={busy} onClick={() => setPending("delete")}>删除当前草稿</button>}
      <button type="button" disabled={busy || !!version.rubric_archived} onClick={() => setPending(version.archived ? "restore" : "archive")}>
        {version.archived ? labels.restore : labels.archive}
      </button>
      <button type="button" disabled={busy} onClick={() => setPending(version.rubric_archived ? "restore-series" : "archive-series")}>
        {version.rubric_archived ? labels["restore-series"] : labels["archive-series"]}
      </button>
    </div>
    {pending && <div role="alertdialog" aria-label="确认量表管理操作" className="v2-validation">
      <strong>{labels[pending]}：{version.definition.title}{pending.endsWith("series") ? "（全部版本）" : `（v${version.version_no}）`}</strong>
      <p>{pending === "delete" ? "仅允许删除未被引用的草稿。删除后不再显示，也不能继续编辑；已发布版本不能删除。"
        : pending.startsWith("archive") ? "归档后退出默认列表和新建作业的标准选项，可通过显示已归档量表恢复。已有作业、任务和确认记录不受影响。"
          : "恢复后重新进入可用列表。恢复系列不会自动取消各版本自身的归档状态。"}</p>
      <div className="v2-actions"><button type="button" disabled={busy} onClick={() => void onAction(pending).then(ok => { if (ok) setPending(null); })}>确认{labels[pending]}</button>
        <button type="button" disabled={busy} onClick={() => setPending(null)}>取消操作</button></div>
    </div>}
  </div>;
}
