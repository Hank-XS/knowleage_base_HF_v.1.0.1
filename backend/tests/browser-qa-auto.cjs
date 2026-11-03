// Exercises the single composer with intercepted QA writes; no business chat is created.
const { chromium } = require('../../frontend/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const output = path.resolve(__dirname, '../.local/qa-ui');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' });
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = []; const sent = [];
  page.on('pageerror', e => errors.push(e.message));
  const ok = data => ({status:200,contentType:'application/json',body:JSON.stringify({code:0,message:'success',data})});
  await page.route('**/api/qa/sessions**', route => route.fulfill(ok(route.request().method()==='POST' ? {session_id:'ui-test'} : {items:[],total:0,page:1,page_size:20})));
  await page.route('**/api/qa/ask_agent', route => {
    sent.push(route.request().postDataJSON());
    return route.fulfill(ok({answer_id:'ui-answer',answer:{summary:'已找到相关代码，请查看原文依据。'},sources:[],review_status:'pending_review',reasoning_trace:[],entities:[],elapsed_ms:1,hit_type:'miss'}));
  });
  await page.route('**/api/qa/answers/ui-answer/feedback',route=>route.fulfill(ok({saved:true})));
  try {
    await page.goto('http://127.0.0.1:5666/',{waitUntil:'networkidle',timeout:120000});
    await page.locator('input[type=password]').waitFor({timeout:60000});
    await page.locator('input[type=password]').fill('dev123456');
    const slider=await page.getByText('请按住滑块拖动',{exact:true}).locator('xpath=ancestor::div[contains(@class,"overflow-hidden")][1]').boundingBox();
    await page.mouse.move(slider.x+20,slider.y+slider.height/2);await page.mouse.down();
    await page.mouse.move(slider.x+slider.width-5,slider.y+slider.height/2,{steps:30});await page.mouse.up();
    await page.getByRole('button',{name:'login',exact:true}).click();
    await page.waitForURL('**/kb/qa',{timeout:60000});
    const composer=page.getByPlaceholder('输入业务问题或粘贴代码',{exact:false});
    await composer.waitFor();
    assert.equal(await page.getByRole('button',{name:/找原代码|找相似逻辑|问业务知识/}).count(),0);
    const text='这段代码在哪里？\n```cobol\nMOVE INPUT-VALUE TO WAIT-VALUE\nCALL \'SERVICE\' USING WAIT-VALUE\n```';
    await composer.fill(text);await page.getByRole('button',{name:/^发\s*送$/}).click();
    await page.getByText('已找到相关代码，请查看原文依据。',{exact:true}).waitFor();
    assert.equal(sent[0].question,text);assert.equal(sent[0].retrieval_mode,undefined);
    await page.getByRole('button',{name:/^反\s*馈$/}).click();
    await page.getByPlaceholder('补充具体问题或期望内容（可选）').fill('检查依据是否匹配');
    await page.getByRole('button',{name:'提交反馈',exact:true}).click();
    await page.getByText('反馈已保存，待复核处理',{exact:true}).waitFor();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    await page.getByText('登录成功',{exact:true}).waitFor({state:'hidden'});
    await page.screenshot({path:path.join(output,'single-composer.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('Single composer, code payload, no mode selectors, feedback: PASS');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
