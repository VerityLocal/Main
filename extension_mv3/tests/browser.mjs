import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { chromium } from "playwright";

const root = resolve("."), artifacts = resolve("../artifacts");
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css" };
const server = createServer(async (request, response) => {
  try {
    const path = resolve(root, "." + new URL(request.url, "http://localhost").pathname);
    if (!path.startsWith(root + sep)) throw new Error("Invalid fixture path");
    const bytes = await readFile(path);
    response.writeHead(200, { "Content-Type": mime[extname(path)] || "application/octet-stream" }); response.end(bytes);
  } catch { response.writeHead(404); response.end("Not found"); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
let browser;
const cases = [], errors = [];
async function check(name, fn) { await fn(); cases.push({ name, passed: true }); console.log(`PASS ${name}`); }
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_EXECUTABLE || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" });
  const page = await browser.newPage({ viewport: { width: 900, height: 750 } });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(base + "/dist/panel.html");
  await check("static DOM range geometry, Unicode, and non-destructive highlights", async () => {
    const result = await page.evaluate(async () => {
      const { StaticDomAdapter } = await import("/src/adapters/static_dom/index.js");
      const { Highlighter } = await import("/src/overlay/index.js");
      document.body.innerHTML = '<article style="font:18px/1.6 Arial;width:330px;margin:30px"><p>😀 Café <b>bold inline</b><br>next line.</p><p hidden>Secret</p><nav>Menu</nav><div id="shadow"></div></article>';
      document.querySelector("#shadow").attachShadow({ mode: "open" }).innerHTML = "<p>Open shadow text.</p>";
      const root = document.querySelector("article"), before = root.innerHTML;
      const adapter = new StaticDomAdapter(root); window.fixtureAdapter = adapter;
      const snapshot = adapter.extractText();
      const start = snapshot.extracted_text.indexOf("Café"), end = snapshot.extracted_text.indexOf("\nnext");
      const ranges = adapter.ranges(start, end);
      const highlighter = new Highlighter(adapter); highlighter.apply([{ start_offset: start, end_offset: end, category: "EXACT_OVERLAP" }]);
      const rects = adapter.mapOffsetsToRects(start, end);
      const result = { text: snapshot.extracted_text, selected: ranges.map(r => r.toString()).join(""),
        unchanged: root.innerHTML === before, rectCount: rects.length, positive: rects.every(r => r.width > 0 && r.height > 0) };
      highlighter.destroy(); return result;
    });
    assert.equal(result.selected, "Café bold inline"); assert.ok(result.text.includes("Open shadow text."));
    assert.ok(!result.text.includes("Secret") && !result.text.includes("Menu"));
    assert.ok(result.unchanged && result.rectCount > 0 && result.positive);
  });
  await check("text control mirror geometry, scroll, selection and mutation", async () => {
    const result = await page.evaluate(async () => {
      const { TextControlAdapter } = await import("/src/adapters/textarea/index.js");
      const { Highlighter } = await import("/src/overlay/index.js");
      document.body.innerHTML = '<textarea style="font:16px/24px Arial;width:240px;height:96px;padding:9px;margin:30px;">😀 Café first line\nsecond line\nthird line\nfourth line\nfifth line</textarea>';
      const control = document.querySelector("textarea"); control.setSelectionRange(2, 6); control.scrollTop = 24;
      const adapter = new TextControlAdapter(control); adapter.extractText();
      let changes = 0; adapter.subscribeToChanges(() => changes++);
      const start = control.value.indexOf("second"), rects = adapter.mapOffsetsToRects(start, start + 6);
      const before = { value: control.value, start: control.selectionStart, end: control.selectionEnd, scroll: control.scrollTop };
      const highlighter = new Highlighter(adapter); highlighter.apply([{ start_offset: start, end_offset: start + 6, category: "EXACT_OVERLAP" }]);
      highlighter.paint();
      const unchanged = control.value === before.value && control.selectionStart === before.start && control.selectionEnd === before.end && control.scrollTop === before.scroll;
      control.value += " changed"; control.dispatchEvent(new Event("input"));
      const staleRects = adapter.mapOffsetsToRects(start, start + 6).length;
      highlighter.destroy(); adapter.destroy();
      return { unchanged, rectCount: rects.length, positive: rects.every(r => r.right > r.left && r.bottom > r.top), changes, staleRects };
    });
    assert.ok(result.unchanged && result.rectCount > 0 && result.positive);
    assert.equal(result.changes, 1); assert.equal(result.staleRects, 0);
  });
  await check("rendered editor-shaped fixtures retain DOM and invalidate mutations", async () => {
    const result = await page.evaluate(async () => {
      const { chooseAdapter } = await import("/src/adapters/index.js");
      const outputs = [];
      for (const marker of ['class="ProseMirror"', 'class="ql-editor"', 'data-lexical-editor="true"', 'data-slate-editor="true"']) {
        document.body.innerHTML = `<div ${marker} contenteditable="true"><p>😀 Editor <b>inline</b> text.</p></div>`;
        const adapter = chooseAdapter(document), html = adapter.root.innerHTML;
        const snapshot = adapter.extractText(); let changes = 0;
        adapter.subscribeToChanges(() => changes++);
        const positive = adapter.mapOffsetsToRects(0, 2).length > 0;
        adapter.root.querySelector("p").append(" New revision.");
        await new Promise(resolve => requestAnimationFrame(resolve));
        outputs.push({ surface: adapter.surface, text: snapshot.extracted_text, positive, changes,
          unchangedBeforeMutation: html === '<p>😀 Editor <b>inline</b> text.</p>' });
        adapter.destroy();
      }
      return outputs;
    });
    assert.equal(result.length, 4);
    for (const item of result) assert.ok(item.positive && item.changes > 0 && item.unchangedBeforeMutation);
  });
  await check("content-script snapshot rejects stale highlights after mutation", async () => {
    await page.evaluate(() => {
      document.body.innerHTML = "<article><p>😀 Current document text.</p></article>";
      window.messages = [];
      window.chrome = { runtime: { id: "fixture", onMessage: { addListener(fn) { window.contentListener = fn; } }, sendMessage(message) { window.messages.push(message); return Promise.resolve(); } } };
    });
    await page.addScriptTag({ url: base + "/dist/content.js" });
    const result = await page.evaluate(async () => {
      let extracted; window.contentListener({ type: "verity.extract" }, { id: "fixture" }, result => { extracted = result; });
      const old = extracted.extraction;
      document.querySelector("p").textContent = "New document revision.";
      await new Promise(resolve => requestAnimationFrame(resolve));
      let highlighted; window.contentListener({ type: "verity.highlight", document_id: old.document_id, revision: old.revision, findings: [] }, { id: "fixture" }, result => { highlighted = result; });
      return { changed: window.messages.some(m => m.type === "verity.document.changed"), error: highlighted.error };
    });
    assert.ok(result.changed); assert.match(result.error, /Stale/);
  });
  await check("panel preview loads, counts Unicode and prevents empty submission", async () => {
    await page.goto(base + "/dist/panel.html");
    await page.locator("#document-text").fill("😀 private text");
    assert.match(await page.locator("#character-count").innerText(), /15 UTF-16/);
    await page.locator("#document-text").fill(""); await page.locator("#analyze").click();
    assert.equal(await page.locator("#status").innerText(), "Add some text first");
    assert.ok(await page.locator("#analyze").isEnabled());
    await page.setViewportSize({ width: 430, height: 1050 });
    await mkdir(artifacts, { recursive: true });
    await page.screenshot({ path: resolve(artifacts, "extension_panel.png"), fullPage: true });
  });
  await check("panel synthetic transport streams results and invalidates manual edits", async () => {
    const ui = await browser.newPage({ viewport: { width: 430, height: 1050 } });
    ui.on("pageerror", error => errors.push(error.message));
    await ui.addInitScript(() => {
      const store = { preferences: { auth: "synthetic-auth", csrf: "synthetic-csrf", excluded: [] } };
      window.chrome = { runtime: { id: "a".repeat(32) }, storage: {
        local: { async get() { return store; }, async set(value) { Object.assign(store, value); } },
        onChanged: { addListener() {} },
      } };
    });
    let submitted;
    await ui.route("http://127.0.0.1:8787/api/v1/**", async route => {
      const request = route.request(), path = new URL(request.url()).pathname;
      const headers = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS" };
      if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
      let result = {};
      if (path.endsWith("/health")) result = { hardware: {} };
      else if (path.endsWith("/models/status")) result = { external_search_enabled: false, detector_checkpoint_configured: false };
      else if (path.endsWith("/sources")) result = { sources: [] };
      else if (path.endsWith("/analyses/text")) {
        submitted = request.postDataJSON().extraction;
        result = { request_id: "synthetic-request", document_id: submitted.document_id, document_revision: submitted.revision };
      } else if (path.endsWith("/events")) {
        const payloads = [["analysis.started", {}], ["ai_detection.completed", { status: "unavailable", findings: [], reason: "Synthetic missing-model fixture" }],
          ["plagiarism.completed", { status: "completed", findings: [{ finding_id: "one", category: "EXACT_OVERLAP", start_offset: 0, end_offset: 2, confidence: null }] }],
          ["analysis.completed", { status: "completed" }]];
        const body = payloads.map(([name, payload], i) => `event: ${name}\ndata: ${JSON.stringify({ request_id: "synthetic-request", document_id: submitted.document_id,
          document_revision: submitted.revision, offset_unit: "utf16_code_unit", sequence: i+1, payload })}\n\n`).join("");
        return route.fulfill({ status: 200, headers, contentType: "text/event-stream", body });
      }
      await route.fulfill({ status: 200, headers, contentType: "application/json", body: JSON.stringify(result) });
    });
    await ui.goto(base + "/dist/panel.html");
    await ui.locator("#document-text").fill("😀 Synthetic fixture text.");
    await ui.locator("#analyze").click();
    await ui.locator("#results .finding").waitFor();
    assert.equal(await ui.locator("#finding-count").innerText(), "1 FINDINGS");
    assert.match(await ui.locator("#engine-statuses").innerText(), /unavailable/);
    await ui.locator("#document-text").fill("Revised fixture text.");
    assert.equal(await ui.locator("#finding-count").innerText(), "0 FINDINGS");
    assert.ok(await ui.locator("#analyze").isEnabled());
    await ui.close();
  });
  assert.deepEqual(errors, []);
  const report = { browser: await browser.version(), platform: process.platform, cases,
    limitations: "Rendered fixture tests only; not editor framework integration, real MV3 installation, or accuracy evaluation." };
  await writeFile(resolve(artifacts, "browser_validation.json"), JSON.stringify(report, null, 2));
  console.log(`${cases.length} real-Chrome fixture checks passed.`);
} finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
