// Capture the real extension using only the bundled public demonstration PDF.
// Requires: a visible Chrome for Testing profile with extension/ loaded and CDP
// on loopback port 9223, plus the matching authenticated backend on port 8000.
// Start the backend with the ID displayed on that profile's extension card.
// CHROMIUM_APP may point to the app bundle when activating it on macOS.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { connect, evaluate, waitExpression } from '../extension/scripts/cdp.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = resolve(root, 'docs/screenshots');
const example = resolve(root, 'docs/examples/verity-local-demo.pdf');
const id = [...createHash('sha256').update(resolve(root, 'extension')).digest('hex').slice(0, 32)]
  .map(value => String.fromCharCode(97 + parseInt(value, 16))).join('');
const origin = `chrome-extension://${id}`;
const endpoint = 'http://127.0.0.1:9223';
const clients = [];
const report = { version: '0.4.0', source: 'Actual Chrome extension with real local models',
  example: 'docs/examples/verity-local-demo.pdf', example_sha256: createHash('sha256').update(await readFile(example)).digest('hex'),
  screenshots: [], errors: [] };
await mkdir(output, { recursive: true });

async function targets() { return (await fetch(`${endpoint}/json/list`)).json(); }
async function attach(target) {
  const client = await connect(target.webSocketDebuggerUrl);
  clients.push(client);
  await client.send('Runtime.enable');
  await client.send('Page.enable');
  await client.send('Emulation.setFocusEmulationEnabled', { enabled: true });
  client.on('Runtime.exceptionThrown', event => report.errors.push(event.exceptionDetails.exception?.description || event.exceptionDetails.text));
  return client;
}
async function page(url, width = 1440, height = 1000) {
  const target = await (await fetch(`${endpoint}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json();
  const client = await attach(target);
  await client.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await client.send('Page.bringToFront');
  return client;
}
async function wait(client, expression, timeout = 30000) { return evaluate(client, waitExpression(expression, timeout)); }
async function capture(client, name, bringToFront = true) {
  if (bringToFront) await client.send('Page.bringToFront');
  const image = await client.send('Page.captureScreenshot', { format: 'webp', quality: 95, captureBeyondViewport: false });
  await writeFile(resolve(output, `${name}.webp`), Buffer.from(image.data, 'base64'));
  const dimensions = await evaluate(client, '({width:innerWidth,height:innerHeight})');
  report.screenshots.push({ name: `${name}.webp`, ...dimensions });
  console.log(`Captured ${name}: ${dimensions.width} × ${dimensions.height}`);
}
async function upload(client, path) {
  const document = await client.send('DOM.getDocument');
  const input = await client.send('DOM.querySelector', { nodeId: document.root.nodeId, selector: '#file' });
  await client.send('DOM.setFileInputFiles', { nodeId: input.nodeId, files: [path] });
}
const deepElements = `(() => { const result = []; function walk(root) { for (const element of root.querySelectorAll('*')) { result.push(element); if (element.shadowRoot) walk(element.shadowRoot); } } walk(document); return result; })()`;

try {
  const extensions = await page('chrome://extensions', 1440, 700);
  await wait(extensions, `(${deepElements}).some(element => element.tagName === 'EXTENSIONS-ITEM' && element.id === ${JSON.stringify(id)})`);
  await evaluate(extensions, `(() => { const toggle = (${deepElements}).find(element => element.id === 'devMode'); if (!toggle.checked) toggle.click(); })()`);
  await wait(extensions, `(${deepElements}).find(element => element.id === 'devMode')?.checked`);
  await capture(extensions, 'install-extension');

  const settings = await page(`${origin}/options.html`, 900, 700);
  await wait(settings, "document.getElementById('settings-form')?.dataset.ready === 'true'");
  const token = (await readFile(resolve(root, '.local/backend-token'), 'utf8')).trim();
  await evaluate(settings, `(() => { document.getElementById('backend').value='http://127.0.0.1:8000'; document.getElementById('token').value=${JSON.stringify(token)}; document.getElementById('settings-form').requestSubmit(); })()`);
  await wait(settings, "document.getElementById('status').textContent === 'Connected. Backend ready.'", 180000);
  assert.equal(await evaluate(settings, "document.getElementById('token').type"), 'password');
  assert.equal(await evaluate(settings, 'chrome.runtime.getManifest().name'), 'Verity Local');
  await capture(settings, 'settings');

  const tab = await evaluate(settings, "chrome.tabs.create({url:'about:blank',active:true}).then(tab=>({id:tab.id,windowId:tab.windowId}))");
  const app = process.env.CHROMIUM_APP || resolve(homedir(), 'Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app');
  if (process.platform === 'darwin' && existsSync(app)) execFileSync('/usr/bin/open', [app]);
  await evaluate(settings, `chrome.windows.update(${tab.windowId},{focused:true}).then(()=>chrome.tabs.update(${tab.id},{active:true}))`);
  await wait(settings, `chrome.windows.get(${tab.windowId}).then(window=>window.focused)`);
  await evaluate(settings, `chrome.action.openPopup({windowId:${tab.windowId}})`);
  const popupTarget = (await targets()).find(target => target.url === `${origin}/popup.html`);
  assert(popupTarget, 'Chrome must open an actual toolbar popup.');
  const popup = await attach(popupTarget);
  await wait(popup, "document.body?.dataset.ready === 'true'");
  await upload(popup, example);
  await wait(popup, "!document.getElementById('scores').hidden", 180000);
  report.results = await evaluate(popup, "({text:document.getElementById('text-score').textContent,code:document.getElementById('code-score').textContent,coverage:document.getElementById('coverage').textContent})");
  assert.match(report.results.text, /^\d+\.\d%$/);
  assert.match(report.results.code, /^\d+\.\d%$/);
  await capture(popup, 'popup', false);

  const state = await evaluate(popup, "chrome.runtime.sendMessage({channel:'coordinator',type:'init'})");
  await evaluate(popup, "document.getElementById('details').click()").catch(error => {
    if (!/target closed/.test(error.message)) throw error;
  });
  await wait(settings, `chrome.tabs.query({}).then(tabs=>tabs.some(tab=>tab.url===${JSON.stringify(`${origin}/review.html?analysis=${state.record.id}`)}))`);
  const reviewTarget = (await targets()).find(target => target.url === `${origin}/review.html?analysis=${state.record.id}`);
  const review = await attach(reviewTarget);
  await review.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await wait(review, "document.getElementById('pdf-canvas')?.dataset.renderedPage === '1'", 60000);
  await evaluate(review, 'window.scrollTo(0,0)');
  await capture(review, 'review-overview');
  await evaluate(review, "document.getElementById('filter').value='analyzed';document.getElementById('filter').dispatchEvent(new Event('change'));document.querySelector('#passages details').open=true;document.querySelector('#passages button').click()");
  await wait(review, "Number(document.getElementById('pdf-canvas').dataset.highlightedBoxes)>0");
  await evaluate(review, "document.querySelector('.workspace').scrollIntoView({block:'start'})");
  await capture(review, 'evidence');
  assert.deepEqual(report.errors, []);
  await writeFile(resolve(output, 'capture.json'), JSON.stringify(report, null, 2) + '\n');
  console.log('All screenshots use genuine local inference and the public demo. Token remains masked.');
} finally {
  for (const client of clients) client.close();
}
