/** Browser acceptance for batch upload, analytics and cross-tab navigation. */
import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(frontendRoot, "..");
const resultsDir = resolve(frontendRoot, "test-results");
const moduleName = process.env.PLAYWRIGHT_MODULE_PATH
  ? pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE_PATH)).href : "playwright";
const { chromium } = await import(moduleName);
const source = await readFile(resolve(repoRoot, "samples/S1.txt"), "utf8");
const browserText = source.replace(/\r\n?/g, "\n");
const baseUrl = process.env.E2E_BASE_URL || "http://localhost:3000";
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROME_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, locale: "zh-CN", acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(15_000);
const browserErrors = [];
page.on("pageerror", (error) => browserErrors.push(error.message));
await mkdir(resultsDir, { recursive: true });

const ids = ["A", "B", "C", "D", "E", "F"];
const names = ["需求背景与用户范围", "需求表达可验证性", "验收场景与测试用例", "系统行为依据", "AI协作过程反思", "同行互评修订"];
const weights = [15, 25, 25, 15, 10, 10];
const rubric = { version: "2026-v1", levels: [100, 70, 30, 0], dimensions: ids.map((id, index) => ({ id, name: names[index], max_score: weights[index], criteria: "核查原文" })) };
const batchId = "batch-browser-test";
const timestamp = "2026-10-21T10:00:00.000Z";
const summary = { batch_id: batchId, name: "软件工程班 · 第二次作业", total_count: 2, completed_count: 0, failed_count: 0, status: "queued", created_at: timestamp, updated_at: timestamp };
const analytics = {
  batch_id: batchId,
  summary: { total_submitted: 2, analyzed_count: 2, average_score: 87.5, pass_rate: 1, excellent_rate: 0.5, max_score: 95, min_score: 80 },
  radar: ids.map((dimension, index) => ({ dimension, name: names[index], full_score: weights[index], average_score: weights[index] * (0.9 - index * 0.05), scoring_rate: 0.9 - index * 0.05 })),
  common_weaknesses: [{ rank: 1, dimension: "C", title: "验收边界场景不足", affected_count: 1, percentage: 0.5, recommendation: "补充异常与边界测试用例。" }],
  security_alerts: [{ task_id: "task-one", filename: "001_甲.txt", flag: "prompt_injection_detected", detail: "检测到疑似对抗指令，请人工核查。" }],
};
const quote = "用户是课程教师。";
const quoteStart = Array.from(source.slice(0, source.indexOf(quote))).length;
const task = {
  id: "task-one", status: "pending_review", source: "agent", text: source,
  input_version: "browser-test", rubric_version: "2026-v1", created_at: timestamp,
  updated_at: timestamp, parent_id: null,
  draft: { dimensions: ids.map((id, index) => ({ id, level: 100, score: weights[index], reason: "原文满足要求。", evidence: index === 0 ? [{ quote, paragraph: 4, start: quoteStart, end: quoteStart + Array.from(quote).length }] : [], needs_review: false, review_note: "" })), total: 100, status: "draft", rubric_version: "2026-v1", input_version: "browser-test" },
  review: null, trace: [], error: null, repair_rounds: 0, validation_count: 1, model_calls: 1, record_id: null,
};
let created = false;
let batchReads = 0;
let submitted = null;

await page.route("**/api/**", async (route) => {
  const path = new URL(route.request().url()).pathname;
  const respond = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  if (path === "/api/rubric") return respond(rubric);
  if (path === "/api/batches") return respond({ total: created ? 1 : 0, items: created ? [{ ...summary, status: batchReads > 1 ? "completed" : "queued", completed_count: batchReads > 1 ? 2 : 0 }] : [] });
  if (path === "/api/batch/tasks" && route.request().method() === "POST") {
    submitted = route.request().postDataJSON();
    created = true;
    return respond(summary, 202);
  }
  if (path === `/api/batch/${batchId}`) {
    batchReads += 1;
    const done = batchReads > 1;
    return respond({ ...summary, status: done ? "completed" : "queued", completed_count: done ? 2 : 0,
      tasks: [
        { task_id: "task-one", filename: "001_甲.txt", status: done ? "pending_review" : "queued", total_score: done ? 80 : null, needs_review: false, security_flag: done ? "prompt_injection_detected" : "none", created_at: timestamp },
        { task_id: "task-two", filename: "002_乙.md", status: done ? "confirmed" : "queued", total_score: done ? 95 : null, needs_review: false, security_flag: "none", created_at: timestamp },
      ] });
  }
  if (path === `/api/batch/${batchId}/analytics`) return respond(analytics);
  if (path === `/api/batch/${batchId}/export-csv`) return route.fulfill({ status: 200, headers: { "content-type": "text/csv; charset=utf-8", "content-disposition": `attachment; filename="gradebook-${batchId}.csv"` }, body: "\ufeff文件名,总分\n001_甲.txt,80\n" });
  if (path === "/api/tasks/task-one") return respond(task);
  return respond({ detail: "测试中未模拟此接口" }, 404);
});

async function noOverflow(label) {
  const sizes = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert.ok(sizes.document <= sizes.viewport + 1 && sizes.body <= sizes.viewport + 1, `${label}: ${JSON.stringify(sizes)}`);
}

try {
  await page.goto(new URL("/legacy", baseUrl).href);
  await page.locator(".rubric-list details").last().waitFor();
  await page.getByRole("tab", { name: "班级学情大屏" }).click();
  await page.getByRole("heading", { name: "尚未选择批次" }).waitFor();
  await page.getByRole("tab", { name: "批量摄取与队列" }).click();
  await page.locator("#batch-name").fill(summary.name);
  await page.locator("#batch-files").setInputFiles({ name: "invalid.docx", mimeType: "application/octet-stream", buffer: Buffer.from("not supported") });
  await page.getByText(/仅支持 TXT、MD/).waitFor();
  assert.equal(await page.locator(".selected-files li").count(), 0);
  await page.locator("#batch-files").setInputFiles({ name: "invalid-utf8.txt", mimeType: "text/plain", buffer: Buffer.from([0xc3, 0x28]) });
  await page.getByText(/不是有效的 UTF-8/).waitFor();
  assert.equal(await page.locator(".selected-files li").count(), 0);
  await page.locator("#batch-files").setInputFiles({ name: "oversized.txt", mimeType: "text/plain", buffer: Buffer.alloc(200_001, 65) });
  await page.getByText(/文件过大/).waitFor();
  assert.equal(await page.locator(".selected-files li").count(), 0);
  await page.locator("#batch-files").setInputFiles([
    { name: "001_甲.txt", mimeType: "text/plain", buffer: Buffer.from(source) },
    { name: "002_乙.md", mimeType: "text/markdown", buffer: Buffer.from("\ufeff# 第二份作业\r\n🧪内容") },
  ]);
  await page.locator(".selected-files li").nth(1).waitFor();
  await page.getByRole("button", { name: "创建批次" }).click();
  await page.locator(".batch-table tbody tr").nth(1).waitFor();
  await page.waitForFunction(() => document.querySelector(".progress-summary > strong")?.textContent === "100%");
  assert.equal(submitted.name, summary.name);
  assert.equal(submitted.rubric_version, "2026-v1");
  assert.deepEqual(submitted.files.map((item) => item.filename), ["001_甲.txt", "002_乙.md"]);
  assert.equal(submitted.files[0].text, source);
  assert.equal(submitted.files[1].text, "\ufeff# 第二份作业\r\n🧪内容");
  assert.ok(batchReads >= 2);
  assert.match(await page.locator(".progress-summary").textContent(), /已完成批改 2 \/ 2/);
  assert.equal(await page.locator(".task-pending_review").count(), 1);
  assert.equal(await page.locator(".task-confirmed").count(), 1);
  await page.screenshot({ path: resolve(resultsDir, "batch-queue-desktop.png"), fullPage: true, style: "nextjs-portal { display: none !important; }" });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "下载班级成绩单" }).click();
  assert.equal((await downloadPromise).suggestedFilename(), `gradebook-${batchId}.csv`);

  await page.getByRole("button", { name: "查看学情" }).click();
  await page.locator(".radar-data").waitFor();
  assert.equal((await page.locator(".radar-data").getAttribute("points")).split(" ").length, 6);
  assert.match(await page.locator(".metric-band").textContent(), /87\.5/);
  assert.match(await page.locator(".weakness-list").textContent(), /验收边界场景不足/);
  assert.match(await page.locator(".security-list").textContent(), /疑似对抗指令/);
  await noOverflow("desktop analytics");
  await page.screenshot({ path: resolve(resultsDir, "batch-analytics-desktop.png"), fullPage: true, style: "nextjs-portal { display: none !important; }" });

  await page.locator(".security-list").getByRole("button", { name: "打开作业" }).click();
  await page.locator(".result-summary h2").waitFor();
  assert.equal(await page.locator("#assignment").inputValue(), browserText);
  assert.equal(await page.evaluate(() => localStorage.getItem("yuejian.latest-task")), "task-one");
  await page.locator(".evidence-button").first().click();
  const selectedQuote = await page.locator("#assignment").evaluate((input) => input.value.slice(input.selectionStart, input.selectionEnd));
  assert.equal(selectedQuote, quote);
  await page.locator("#assignment").fill("老师修改了原文");
  await page.getByRole("tab", { name: "批量摄取与队列" }).click();
  await page.locator(".batch-table").getByRole("button", { name: "打开作业" }).first().click();
  await page.waitForFunction((original) => document.querySelector("#assignment")?.value === original, browserText);
  assert.equal(await page.getByRole("tab", { name: "单份精细批改" }).getAttribute("aria-selected"), "true");

  await page.getByRole("tab", { name: "班级学情大屏" }).click();
  await page.reload();
  await page.locator(".radar-data").waitFor();
  assert.equal(await page.getByRole("tab", { name: "班级学情大屏" }).getAttribute("aria-selected"), "true");
  assert.equal(await page.evaluate(() => localStorage.getItem("yuejian.latest-batch")), batchId);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const label of ["班级学情大屏", "批量摄取与队列", "单份精细批改"]) {
    await page.getByRole("tab", { name: label }).click();
    await noOverflow(`mobile ${label}`);
    if (label === "批量摄取与队列") await page.screenshot({ path: resolve(resultsDir, "batch-queue-mobile.png"), fullPage: true, style: "nextjs-portal { display: none !important; }" });
  }
  await page.getByRole("tab", { name: "班级学情大屏" }).click();
  await page.screenshot({ path: resolve(resultsDir, "batch-analytics-mobile.png"), fullPage: true, style: "nextjs-portal { display: none !important; }" });
  assert.deepEqual(browserErrors, []);
  console.log("PASS batch upload, polling, CSV, analytics, task navigation, persistence and mobile layout");
} finally {
  await context.close();
  await browser.close();
}
