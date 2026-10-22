/** Browser acceptance against the real Next frontend and the test-only FastAPI server.
 * Start backend/tests/ui_server.py before running; no production model credentials are used.
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(frontendRoot, "..");
const resultsDir = resolve(frontendRoot, "test-results");
const url = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const moduleName = process.env.PLAYWRIGHT_MODULE_PATH
  ? pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE_PATH)).href
  : "playwright";
const { chromium } = await import(moduleName);
const source = (await readFile(resolve(repoRoot, "samples/S1.txt"), "utf8")).replace(/\r\n?/g, "\n");
const runMarker = `[E2E_RUN_${randomUUID()}]`;
await mkdir(resultsDir, { recursive: true });

const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROME_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: "zh-CN", acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(15_000);
const errors = [];
const failedRequests = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("requestfailed", (failed) => failedRequests.push({ url: failed.url(), error: failed.failure()?.errorText }));

async function waitForStatus(targetPage, expected) {
  await targetPage.waitForFunction((label) => document.querySelector(".result-summary h2")?.textContent === label, expected, { timeout: 30_000 });
  assert.equal(await targetPage.locator(".result-summary h2").textContent(), expected);
}

async function waitForTotal(targetPage, expected) {
  await targetPage.waitForFunction((total) => document.querySelector(".score-total strong")?.textContent === total, String(expected));
  assert.equal(await targetPage.locator(".score-total strong").textContent(), String(expected));
}

async function assertNoOverflow(targetPage, label) {
  const dimensions = await targetPage.evaluate(() => ({ viewport: window.innerWidth, page: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert.ok(dimensions.page <= dimensions.viewport + 1 && dimensions.body <= dimensions.viewport + 1, `${label}: unexpected horizontal overflow ${JSON.stringify(dimensions)}`);
}

async function start(targetPage, text) {
  await targetPage.locator("#assignment").fill(text);
  await targetPage.getByRole("button", { name: "生成评分草稿", exact: true }).click();
}

async function checkAll(targetPage) {
  const checks = targetPage.locator(".review-checkbox input");
  assert.equal(await checks.count(), 6);
  for (let index = 0; index < 6; index++) await checks.nth(index).check();
}

try {
  await page.goto(url);
  await page.locator(".rubric-list details").last().waitFor();
  assert.equal(await page.locator(".rubric-list details").count(), 6);
  assert.match(await page.locator(".rubric-footer").textContent(), /2026-v1/);
  for (const index of [1, 2]) assert.equal(await page.locator(".rubric-list details").nth(index).locator("strong").textContent(), "25 分");
  await assertNoOverflow(page, "desktop empty");

  // Normal generation, evidence, an exact half-point change, confirmation and export.
  await start(page, source);
  await waitForStatus(page, "待教师确认");
  assert.equal(await page.locator("#assignment").inputValue(), source);
  assert.equal(await page.locator(".dimension-card").count(), 6);
  await waitForTotal(page, 100);
  assert.ok(await page.locator(".confirm-panel").getByRole("button", { name: "确认保存批改记录", exact: true }).isDisabled());

  const firstEvidence = page.locator(".evidence-button").first();
  const quotedText = await firstEvidence.locator("span").textContent();
  await firstEvidence.click();
  const selectedText = await page.locator("#assignment").evaluate((input) => input.value.slice(input.selectionStart, input.selectionEnd));
  assert.equal(selectedText, quotedText.slice(1, -1), "evidence selects the exact source quote");

  await page.locator("#level-A").selectOption("70");
  await waitForTotal(page, "—");
  await checkAll(page);
  await page.locator(".confirm-panel").getByRole("button", { name: "保存复核", exact: true }).click();
  await waitForTotal(page, 95.5);
  assert.equal(await page.locator(".dimension-card").first().locator(".dimension-score strong").textContent(), "10.5");
  await page.locator(".confirm-panel").getByRole("button", { name: "确认保存批改记录", exact: true }).click();
  await waitForStatus(page, "已确认保存");
  await waitForTotal(page, 95.5);
  await assertNoOverflow(page, "desktop reviewed");
  await page.screenshot({ path: resolve(resultsDir, "desktop-confirmed.png"), fullPage: true, style: ".confirm-panel { position: static !important; }" });

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "导出 JSON 记录", exact: true }).click();
  const download = await downloadPromise;
  assert.match(download.suggestedFilename(), /^grading-.+\.json$/);
  const recordPath = resolve(resultsDir, "confirmed-record.json");
  await download.saveAs(recordPath);
  const exported = JSON.parse(await readFile(recordPath, "utf8"));
  assert.equal(exported.task.status, "confirmed");
  assert.equal(exported.task.text, source);
  assert.equal(exported.task.review.total, 95.5);
  assert.equal(exported.task.review.dimensions.find((dimension) => dimension.id === "A").score, 10.5);
  assert.ok(exported.task.review.dimensions.every((dimension) => dimension.reviewed));
  assert.equal(exported.record_id, exported.task.record_id);
  const savedId = await page.evaluate(() => localStorage.getItem("yuejian.latest-task"));
  assert.equal(savedId, exported.task.id);

  await page.reload();
  await waitForStatus(page, "已确认保存");
  await waitForTotal(page, 95.5);
  assert.equal(await page.locator("#assignment").inputValue(), source);
  await page.locator("#assignment").fill(`${source}\n原文已修改`);
  assert.equal(await page.locator(".dimension-card").count(), 0);
  assert.equal(await page.locator(".result-summary").count(), 0);
  assert.equal(await page.evaluate(() => localStorage.getItem("yuejian.latest-task")), null);
  assert.equal(await page.locator(".empty-state h2").textContent(), "评分建议将在这里呈现");
  console.log("PASS normal review, 95.5 exact score, export, reload and source invalidation");

  // A test-only one-shot provider failure retains the exact input and succeeds on retry.
  const transientSource = `${source}\n[E2E_TOOL_503_ONCE]\n${runMarker}`;
  await start(page, transientSource);
  await waitForStatus(page, "生成未完成");
  assert.equal(await page.locator("#assignment").inputValue(), transientSource);
  assert.equal(await page.locator(".dimension-card").count(), 0);
  await page.getByRole("button", { name: "重新尝试", exact: true }).click();
  await waitForStatus(page, "待教师确认");
  assert.equal(await page.locator("#assignment").inputValue(), transientSource);
  await waitForTotal(page, 100);
  assert.equal(await page.locator(".dimension-card").count(), 6);
  console.log("PASS transient failure retains source and retry uses real task endpoint");

  // A persistent test-only failure offers a complete, initially blank manual review.
  const failedSource = `${source}\n[E2E_ALWAYS_FAIL]`;
  await start(page, failedSource);
  await waitForStatus(page, "生成未完成");
  assert.equal(await page.locator("#assignment").inputValue(), failedSource);
  await page.getByRole("button", { name: "进入人工批改", exact: true }).click();
  await waitForStatus(page, "待教师确认");
  assert.equal(await page.locator(".result-summary .small-badge").textContent(), "人工批改");
  assert.equal(await page.locator(".task-error").count(), 0, "old failure actions disappear after manual takeover");
  assert.ok(await page.locator(".confirm-panel").getByRole("button", { name: "确认保存批改记录", exact: true }).isDisabled());
  for (const id of "ABCDEF") {
    assert.equal(await page.locator(`#level-${id}`).inputValue(), "");
    await page.locator(`#level-${id}`).selectOption("100");
    await page.locator(`#reason-${id}`).fill(`教师人工核查 ${id} 维：原文满足固定量表要求。`);
  }
  await checkAll(page);
  await page.locator(".confirm-panel").getByRole("button", { name: "确认保存批改记录", exact: true }).click();
  await waitForStatus(page, "已确认保存");
  await waitForTotal(page, 100);
  assert.equal(await page.locator("#assignment").inputValue(), failedSource);
  console.log("PASS persistent failure and complete six-dimension manual confirmation");

  // Historical snapshots are fixtures because the API only creates the current rubric.
  const historyContext = await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: "zh-CN" });
  const historyPage = await historyContext.newPage();
  historyPage.setDefaultTimeout(15_000);
  historyPage.on("pageerror", (error) => errors.push(error.message));
  const historicalBase = structuredClone(exported.task);
  historicalBase.id = "history-fixture";
  historicalBase.rubric_version = "af-2026-10-09-v1";
  for (const data of [historicalBase.draft, historicalBase.review]) {
    if (data) {
      data.dimensions.find((item) => item.id === "B").score = 20;
      data.dimensions.find((item) => item.id === "C").score = 30;
    }
  }
  if (historicalBase.draft) historicalBase.draft.rubric_version = historicalBase.rubric_version;
  let historicalFixture = historicalBase;
  let historicalReads = 0;
  const historicalWrites = [];
  await historyPage.route(/\/api\/tasks\/history-fixture(?:\/retry)?$/, async (route) => {
    const incoming = route.request();
    if (incoming.method() === "GET") {
      historicalReads += 1;
      await route.fulfill({ json: historicalFixture });
    } else {
      historicalWrites.push({ method: incoming.method(), path: new URL(incoming.url()).pathname });
      await route.fulfill({ status: 202, json: { ...exported.task, id: "regenerated-fixture", parent_id: historicalBase.id, status: "pending_review", record_id: null, review: null } });
    }
  });
  await historyPage.goto(url);
  await historyPage.locator(".rubric-list details").last().waitFor();
  for (const status of ["pending_review", "queued", "running", "confirmed", "failed"]) {
    historicalFixture = { ...historicalBase, status, record_id: status === "confirmed" ? historicalBase.record_id : null,
      error: status === "failed" ? { code: "historical_failure", message: "历史任务失败" } : null };
    await historyPage.evaluate((id) => localStorage.setItem("yuejian.latest-task", id), historicalBase.id);
    historicalReads = 0;
    await historyPage.reload();
    await historyPage.locator(".historical-task").waitFor();
    assert.equal(await historyPage.locator(".dimension-score span").count(), 0, "history must not show new dimension maxima");
    assert.equal(await historyPage.getByRole("button", { name: "保存复核", exact: true }).count(), 0);
    assert.equal(await historyPage.getByRole("button", { name: "进入人工批改", exact: true }).count(), 0);
    for (const field of await historyPage.locator(".review-fields select, .review-fields textarea, .review-checkbox input").all()) assert.ok(await field.isDisabled());
    if (status === "confirmed") {
      assert.equal(await historyPage.getByRole("link", { name: "导出 JSON 记录", exact: true }).getAttribute("href"), "/api/tasks/history-fixture/export");
    } else {
      assert.ok(await historyPage.getByRole("button", { name: "按当前量表重新生成", exact: true }).isEnabled());
    }
    if (status === "queued" || status === "running") {
      await historyPage.waitForTimeout(1200);
      assert.equal(historicalReads, 1, "historical running tasks must not be polled");
      assert.equal(await historyPage.locator(".run-progress").count(), 0);
    }
  }
  await historyPage.getByRole("button", { name: "按当前量表重新生成", exact: true }).click();
  await historyPage.locator(".dimension-score span").first().waitFor();
  assert.deepEqual(historicalWrites, [{ method: "POST", path: "/api/tasks/history-fixture/retry" }]);
  assert.equal(await historyPage.locator(".historical-task").count(), 0);
  assert.ok(await historyPage.locator("#level-B").isEnabled());
  await historyContext.close();
  console.log("PASS historical tasks are read-only, running history does not poll, retry uses the current rubric, and archived JSON stays available");

  // Check small-screen layout with real populated result cards, not only an empty shell.
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "zh-CN" });
  const mobilePage = await mobile.newPage();
  mobilePage.setDefaultTimeout(15_000);
  mobilePage.on("pageerror", (error) => errors.push(error.message));
  await mobilePage.goto(url);
  await mobilePage.locator(".rubric-list details").last().waitFor();
  await assertNoOverflow(mobilePage, "mobile empty");
  await start(mobilePage, source);
  await waitForStatus(mobilePage, "待教师确认");
  await waitForTotal(mobilePage, 100);
  await assertNoOverflow(mobilePage, "mobile populated");
  await mobilePage.screenshot({ path: resolve(resultsDir, "mobile-review.png"), fullPage: true, style: ".confirm-panel { position: static !important; }" });
  await mobile.close();
  assert.deepEqual(errors, [], "no browser runtime errors");
  console.log("PASS desktop/mobile overflow checks and browser runtime checks");
  console.log(`Browser acceptance passed. Evidence: ${resultsDir}`);
} catch (error) {
  console.error("Browser diagnostics:", JSON.stringify({ errors, failedRequests }));
  await page.screenshot({ path: resolve(resultsDir, "failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await context.close();
  await browser.close();
}
