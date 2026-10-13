import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "阅见 · 作业批改工作台",
  description: "有据可查的六维评分草稿，由教师复核并确认。",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
