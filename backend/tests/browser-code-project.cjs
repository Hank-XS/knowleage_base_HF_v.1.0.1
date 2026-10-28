// Run from the repository with the local app running; creates one labelled demo project.
const { chromium } = require('../../frontend/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');

(async () => {
  const runtime = path.resolve(__dirname, '../.local/browser-code-project');
  fs.mkdirSync(runtime, { recursive: true });
  const python = process.env.PYTHON_PATH || path.resolve(__dirname,
    process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python');
  execFileSync(python, [path.join(__dirname, 'code_project_sample.py'), path.join(runtime, 'cobol-demo.zip')]);
  const browser = await chromium.launch({ headless: true,
    executablePath: process.env.BROWSER_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 400 && response.url().includes('/code-projects')) errors.push(`${response.status()} ${response.url()}`);
  });
  try {
    await page.goto('http://127.0.0.1:5666/', { waitUntil: 'networkidle', timeout: 120000 });
    await page.locator('input[type=password]').waitFor({ timeout: 60000 });
    await page.locator('input[type=password]').fill('dev123456');
    const slider = await page.getByText('请按住滑块拖动', { exact: true }).locator('xpath=ancestor::div[contains(@class, "overflow-hidden")][1]').boundingBox();
    await page.mouse.move(slider.x + 20, slider.y + slider.height / 2);
    await page.mouse.down();
    await page.mouse.move(slider.x + slider.width - 5, slider.y + slider.height / 2, { steps: 30 });
    await page.mouse.up();
    await page.getByRole('button', { name: 'login', exact: true }).click();
    await page.waitForURL('**/kb/qa', { timeout: 60000 });
    await page.goto('http://127.0.0.1:5666/knowledge/upload?mode=project', { waitUntil: 'networkidle' });
    await page.getByPlaceholder('例如：账户核心系统').fill('COBOL 首版验收示例');
    await page.locator('input[type=file]').setInputFiles(path.join(runtime, 'cobol-demo.zip'));
    await page.screenshot({ path: path.join(runtime, 'codegraph-upload.png'), fullPage: true });
    const uploaded = page.waitForResponse(r => r.url().endsWith('/code-projects') && r.request().method() === 'POST');
    await page.getByRole('button', { name: '上传并解析工程', exact: true }).click();
    const http = await uploaded;
    const payload = await http.json();
    assert.equal(http.status(), 200, JSON.stringify(payload));
    const jobId = payload.data.job_id;
    await page.waitForURL(`**/kb/code-projects/${jobId}`, { timeout: 30000 });
    await page.getByText('已完成', { exact: true }).waitFor({ timeout: 120000 });
    await page.getByText('MISSING-SERVICE', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(runtime, 'codegraph-report.png'), fullPage: true });
    await page.getByRole('tab', { name: '结构切片', exact: true }).click();
    await page.getByRole('button', { name: '定位源码', exact: true }).first().waitFor();
    const chunkCount = await page.getByRole('button', { name: '定位源码', exact: true }).count();
    assert.ok(chunkCount >= 4);
    await page.getByRole('button', { name: '定位源码', exact: true }).first().click();
    await page.locator('.source-box .highlighted').first().waitFor();
    await page.screenshot({ path: path.join(runtime, 'codegraph-source.png'), fullPage: true });
    await page.getByRole('tab', { name: '代码关系图', exact: true }).click();
    await page.locator('.graph-box[data-ready="true"] canvas').waitFor({ timeout: 30000 });
    await page.locator('.graph-box').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(runtime, 'codegraph-graph.png'), fullPage: true });
    // Reload must preserve the snapshot and results, independently of the upload page.
    await page.reload({ waitUntil: 'networkidle' });
    await page.getByText('MISSING-SERVICE', { exact: true }).waitFor();
    await page.getByRole('button', { name: '接入任务', exact: true }).click();
    await page.getByText('COBOL 首版验收示例', { exact: true }).first().waitFor();
    await page.goto('http://127.0.0.1:5666/knowledge/upload', { waitUntil: 'networkidle' });
    await page.locator('input[type=file]').setInputFiles({ name: 'codegraph-upload-regression.md', mimeType: 'text/markdown', buffer: Buffer.from('# Upload regression\n\nExisting document upload remains available.\n') });
    const documentResponse = page.waitForResponse(r => r.url().endsWith('/knowledge/upload') && r.request().method() === 'POST');
    await page.getByRole('button', { name: '开始上传', exact: true }).click();
    const documentHttp = await documentResponse;
    assert.equal(documentHttp.status(), 200, await documentHttp.text());
    assert.deepEqual(errors, []);
    const result = { jobId, chunkCount, browserErrors: errors, url: `http://127.0.0.1:5666/kb/code-projects/${jobId}` };
    fs.writeFileSync(path.join(runtime, 'codegraph-browser-result.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    await page.screenshot({ path: path.join(runtime, 'codegraph-browser-failure.png'), fullPage: true });
    console.error(await page.locator('body').innerText());
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
