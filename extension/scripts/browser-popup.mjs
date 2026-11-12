// Visible Chromium popup integration, real backend/models, no production bypass.
// The fixture server only binds loopback and is closed when the suite finishes.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { connect, evaluate, waitExpression } from './cdp.mjs';

const output = resolve('.local/browser-tests'); await mkdir(output, { recursive: true });
const pdf = await readFile('test/16014225801 ML EXP 1.pdf');
function prosePdf() {
  const lines = Array.from({ length: 30 }, (_, i) => [
    'We measured the voltage across the resistor and recorded our laboratory results.',
    'The observations were compared with the theoretical values for the experiment.',
    'Small differences may be caused by component tolerances and measuring instruments.'
  ][i % 3]);
  const stream = `BT /F1 10 Tf 36 760 Td 14 TL\n${lines.map(line => `(${line}) Tj T*`).join('\n')}\nET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];
  let text = '%PDF-1.7\n'; const offsets = [0];
  for (const [index, object] of objects.entries()) { offsets.push(text.length); text += `${index + 1} 0 obj\n${object}\nendobj\n`; }
  const xref = text.length;
  text += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(text);
}
const prose = prosePdf();
const id = [...createHash('sha256').update(resolve('extension')).digest('hex').slice(0,32)].map(x => String.fromCharCode(97 + parseInt(x,16))).join('');
const origin = `chrome-extension://${id}`;
const counts = {}; const siteHeaders = []; const clients = [];
const report = { browser: 'Visible Chromium toolbar popup', real_models: true, tests: [], errors: [] };
const server = createServer((request, response) => {
  const path = new URL(request.url, 'http://127.0.0.1').pathname;
  counts[path] = (counts[path] || 0) + 1;
  siteHeaders.push({ path, backendCredential: !!request.headers.authorization });
  if (path === '/login.pdf') { response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<h1>Sign in</h1>'); }
  else if (path === '/redirect.pdf' && request.headers['sec-fetch-dest'] === 'empty') { response.writeHead(302, { Location: '/assignment.pdf' }); response.end(); }
  else if (path === '/oversize.pdf') { response.writeHead(200, { 'Content-Type': 'application/pdf', 'Content-Length': 9 * 1024 * 1024 }); response.end(Buffer.alloc(9 * 1024 * 1024)); }
  else { response.writeHead(200, { 'Content-Type': 'application/pdf', 'Cache-Control': 'no-store' }); response.end(path === '/prose-only.pdf' ? prose : pdf); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const site = `http://127.0.0.1:${server.address().port}`;
async function targets() { return (await fetch('http://127.0.0.1:9223/json/list')).json(); }
async function newTarget(url) { return (await fetch(`http://127.0.0.1:9223/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json(); }
async function attach(target) {
  const c = await connect(target.webSocketDebuggerUrl); clients.push(c);
  await c.send('Runtime.enable'); await c.send('Page.enable');
  c.on('Runtime.exceptionThrown', x => report.errors.push(x.exceptionDetails.exception?.description || x.exceptionDetails.text));
  return c;
}
async function wait(c, expression, timeout = 15000) { return evaluate(c, waitExpression(expression, timeout)); }
async function check(name, action) {
  try { const details = await action(); report.tests.push({ name, passed: true, details }); console.log('PASS', name, details || ''); }
  catch (error) { report.tests.push({ name, passed: false, error: error.message }); throw error; }
}
let controller, popup, popupTarget, pdfTab, beforeTabs, beforeReviews;
async function openPopup() {
  // Native toolbar popups require an actually active OS window, not just CDP's
  // emulated document focus. Activate the isolated Chromium app on macOS.
  const app = process.env.CHROMIUM_APP || resolve(homedir(), 'Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app');
  for (let attempt = 0; ; attempt++) {
    if (process.platform === 'darwin' && existsSync(app)) execFileSync('/usr/bin/open', [app]);
    await evaluate(controller, `chrome.windows.update(${pdfTab.windowId},{focused:true}).then(()=>chrome.tabs.update(${pdfTab.id},{active:true}))`);
    await wait(controller, `chrome.windows.get(${pdfTab.windowId}).then(window=>window.focused)`);
    try {
      await evaluate(controller, `new Promise(requestAnimationFrame).then(()=>chrome.action.openPopup({windowId:${pdfTab.windowId}}))`); break;
    } catch (error) {
      if (attempt >= 2 || !/inactive window|active browser window/.test(error.message)) throw error;
    }
  }
  popupTarget = (await targets()).find(x => x.url === `${origin}/popup.html`);
  assert(popupTarget, 'Chrome did not open the toolbar popup.'); popup = await attach(popupTarget);
  await popup.send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await wait(popup, "document.body?.dataset.ready==='true'"); return popup;
}
async function closePopup() {
  await fetch(`http://127.0.0.1:9223/json/close/${popupTarget.id}`); popup.close(); popup = null;
}
async function waitPopup(expression, timeout = 15000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    try { return await wait(popup, expression, Math.max(1, deadline - Date.now())); }
    catch (error) {
      // Losing OS focus may close a native toolbar popup. Reopen it just as a
      // user would; the session must survive, with no production test bypass.
      if (!/target closed/.test(error.message) || Date.now() >= deadline) throw error;
      await openPopup();
      const state = await evaluate(popup, "chrome.runtime.sendMessage({channel:'coordinator',type:'init'})");
      if (state.record?.state === 'importing') throw new Error('File transfer interrupted before submission.');
    }
  }
}
async function pdfTabAt(path) {
  pdfTab = await evaluate(controller, `chrome.tabs.create({url:${JSON.stringify(site + path)},active:true}).then(tab=>({id:tab.id,url:tab.url,windowId:tab.windowId}))`);
}
async function screenshot(c, name) {
  const image = await c.send('Page.captureScreenshot', { format: 'png' });
  await writeFile(`${output}/${name}.png`, Buffer.from(image.data, 'base64'));
}
try {
  controller = await attach(await newTarget(`${origin}/options.html`));
  await controller.send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await wait(controller, "document.getElementById('settings-form')?.dataset.ready==='true'");
  assert.equal(await evaluate(controller, 'chrome.runtime.getManifest().action.default_popup'), 'popup.html');
  await pdfTabAt('/assignment.pdf');
  beforeTabs = (await targets()).filter(x => x.type === 'page').length;
  beforeReviews = (await targets()).filter(x => x.url.includes('/review.html')).length;
  await check('Real toolbar popup opens without a review tab', async () => {
    await openPopup();
    assert.equal((await targets()).filter(x => x.url.includes('/review.html')).length, beforeReviews);
    const state = await evaluate(popup, "({status:document.getElementById('status').textContent,permission:!document.getElementById('permission').hidden,width:document.body.clientWidth})");
    assert.equal(state.width, 380); console.log('Initial popup:', state); return { width: state.width, site_permission_needed: state.permission };
  });
  await check('Capture starts from the PDF tab with granted access', async () => {
    const needs = await evaluate(popup, "!document.getElementById('permission').hidden");
    if (needs) throw new Error('The test needs a user-granted permission for its loopback fixture site; activeTab did not grant fetch access.');
    await wait(popup, "!document.getElementById('progress').hidden || !document.getElementById('scores').hidden || document.getElementById('status').textContent.includes('unavailable')");
    const state = await evaluate(popup, 'chrome.runtime.sendMessage({channel:"coordinator",type:"init"})');
    assert(state.record && state.record.state !== 'failed', JSON.stringify(state)); return { state: state.record.state };
  });
  let analysis;
  await check('Close/reopen retains the same background analysis', async () => {
    const initial = await evaluate(popup, 'chrome.runtime.sendMessage({channel:"coordinator",type:"init"})');
    analysis = initial.record.id; await closePopup(); await openPopup();
    const reopened = await evaluate(popup, 'chrome.runtime.sendMessage({channel:"coordinator",type:"init"})');
    assert.equal(reopened.record.id, analysis); return { same_session: true };
  });
  await check('Real PDF returns separate text/code percentages', async () => {
    await wait(popup, "!document.getElementById('scores').hidden || !document.getElementById('retry').hidden", 180000);
    const state = await evaluate(popup, "({text:document.getElementById('text-score').textContent,code:document.getElementById('code-score').textContent,status:document.getElementById('status').textContent,ready:!document.getElementById('scores').hidden})");
    assert(state.ready, state.status); assert.match(state.text, /^\d+\.\d%$/); assert.match(state.code, /^\d+\.\d%$/);
    assert(await evaluate(popup, "document.querySelector('.notice').getBoundingClientRect().bottom <= innerHeight"), 'The score caveat must be visible without scrolling.');
    await screenshot(popup, 'popup-results'); return { text: state.text, code: state.code };
  });
  await check('Details reuse the analysis and PDF without another fetch', async () => {
    const oldCount = counts['/assignment.pdf'];
    await evaluate(popup, "document.getElementById('details').click()").catch(error => { if (!/target closed/.test(error.message)) throw error; });
    await wait(controller, `chrome.tabs.query({}).then(tabs=>tabs.find(tab=>tab.url===${JSON.stringify(`${origin}/review.html?analysis=${analysis}`)}))`);
    const reviewTarget = (await targets()).find(x => x.url === `${origin}/review.html?analysis=${analysis}`);
    assert(reviewTarget, 'Details tab was not created.');
    const review = await attach(reviewTarget); await review.send('Emulation.setFocusEmulationEnabled', { enabled: true });
    await wait(review, "document.getElementById('pdf-canvas')?.dataset.renderedPage==='1'", 30000);
    assert.equal(counts['/assignment.pdf'], oldCount);
    await evaluate(review, "document.getElementById('filter').value='analyzed';document.getElementById('filter').dispatchEvent(new Event('change'));document.querySelector('#passages button').click()");
    await wait(review, "Number(document.getElementById('pdf-canvas').dataset.highlightedBoxes)>0");
    await screenshot(review, 'popup-detail-review');
    return { same_session: true, no_pdf_refetch: true, highlighted: true };
  });
  await check('Changing PDFs does not show the prior document score', async () => {
    await pdfTabAt('/second.pdf'); await openPopup();
    const state = await evaluate(popup, 'chrome.runtime.sendMessage({channel:"coordinator",type:"init"})');
    assert.notEqual(state.record?.id, analysis); assert.equal(state.source.name, 'second.pdf');
    const secondId = state.record?.id;
    if (secondId) await evaluate(popup, `chrome.runtime.sendMessage({channel:'coordinator',type:'clear',source:${JSON.stringify(state.source)},id:${JSON.stringify(secondId)}})`);
    await closePopup(); return { isolated: true };
  });
  for (const [path, expected] of [['/login.pdf', 'viewer/login'], ['/redirect.pdf', 'Failed to fetch'], ['/oversize.pdf', '8 MiB']]) {
    await check(`Safe capture fallback: ${path}`, async () => {
      await pdfTabAt(path); await openPopup();
      await wait(popup, "document.getElementById('scores').hidden && !document.getElementById('file').disabled && document.getElementById('status').textContent!== 'Checking the current tab…'", 30000);
      const state = await evaluate(popup, "chrome.runtime.sendMessage({channel:'coordinator',type:'init'})");
      assert.equal(state.record?.state, 'failed');
      assert(state.record.error.includes(expected), state.record.error);
      assert(await evaluate(popup, "document.getElementById('scores').hidden && !document.getElementById('file').disabled"));
      await closePopup(); return { fallback: true };
    });
  }
  await check('Popup file upload works when tab capture is unavailable', async () => {
    await pdfTabAt('/login.pdf'); await openPopup();
    for (let attempt = 0; ; attempt++) {
      try {
        await waitPopup("document.getElementById('scores').hidden && !document.getElementById('file').disabled");
        const dom = await popup.send('DOM.getDocument');
        const input = await popup.send('DOM.querySelector', { nodeId: dom.root.nodeId, selector: '#file' });
        await popup.send('DOM.setFileInputFiles', { nodeId: input.nodeId, files: [resolve('test/16014225801 ML EXP 1.pdf')] });
        await waitPopup("document.getElementById('status').textContent==='Analysis complete'", 180000); break;
      } catch (error) {
        if (attempt >= 2 || !/target closed|interrupted before submission/.test(error.message)) throw error;
        await openPopup();
        await evaluate(popup, "document.getElementById('clear').click()");
        await waitPopup("document.getElementById('clear').hidden");
      }
    }
    assert.equal(await evaluate(popup, "document.getElementById('text-score').textContent"), '54.0%');
    await evaluate(popup, "document.getElementById('clear').click()");
    await waitPopup("document.getElementById('scores').hidden && document.getElementById('clear').hidden");
    const state = await evaluate(popup, "chrome.runtime.sendMessage({channel:'coordinator',type:'init'})");
    assert.equal(state.record, null); await closePopup(); return { file_upload: true, clear: true };
  });
  await check('A prose-only PDF shows code as Not scored, not zero', async () => {
    await pdfTabAt('/prose-only.pdf'); await openPopup();
    await wait(popup, "!document.getElementById('scores').hidden", 180000);
    assert.equal(await evaluate(popup, "document.getElementById('code-score').textContent"), 'Not scored');
    assert.match(await evaluate(popup, "document.getElementById('text-score').textContent"), /^\d+\.\d%$/);
    await closePopup(); return { missing_code: 'Not scored' };
  });
  await check('Local PDFs either capture with file access or explain the setting', async () => {
    const local = new URL(`file://${resolve('test/16014225801 ML EXP 1.pdf')}`).href;
    pdfTab = await evaluate(controller, `chrome.tabs.create({url:${JSON.stringify(local)},active:true}).then(tab=>({id:tab.id,url:tab.url,windowId:tab.windowId}))`);
    await openPopup();
    const state = await evaluate(popup, "chrome.runtime.sendMessage({channel:'coordinator',type:'init'})");
    if (!state.source.target) {
      // Programmatic action.openPopup does not itself grant activeTab for local
      // URLs. A physical toolbar click can; never grant file access in the test.
      assert(await evaluate(popup, "document.getElementById('scores').hidden && document.getElementById('fallback').open && !document.getElementById('file').disabled"));
    }
    else if (!state.fileAccess) assert(await evaluate(popup, "!document.getElementById('local-access').hidden && document.getElementById('scores').hidden"));
    else if (state.permitted) { assert(state.source.target?.local); await wait(popup, "!document.getElementById('scores').hidden", 180000); }
    else assert(await evaluate(popup, "!document.getElementById('permission').hidden"));
    await closePopup(); return { file_access_enabled: state.fileAccess, local_url_visible: !!state.source.target?.local };
  });
  await check('Remote PDF requests never receive backend credentials', async () => { assert(siteHeaders.every(x => !x.backendCredential)); return { checked_requests: siteHeaders.length }; });
  await check('No uncaught popup/review errors', async () => { assert.deepEqual(report.errors, []); return { count: 0 }; });
  // Leave the actual popup with results visible for the user.
  await pdfTabAt('/assignment.pdf'); await openPopup();
  await wait(popup, "!document.getElementById('scores').hidden", 180000); await screenshot(popup, 'popup-live');
} catch (error) {
  process.exitCode = 1; report.run_error = error.message; console.error('FAIL', error.message);
  if (popup) await screenshot(popup, 'popup-failure').catch(() => {});
} finally {
  report.site_requests = counts; report.initial_page_count = typeof beforeTabs === 'number' ? beforeTabs : undefined;
  await writeFile(`${output}/popup-report.json`, JSON.stringify(report, null, 2));
  for (const c of clients) c.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  console.log('Report:', `${output}/popup-report.json`);
}
