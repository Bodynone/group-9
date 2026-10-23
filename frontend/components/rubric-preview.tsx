import type { Definition } from "@/lib/grading-v2";

export function RubricPreview({ definition, total, dirty = false }: { definition: Definition; total?: string; dirty?: boolean }) {
  return <section className="v2-card rubric-preview" aria-label="评分标准预览">
    <h2>评分表预览</h2><h3>{definition.title}</h3>
    <p>{dirty ? "预览包含未保存修改；合计以保存后的服务端校验为准。" : `服务端合计：${total || definition.total_score} / 100.00`}</p>
    <div className="v2-table-wrap"><table><thead><tr><th>评价维度</th><th>满分</th><th>评价说明</th></tr></thead><tbody>
      {definition.dimensions.map((d, i) => <tr key={i}><td>{d.name || "未命名维度"}</td><td>{d.max_score}</td><td>{d.description}</td></tr>)}
    </tbody></table></div>
    <h3>档位与判据</h3>{definition.dimensions.map((d, i) => <details key={i}><summary>{d.name || "未命名维度"}</summary>
      {definition.levels.map((l, j) => <p key={j}><strong>{l.label}（{l.percent}%）：</strong>{d.criteria[l.id] || "尚未填写判据"}</p>)}
    </details>)}
  </section>;
}
