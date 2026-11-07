import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { pdfURL, detect, permissionPattern } from "../extension/capture.js";
import { safeURL, renderReader, validateResult, exportReport } from "../extension/reader.js";
import { connectCompanion } from "../extension/connection.js";

test("active PDF URLs and native viewer parameters", () => {
  assert.equal(pdfURL("https://example.org/PAPER.PDF?token=x#page=2"), "https://example.org/PAPER.PDF?token=x#page=2");
  assert.equal(pdfURL("file:///documents/paper.pdf"), "file:///documents/paper.pdf");
  assert.equal(pdfURL("chrome-extension://viewer/index.html?file=https%3A%2F%2Fexample.org%2Fpaper.pdf"), "https://example.org/paper.pdf");
  assert.equal(pdfURL("https://example.org/page"), null);
  assert.equal(pdfURL("javascript:alert(1)"), null);
});

test("embedded PDFs take precedence over website and duplicate candidates", async () => {
  globalThis.chrome = { scripting: { executeScript: async () => [{ frameId: 0, result: { candidates: [{ url: "https://example.org/one.pdf", label: "one" }, { url: "https://example.org/two.pdf", label: "two" }] } }, { frameId: 2, result: { viewer: true, url: "https://example.org/one.pdf" } }] } };
  const sources = await detect({ id: 1, url: "https://example.org/article" });
  assert.equal(sources.length, 2);
  assert.ok(sources.every(row => row.kind === "pdf"));
  assert.equal(sources[0].viewer, true);
  delete globalThis.chrome;
});

test("PDF permissions are narrowed to origin and URLs are safe", () => {
  assert.equal(permissionPattern("https://example.org/file.pdf"), "https://example.org/*");
  assert.equal(permissionPattern("file:///file.pdf"), "file:///*");
  assert.equal(safeURL("javascript:alert(1)"), null);
  assert.equal(safeURL("https://user:pass@example.org/"), null);
});

const row = { id: "s0", start: 0, end: 10, text: "Hello 🦊! ", ai: { score: .8, confidence: .8, status: "scored" }, plagiarism: { score: .9, confidence: null, status: "checked", match: { url: "https://example.org/" } } };

test("UTF-16 reader ranges are exact and stale results rejected", () => {
  const result = { schema_version: 1, text: row.text, segments: [row] };
  assert.equal(validateResult(result, row.text), result);
  assert.throws(() => validateResult(result, "different"));
  assert.throws(() => validateResult({ ...result, segments: [{ ...row, end: 100 }] }, row.text));
  assert.throws(() => validateResult({ ...result, segments: [{ ...row, ai: { score: NaN } }] }, row.text));
});

test("safe original-text rendering retains both highlight colors and null confidence", () => {
  const doc = { createTextNode: text => ({ textContent: text }), createElement: () => ({ attributes: {}, events: {}, setAttribute(k, v) { this.attributes[k] = v; }, addEventListener(k, v) { this.events[k] = v; } }) };
  const container = { ownerDocument: doc, children: [], replaceChildren() { this.children = []; }, append(value) { this.children.push(value); } };
  renderReader(container, row.text, [row], () => {});
  const span = container.children[1];
  assert.equal(span.textContent, row.text);
  assert.match(span.className, /copied artificial/);
  assert.match(span.title, /Source: https:\/\/example.org/);
  assert.equal(span.tabIndex, 0);
  assert.equal(span.innerHTML, undefined);
});

test("exports include coverage and evidence without exposing credentials", () => {
  const value = { text: row.text, segments: [row], notes: ["Signals, not proof"], overall: { ai: { percent: 80, coverage: 1 }, plagiarism: { percent: 90, search_coverage: .5 } } };
  assert.match(exportReport(value, { title: "Example" }, "txt").content, /search coverage: 50%/);
  assert.equal(JSON.parse(exportReport(value, { title: "Example" }, "json").content).segments[0].ai.score, .8);
});

test("desktop companion pairs automatically through the narrow native host", async () => {
  const origin = "chrome-extension://" + "a".repeat(32);
  let stored;
  const api = { runtime: { id: "a".repeat(32), getURL: () => origin + "/", sendNativeMessage: async (host, message) => {
    assert.equal(host, "local.verity.helper");
    assert.deepEqual(message, { type: "bootstrap", protocol: 1, origin });
    return { protocol: 1, origin, ready: true, token: "t".repeat(43) };
  } }, storage: { local: { set: async value => { stored = value; } } } };
  assert.equal(await connectCompanion(api), "t".repeat(43));
  assert.deepEqual(stored, { pairingToken: "t".repeat(43) });
});

test("missing or malformed native hosts never store arbitrary tokens", async () => {
  const origin = "chrome-extension://" + "a".repeat(32);
  const api = { runtime: { id: "a".repeat(32), getURL: () => origin + "/", sendNativeMessage: async () => { throw new Error("private native path"); } }, storage: { local: { set: async () => { throw new Error("Should not persist"); } } } };
  await assert.rejects(connectCompanion(api), /Install the Verity desktop companion once/);
  api.runtime.sendNativeMessage = async () => ({ protocol: 1, ready: true, origin: "https://evil.invalid", token: "t".repeat(43) });
  await assert.rejects(connectCompanion(api), /could not start/);
  api.runtime.sendNativeMessage = async () => ({ protocol: 1, ready: false, code: "port_conflict" });
  await assert.rejects(connectCompanion(api), /Another local service/);
});

test("build only ships first-party surfaces, no internal upstream identities", async () => {
  const forbidden = /GPTSniffer|ai-gen-code-search|binoculars|desklib|docling|playwright/i;
  for (const target of ["chrome", "firefox"]) {
    const entries = await readdir(`product/dist/${target}`);
    assert.equal(entries.length, 11);
    for (const name of entries) {
      assert.doesNotMatch(await readFile(`product/dist/${target}/${name}`, "utf8"), forbidden);
      assert.doesNotMatch(name, /model.card|internal|README|\.env/);
    }
    const manifest = JSON.parse(await readFile(`product/dist/${target}/manifest.json`, "utf8"));
    assert.equal(manifest.manifest_version, 3);
    assert.equal(!!manifest.side_panel, target === "chrome");
    assert.ok(manifest.permissions.includes("nativeMessaging"));
    assert.equal(!!manifest.key, target === "chrome");
  }
  // Public documentation discloses actual model availability; runtimes/weights
  // still never enter the first-party extension payload.
  const readme = await readFile("README.md", "utf8");
  assert.match(readme, /independently calibrated/);
  assert.match(readme, /model availability/);
});
