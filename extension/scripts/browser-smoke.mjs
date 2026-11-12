// Run against the visible Chromium test profile, with the actual MV3 extension.
// Usage: node extension/scripts/browser-smoke.mjs [PDF path]
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, basename } from 'node:path';
import { createHash } from 'node:crypto';
import { connect, evaluate, waitExpression } from './cdp.mjs';

const output = resolve('.local/browser-tests');
await mkdir(output, { recursive: true });
const targets = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const extensionID = [...createHash('sha256').update(resolve('extension')).digest('hex').slice(0,32)].map(x=>String.fromCharCode(97+parseInt(x,16))).join('');
const origin = `chrome-extension://${extensionID}`;
const target = await (await fetch(`http://127.0.0.1:9223/json/new?${encodeURIComponent(origin+'/review.html')}`, {method:'PUT'})).json();
const c = await connect(target.webSocketDebuggerUrl);
const report = { browser: 'Visible Chromium', extension_id: origin.split('//')[1], real_models: true, tests: [], errors: [], requests: [] };
await c.send('Runtime.enable'); await c.send('Page.enable'); await c.send('Network.enable');
await c.send('Page.bringToFront');
await c.send('Emulation.setFocusEmulationEnabled', {enabled:true});
c.on('Runtime.exceptionThrown', x => report.errors.push(x.exceptionDetails.exception?.description || x.exceptionDetails.text));
c.on('Network.responseReceived', x => {
  if (x.response.url.startsWith('http://127.0.0.1:8765/')) report.requests.push({ path: new URL(x.response.url).pathname, status: x.response.status });
});
async function check(name, action) {
  try { const details = await action(); report.tests.push({ name, passed: true, details }); console.log(`PASS ${name}`, details || ''); }
  catch (error) { report.tests.push({ name, passed: false, error: error.message }); console.log(`FAIL ${name}: ${error.message}`); throw error; }
}
async function wait(expression, timeout) { return evaluate(c, waitExpression(expression, timeout)); }
async function screenshot(name) {
  await c.send('Page.bringToFront');
  const image = await c.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(`${output}/${name}.png`, Buffer.from(image.data, 'base64'));
}
async function load(path) {
  const dom = await c.send('DOM.getDocument');
  const input = await c.send('DOM.querySelector', { nodeId: dom.root.nodeId, selector: '#file' });
  await c.send('DOM.setFileInputFiles', { nodeId: input.nodeId, files: [resolve(path)] });
  const expected = `Ready: ${basename(path)}.`;
  await wait(`!document.getElementById('analyze').disabled && document.getElementById('status').textContent.startsWith(${JSON.stringify(expected)})`,15000);
}
async function analyze() {
  await c.send('Page.bringToFront');
  await evaluate(c, "document.getElementById('analyze').click()");
  const state=await wait("!document.getElementById('analyze').disabled && document.getElementById('status').textContent", 180000);
  assert(state.startsWith('Analysis complete.'),state);
}
async function allAnalyzed() {
  await evaluate(c, "document.getElementById('filter').value='analyzed';document.getElementById('filter').dispatchEvent(new Event('change'))");
}

try {
  await wait("document.body?.dataset.ready==='true'", 15000);
  assert.equal(await evaluate(c, 'chrome.runtime.getManifest().manifest_version'), 3);
  const pdfPath = process.argv[2] || 'test/16014225801 ML EXP 1.pdf';
  await check('Real university PDF upload and both-modality review', async () => {
    await load(pdfPath); await analyze();
    await wait("document.getElementById('pdf-canvas').dataset.renderedPage==='1'", 30000);
    const stats = await evaluate(c, "({coverage:document.getElementById('coverage').innerText,modalities:document.getElementById('modalities').innerText,preview:document.getElementById('location').innerText,page:document.getElementById('page-number').innerText})");
    assert(!stats.preview.includes('unavailable'), stats.preview); assert(stats.modalities.includes('Unvalidated for university submissions'));
    await screenshot('pdf-results'); return stats;
  });
  await check('PDF passage location and page navigation', async () => {
    await allAnalyzed();
    assert(await evaluate(c, "document.querySelectorAll('#passages button').length>0"));
    await evaluate(c, "document.querySelector('#passages details').open=true;document.querySelector('#passages button').click()");
    await wait("Number(document.getElementById('pdf-canvas').dataset.highlightedBoxes)>0", 15000);
    await screenshot('pdf-highlight');
    const total = await evaluate(c, "Number(document.getElementById('page-number').textContent.split('/')[1])");
    if (total>1) {
      const old = await evaluate(c, "document.getElementById('page-number').textContent");
      await evaluate(c, "document.getElementById('next').click()");
      await wait(`document.getElementById('page-number').textContent!==${JSON.stringify(old)}`, 15000);
    }
    return { page_count: total };
  });
  const python = '# Unicode evidence: 🧪\n' + Array.from({length:5},(_,i)=>`def sum_items_${i}(items):\n    # Keep indentation and the submitted comment.\n    total = 0\n    for item in items:\n        if isinstance(item, (int, float)):\n            total += item\n    return total\n\n`).join('');
  await writeFile(`${output}/sample.py`, python);
  await check('Python upload uses real code detector', async () => {
    await load(`${output}/sample.py`); await analyze(); await allAnalyzed();
    const stats=await evaluate(c,"({source:document.getElementById('source-view').textContent,passages:document.querySelectorAll('#passages details').length,summary:document.getElementById('modalities').innerText})");
    assert.equal(stats.source,python); assert(stats.passages>0); await screenshot('python-results');
    return { analyzed_passages: stats.passages };
  });
  await check('Source highlights preserve Unicode offsets', async () => {
    await evaluate(c, "document.querySelector('#passages details').open=true;document.querySelector('#passages button').click()");
    const actual=await evaluate(c,"({marked:[...document.querySelectorAll('#source-view mark')].map(x=>x.textContent).join(''),passage:document.querySelector('#passages pre').textContent,source:document.getElementById('source-view').textContent})");
    assert.equal(actual.source,python); assert.equal(actual.marked,actual.passage); await screenshot('python-highlight'); return { exact: true };
  });
  const java='import java.util.Arrays;\nclass Demo {\n    static int sum(int[] values) {\n        int total = 0;\n        for (int value : values) { total += value; }\n        return total;\n    }\n}\n';
  await writeFile(`${output}/unsupported.py`, java);
  await check('Java listing withheld, not falsely scored as Python',async()=>{
    await load(`${output}/unsupported.py`); await analyze();
    await evaluate(c,"document.getElementById('filter').value='unscored';document.getElementById('filter').dispatchEvent(new Event('change'))");
    const text=await evaluate(c,"document.getElementById('passages').innerText");assert(text.includes('outside_validation_domain'));await screenshot('unsupported-java');return {reason:'outside_validation_domain'};
  });
  const javascript=Array.from({length:5},(_,i)=>`function sumValues${i}(values) {\n  const valid = values.filter(value => Number.isFinite(value));\n  const total = valid.reduce((sum, value) => sum + value, 0);\n  return { total, count: valid.length };\n}\n\n`).join('');
  await writeFile(`${output}/sample.js`,javascript);
  await check('JavaScript upload and exact source review',async()=>{
    await load(`${output}/sample.js`);await analyze();await allAnalyzed();
    assert.equal(await evaluate(c,"document.getElementById('source-view').textContent"),javascript);
    const count=await evaluate(c,"document.querySelectorAll('#passages details').length");assert(count>0);return {analyzed_passages:count};
  });
  const prose=Array.from({length:8},()=> 'We measured the voltage across the resistor and recorded the data in our laboratory notebook. The results were compared with the theoretical values. Small differences can be caused by component tolerances and the resolution of our measuring instruments.\n\n').join('');
  await writeFile(`${output}/sample.txt`,prose);
  await check('UTF-8 text upload and separate prose detector',async()=>{
    await load(`${output}/sample.txt`);await analyze();await allAnalyzed();
    assert.equal(await evaluate(c,"document.getElementById('source-view').textContent"),prose);
    const count=await evaluate(c,"document.querySelectorAll('#passages details').length");assert(count>0);return {analyzed_passages:count};
  });
  await check('Unauthorized API access rejected',async()=>{
    const status=await evaluate(c,"fetch('http://127.0.0.1:8765/health',{credentials:'omit'}).then(x=>x.status)");assert.equal(status,401);return {http_status:status};
  });
  await check('Clear review removes document and result',async()=>{
    await evaluate(c,"document.getElementById('clear').click()");await wait("document.getElementById('results').hidden && document.getElementById('analyze').disabled",15000);
    assert.equal(await evaluate(c,"document.getElementById('source-view').textContent"),'');return { cleared: true };
  });
  await check('No uncaught extension script errors',async()=>{assert.deepEqual(report.errors,[]);return {count:0};});
  // Leave a real, usable PDF review open for the user after cleanup was verified.
  await load(pdfPath); await analyze();
  await wait("document.getElementById('pdf-canvas').dataset.renderedPage==='1'",30000);
  await allAnalyzed();
  await evaluate(c,"document.querySelector('#passages details').open=true;document.querySelector('#passages button').click()");
  await wait("Number(document.getElementById('pdf-canvas').dataset.highlightedBoxes)>0",15000);
  await evaluate(c,"document.querySelector('.workspace').scrollIntoView({block:'start'})");
  await screenshot('live-review');
} catch (error) { process.exitCode=1; report.run_error=error.message; console.error('Browser run failed:',error.message); await screenshot('failure'); }
finally { await writeFile(`${output}/report.json`,JSON.stringify(report,null,2));c.close();console.log(`Report: ${output}/report.json`); }
