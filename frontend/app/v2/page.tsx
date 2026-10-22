import Link from "next/link";
import { CourseWorkspace } from "@/components/course-workspace";
import "./workspace.css";

export default function CoursePage() {
  return <div className="v2-shell"><header className="v2-header"><Link href="/">阅见 / 教师工作台</Link><strong>课程与评分标准</strong><Link href="/">返回固定量表演示</Link></header><CourseWorkspace /></div>;
}
