/** Course/teacher rubric acceptance; real APIs and deterministic test provider. */
import assert from "node:assert/strict";
import { randomUUID, createHash } from "node:crypto";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const base = process.env.E2E_BASE_URL || "http://127.0.0.1:13001";
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROME_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(20000);
const errors = [];
page.on("pageerror", e => errors.push(e.message));
const resultDir = resolve("test-results/v2");
await mkdir(resultDir, { recursive: true });
const marker = randomUUID().slice(0, 8);

async function ready() {
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent === '创建课程' && !button.disabled));
}
async function get(path) {
  const response = await context.request.get(`${base}/api/v2/${path}`);
  assert.equal(response.status(), 200, path);
  return response.json();
}
async function waitTask(id) {
  for (let i = 0; i < 100; i++) {
    const task = await get(`tasks/${id}`);
    if (!["queued", "running"].includes(task.status)) return task;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('test task did not finish');
}
async function tickAll() {
  for (const checkbox of await page.getByRole('checkbox').all()) await checkbox.check();
}

try {
  const health = await (await context.request.get(`${base}/api/health`)).json();
  assert.equal(health.model, 'scripted-ui-test-provider', 'Use backend/tests/ui_server.py, never a real model for browser acceptance.');
  await page.goto(`${base}/v2`);
  await ready();
  await page.getByLabel('课程名称', { exact: true }).fill(`数据库课程-${marker}`);
  await page.getByRole('button', { name: '创建课程', exact: true }).click();
  await ready();
  await page.getByLabel('新量表名称').fill(`报告标准-${marker}`);
  const createRubric = page.waitForResponse(response => response.url().endsWith('/api/v2/rubrics') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '新建评分量表', exact: true }).click();
  const rubric = await (await createRubric).json();
  const versionId = rubric.draft.id;
  await page.getByRole('button', { name: '填入四维数据库教学示例' }).click();
  const saveRubric = page.waitForResponse(response => response.url().endsWith(`/rubric-versions/${versionId}`) && response.request().method() === 'PATCH');
  await page.getByRole('button', { name: '保存并校验' }).click();
  assert.equal((await (await saveRubric).json()).total_score, '100.00');
  await ready();
  const publishRubric = page.waitForResponse(response => response.url().endsWith(`/rubric-versions/${versionId}/publish`));
  await page.getByRole('button', { name: '保存当前配置并发布' }).click();
  assert.equal((await (await publishRubric).json()).state, 'published');
  await ready();
  await page.getByLabel('作业标题', { exact: true }).fill(`查询实验-${marker}`);
  await page.getByLabel('任务要求', { exact: true }).fill('说明关联查询、实验步骤、结果分析与文本规范。不执行SQL。');
  await page.getByLabel('绑定量表版本').selectOption(versionId);
  const createAssignment = page.waitForResponse(response => response.url().endsWith('/api/v2/assignments') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '创建作业草稿' }).click();
  const assignment = await (await createAssignment).json();
  await ready();
  await page.getByRole('button', { name: '发布当前作业' }).click();
  await page.getByText('作业已发布，可以提交单份或批量文本。').waitFor();
  await page.getByLabel('作业正文', { exact: true }).fill('🧪 匿名实验报告\n查询说明：LEFT JOIN保留无选课学生，AVG排除NULL；给定80和100，均分为90。\n实验过程：创建合成数据、查询、分析并说明限制。');
  const createTask = page.waitForResponse(response => response.url().endsWith('/api/v2/tasks') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '按当前作业标准生成草稿' }).click();
  let task = await (await createTask).json();
  await page.getByText('最近保存总分：', { exact: false }).waitFor();
  task = await waitTask(task.id);
  assert.equal(task.rubric_snapshot.dimensions.length, 4);
  assert.equal(task.draft.total, '100.00');
  const workspace = page.getByRole('region', { name: '动态评分与复核' });
  await workspace.getByLabel('评分档位').first().selectOption('basic');
  await tickAll();
  const saveReview = page.waitForResponse(response => response.url().endsWith(`/tasks/${task.id}/review`));
  await page.getByRole('button', { name: '保存复核并重算' }).click();
  task = await (await saveReview).json();
  assert.equal(task.review.total, '88.00');
  await page.getByRole('button', { name: '确认并归档' }).click();
  await page.getByRole('link', { name: '下载确认记录 JSON' }).waitFor();
  await page.getByRole('button', { name: '定位证据：', exact: false }).first().click();
  assert.ok((await page.locator('mark').textContent()).startsWith('🧪'));
  const exported = await context.request.get(`${base}/api/v2/tasks/${task.id}/export`);
  const originalExport = await exported.text();
  assert.equal(JSON.parse(originalExport).task.review.total, '88.00');
  await page.screenshot({ path: resolve(resultDir, 'course-single-confirmed.png'), fullPage: true });
  console.log('PASS teacher config, four-dimensional scoring, 88.00 Decimal review, confirmation, codepoint evidence and JSON');

  const raw = '\ufeff🧪 原样输入\r\nSQL查询、过程和分析均为匿名合成文本。';
  await page.getByLabel('选择多个文本文件').setInputFiles([
    { name: '=full.txt', mimeType: 'text/plain', buffer: Buffer.from(raw) },
    { name: 'second.md', mimeType: 'text/markdown', buffer: Buffer.from('第二份匿名报告，有过程与限制。') },
    { name: 'failed.txt', mimeType: 'text/plain', buffer: Buffer.from('匿名原文 [V2_FAIL]') },
  ]);
  await page.getByText('已解析3份文件，保留原始换行和字符。').waitFor();
  const createBatch = page.waitForResponse(response => response.url().endsWith('/api/v2/batches') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '创建批量任务' }).click();
  let batch = await (await createBatch).json();
  for (let i = 0; i < 100; i++) {
    batch = await get(`batches/${batch.id}`);
    if (batch.finished_count === 3) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(batch.failed_count, 1);
  assert.equal(batch.total_count, 3);
  const first = await get(`tasks/${batch.items[0].task_id}`);
  assert.equal(first.text, raw);
  assert.equal(first.input_version, createHash('sha256').update(Buffer.from(raw)).digest('hex'));
  assert.equal((await get(`batches/${batch.id}/analytics`)).analyzed, 0);
  assert.equal((await context.request.get(`${base}/api/v2/batches/${batch.id}/export-csv`)).status(), 409);
  await page.getByLabel('统计口径').selectOption('working');
  await page.getByText('临时统计，包含未确认草稿或复核', { exact: false }).waitFor();
  assert.equal((await get(`batches/${batch.id}/analytics?basis=working`)).analyzed, 2);
  await page.locator('tbody tr').first().getByRole('button', { name: '打开复核' }).click();
  await tickAll();
  const saveFirst = page.waitForResponse(response => response.url().endsWith(`/tasks/${first.id}/review`));
  await page.getByRole('button', { name: '保存复核并重算' }).click();
  await saveFirst;
  await page.getByRole('button', { name: '确认并归档' }).click();
  await page.getByRole('link', { name: '导出已确认 1 份 CSV（其他提交不导出）' }).waitFor();
  const csv = await context.request.get(`${base}/api/v2/batches/${batch.id}/export-csv`);
  assert.equal(csv.headers()['x-exported-count'], '1');
  assert.equal(csv.headers()['x-excluded-count'], '2');
  const bytes = await csv.body();
  assert.equal(bytes.subarray(0, 3).toString('hex'), 'efbbbf');
  assert.match(bytes.toString('utf8'), /'=full.txt/);
  assert.doesNotMatch(bytes.toString('utf8'), /second.md|failed.txt/);
  await page.getByLabel('统计口径').selectOption('confirmed');
  await page.getByText('确认统计，只使用不可变确认记录', { exact: false }).waitFor();
  assert.equal((await get(`batches/${batch.id}/analytics`)).average_score, '100.00');
  await page.screenshot({ path: resolve(resultDir, 'course-batch-confirmed.png'), fullPage: true });
  console.log('PASS raw BOM/CRLF/emoji hashes, partial batch failure, confirmed/working sources and confirmed-only safe BOM CSV');

  await page.getByRole('button', { name: '复制为新版本' }).click();
  await page.getByLabel('维度名称', { exact: true }).first().fill('新版本查询标准');
  await page.getByRole('button', { name: '保存当前配置并发布' }).click();
  await page.getByText('量表已发布，已有任务快照不会随新版本变化。').waitFor();
  assert.equal(await (await context.request.get(`${base}/api/v2/tasks/${task.id}/export`)).text(), originalExport);
  assert.equal((await get(`assignments/${assignment.id}`)).rubric_version_id, versionId);
  console.log('PASS new version never changes prior assignment, task snapshot or immutable export');

  const template = (await get(`rubric-versions/${versionId}`)).definition;
  async function post(path, body) {
    const response = await context.request.post(`${base}/api/v2/${path}`, { data: body, headers: { 'Idempotency-Key': randomUUID() } });
    assert.ok(response.ok(), `${path}: ${await response.text()}`);
    return response.json();
  }
  for (const n of [1, 2, 12]) {
    const created = await post('rubrics', { title: `chart-${n}-${marker}` });
    const def = { ...template, dimensions: Array.from({ length: n }, (_, i) => ({ ...template.dimensions[0], id: `axis_${i}`, name: `维度${i + 1}`,
      max_score: n === 1 ? '100.00' : n === 2 ? '50.00' : i === 11 ? '8.37' : '8.33' })) };
    const saved = await context.request.patch(`${base}/api/v2/rubric-versions/${created.draft.id}`, { data: { expected_revision: 1, definition: def } });
    assert.equal(saved.status(), 200);
    const version = await post(`rubric-versions/${created.draft.id}/publish`, { expected_revision: 2 });
    const item = await post('assignments', { course_id: assignment.course_id, title: `chart-${n}`, instructions: '仅用于动态图表协议测试', rubric_version_id: version.id });
    await post(`assignments/${item.id}/publish`, { expected_revision: 1 });
    const fixture = await post('batches', { assignment_id: item.id, name: `chart-${n}-${marker}`, files: [{ filename: 'chart.txt', submission_label: '图表测试', text: '匿名测试文本，模型为脚本替身，不是效果评测。' }] });
    assert.equal((await waitTask(fixture.items[0].task_id)).status, 'pending_review');
    await page.reload();
    await page.getByLabel('历史批次').selectOption(fixture.id);
    await page.getByLabel('统计口径').selectOption('working');
    await page.getByText('临时统计，包含未确认草稿或复核', { exact: false }).waitFor();
    if (n <= 2) {
      assert.equal(await page.locator('meter').count(), n);
    } else {
      await page.getByRole('img', { name: '12维平均得分率雷达图' }).waitFor();
    }
  }
  console.log('PASS one/two-dimensional bars and twelve-dimensional native SVG radar against real APIs');

  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 900 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
  }
  await page.screenshot({ path: resolve(resultDir, 'course-mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  console.log('PASS mobile layouts and browser runtime checks');
} finally {
  await browser.close();
}
