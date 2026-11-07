import { detect, allowPDF, capture } from "./capture.js";
import { renderReader, safeURL, percent, validateResult, exportReport } from "./reader.js";
import { connectCompanion } from "./connection.js";
const api = globalThis.browser || globalThis.chrome;
const $ = id => document.getElementById(id);
let token = "", identity = null, sources = [], extracted = null, result = null, job = null, generation = 0, abort = null;
let connecting = null;
const status = value => { $("status").textContent = value; };
if (!api?.sidePanel) document.body.classList.add("popup");

async function helper(path, data, signal, restarted = false) {
  if (!token) await connection();
  let response;
  try {
    response = await fetch("http://127.0.0.1:8790" + path, { method: data === undefined ? "GET" : "POST", headers: { Authorization: "Bearer " + token, ...(data === undefined ? {} : { "Content-Type": "application/json" }) }, body: data === undefined ? undefined : JSON.stringify(data), credentials: "omit", cache: "no-store", signal: signal || AbortSignal.timeout(120_000) });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    if (path === "/health" && !restarted) { await connection(); return helper(path, data, signal, true); }
    throw new Error("The desktop companion disconnected. Click Connect in Settings to restart it automatically");
  }
  const value = await response.json();
  if (!response.ok) throw new Error([401, 403].includes(response.status) ? "Pair this extension and check its local token" : response.status === 422 ? "The document could not be read. Check its text layer and size limits" : response.status === 413 ? "The document exceeds the local size limits" : response.status === 429 ? "The local helper is busy. Wait for the current operation and try again" : "The local operation could not be completed. Check document limits and helper setup");
  if (path === "/health") {
    const names = { text: "Prose classifier", ratio: "Prose comparison", code: "Code classifier", code_match: "Code reference matches", semantic: "Semantic similarity" };
    const labels = { provisioned: "setup complete; inference not guaranteed", insufficient_memory: "insufficient RAM", checkpoint_required: "trained checkpoint required", corpus_required: "reference corpus required", disabled: "disabled in settings", custom_configured: "custom assets; not setup-verified", not_configured: "not configured" };
    const states = Object.entries(value.model_setup || {}).filter(([key, state]) => names[key] && labels[state]).map(([key, state]) => `${names[key]}: ${labels[state]}`);
    $("model-status").textContent = `${states.length ? states.join(". ") : "No automatic model profile reported"}. AI percentages require independent calibration.`;
  }
  return value;
}

function connection() {
  if (connecting) return connecting;
  connecting = (async () => {
    $("connect").disabled = true;
    $("connection-status").textContent = "Starting your local companion…";
    try {
      token = await connectCompanion(api);
      $("token").value = token;
      $("connection-status").textContent = "Desktop companion ready. Connection and pairing are automatic.";
      $("settings").hidden = true;
      return token;
    } catch (error) {
      $("connection-status").textContent = error.message;
      $("settings").hidden = !!token;
      throw error;
    } finally { $("connect").disabled = false; connecting = null; }
  })();
  return connecting;
}

async function active() {
  if (!api?.runtime?.id) throw new Error("Load the extension to read an active document");
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url) throw new Error("The active tab could not be read");
  return tab;
}

async function current(expected) {
  const tab = await active();
  if (!expected || tab.id !== expected.tabId || tab.url !== expected.tabURL) throw new Error("The active tab changed. Read the current document before scanning");
}

function resetScores() {
  for (const id of ["ai-score", "copy-score"]) { $(id).textContent = "—"; $(id).classList.remove("unavailable"); }
  $("copy-coverage").textContent = $("ai-coverage").textContent = "Not checked";
  $("export").disabled = true;
  $("detail").hidden = true;
}

function invalidate(clearText = true) {
  generation++;
  abort?.abort(); abort = null;
  if (job) helper(`/jobs/${job}/cancel`, {}).catch(() => {});
  job = null; result = null; resetScores();
  $("cancel").hidden = true; $("extract").disabled = false;
  if (clearText) { extracted = null; identity = null; $("reader").textContent = "Read the active document to begin."; }
  else if (extracted) $("reader").textContent = extracted.text;
  $("scan").disabled = !extracted;
}

async function discover() {
  const tab = await active();
  sources = await detect(tab);
  identity = { tabId: tab.id, tabURL: tab.url, title: tab.title || "Active document" };
  $("document-title").textContent = identity.title;
  $("surface").textContent = sources[0].kind === "pdf" ? "ACTIVE PDF" : "CURRENT WEBSITE";
  $("source").replaceChildren();
  for (const [index, source] of sources.entries()) { const option = document.createElement("option"); option.value = String(index); option.textContent = `${source.label} · ${source.url}`; $("source").append(option); }
  $("source-label").hidden = sources.length < 2;
  return identity;
}

$("extract").addEventListener("click", async () => {
  const selectedURL = sources[Number($("source").value) || 0]?.url;
  invalidate();
  const version = generation;
  $("extract").disabled = true;
  abort = new AbortController();
  try {
    const expected = await discover();
    const selectedIndex = sources.findIndex(source => source.url === selectedURL);
    if (selectedIndex >= 0) $("source").value = String(selectedIndex);
    const source = sources[Number($("source").value) || 0];
    if (source.kind === "pdf") await allowPDF(source);
    if (version !== generation) return;
    await current(expected);
    await helper("/health");
    status("Reading the active document on this device…");
    const snapshot = await capture(source, helper, abort.signal);
    await current(expected);
    if (version !== generation) return;
    if (!snapshot.text?.trim() || snapshot.text.length > 200_000) throw new Error("No supported document text was found");
    extracted = snapshot;
    identity = { ...expected, sourceURL: source.url, kind: source.kind };
    $("reader").textContent = snapshot.text;
    $("document-note").textContent = `${snapshot.text.length.toLocaleString()} characters · ${snapshot.note || "Review the extracted text before scanning."}${snapshot.empty_pages?.length ? " Some pages have no text layer and are excluded." : ""}`;
    $("scan").disabled = false;
    status("Text ready. Enable web comparison if you also want source-overlap results.");
  } catch (error) { if (version === generation && error.name !== "AbortError") status(error.message); }
  finally { if (version === generation) $("extract").disabled = false; }
});

$("source").addEventListener("change", () => {
  const oldIdentity = identity;
  invalidate(); identity = oldIdentity;
  status("PDF selection changed. Read the selected PDF before scanning.");
});

function showDetail(row) {
  const detail = $("detail"); detail.replaceChildren(); detail.hidden = false;
  const heading = document.createElement("strong"); heading.textContent = "Segment evidence"; detail.append(heading);
  for (const message of [`AI estimate: ${percent(row.ai.score)} · classification confidence: ${percent(row.ai.confidence)} · ${row.ai.status.replaceAll("_", " ")}`, `Source similarity: ${percent(row.plagiarism.score)} · match confidence: ${percent(row.plagiarism.confidence)} · ${row.plagiarism.status.replaceAll("_", " ")}`]) { const paragraph = document.createElement("p"); paragraph.textContent = message; detail.append(paragraph); }
  const url = safeURL(row.plagiarism.match?.url);
  if (url) { const link = document.createElement("a"); link.href = url; link.textContent = url; link.target = "_blank"; link.rel = "noopener noreferrer"; detail.append(link); }
}

function showResult(value) {
  result = validateResult(value, extracted.text);
  for (const [key, scoreId, coverageId] of [["ai", "ai-score", "ai-coverage"], ["plagiarism", "copy-score", "copy-coverage"]]) {
    const overall = result.overall[key];
    const available = Number.isFinite(overall.percent);
    $(scoreId).textContent = available ? `${Math.round(overall.percent)}%` : overall.status === "not_checked" ? "Not checked" : "Unavailable";
    $(scoreId).classList.toggle("unavailable", !available);
    $(coverageId).textContent = `${percent(key === "ai" ? overall.coverage : overall.search_coverage)} ${key === "ai" ? "scored" : "search coverage"}${overall.status !== "complete" ? " · incomplete" : ""}`;
  }
  renderReader($("reader"), result.text, result.segments, showDetail);
  $("export").disabled = false;
  status("Review complete. Percentages apply only to scored text; unavailable and unchecked passages are not counted as original.");
}

const delay = (ms, signal) => new Promise((resolve, reject) => {
  const cancel = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
  const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, ms);
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
});

$("scan").addEventListener("click", async () => {
  if (!extracted) return;
  invalidate(false);
  const version = generation, expected = identity;
  const controller = new AbortController(); abort = controller;
  $("scan").disabled = true; $("extract").disabled = true; $("cancel").hidden = false;
  try {
    await current(expected);
    await helper("/health");
    const created = await helper("/jobs", { text: extracted.text, consent: $("consent").checked, source_url: expected.sourceURL }, controller.signal);
    if (version !== generation) { helper(`/jobs/${created.id}/cancel`, {}).catch(() => {}); return; }
    job = created.id;
    while (version === generation) {
      await current(expected);
      const value = await helper(`/jobs/${job}`, undefined, controller.signal);
      if (value.state === "completed") {
        await current(expected);
        if (expected.kind === "website") {
          const refreshed = await capture({ kind: "website", tabId: expected.tabId }, helper, controller.signal);
          if (refreshed.text !== extracted.text) throw new Error("Website text changed. Read and scan its current version");
        }
        if (version === generation) showResult(value.result);
        break;
      }
      if (["cancelled", "error"].includes(value.state)) throw new Error(value.state === "cancelled" ? "Scan cancelled" : "The local scan could not be completed");
      const p = value.progress || {};
      status(p.stage === "sources" ? `Comparing sources · ${p.done} / ${p.total} segments` : `Checking authorship locally · ${p.done || 0} / ${p.total || "…"} segments`);
      await delay(1000, controller.signal);
    }
  } catch (error) {
    if (version === generation && error.name !== "AbortError") { if (job) helper(`/jobs/${job}/cancel`, {}).catch(() => {}); status(error.message); }
  } finally { if (version === generation) { job = null; $("scan").disabled = false; $("extract").disabled = false; $("cancel").hidden = true; } }
});

$("cancel").addEventListener("click", () => { invalidate(false); status("Scan cancelled. No incomplete scan results are shown."); });
$("clear").addEventListener("click", () => { invalidate(); status("Document text and results cleared from this panel."); });
$("consent").addEventListener("change", () => { invalidate(false); status("Comparison preference changed. Scan again to update results."); });
$("settings-button").addEventListener("click", () => { $("settings").hidden = !$("settings").hidden; $("settings-button").setAttribute("aria-expanded", String(!$("settings").hidden)); });
$("connect").addEventListener("click", async () => {
  invalidate();
  try { await connection(); status("Local companion ready. Read the active PDF or website."); }
  catch (error) { status(error.message); }
});
$("save").addEventListener("click", async () => {
  invalidate(); token = $("token").value.trim();
  if (api?.runtime?.id) await api.storage.local.set({ pairingToken: token });
  try { await helper("/health"); $("settings").hidden = true; status("Local helper connected. Read the active PDF or website."); } catch (error) { status(error.message); }
});
$("export").addEventListener("click", async () => {
  if (!result) return;
  try {
    await current(identity);
    const file = exportReport(result, identity, $("format").value);
    const url = URL.createObjectURL(new Blob([file.content], { type: file.type }));
    const link = document.createElement("a"); link.href = url; link.download = `verity-review.${file.extension}`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { status(error.message); }
});

async function initialize() {
  if (!api?.runtime?.id) { status("Load the extension in your browser to review an active document."); return; }
  token = (await api.storage.local.get("pairingToken")).pairingToken || "";
  $("token").value = token;
  $("origin").textContent = `Pair this origin: ${api.runtime.getURL("").replace(/\/$/, "")}`;
  $("settings").hidden = true;
  api.runtime.onMessage.addListener(message => { if (message.type === "verity.invalidated" && message.tabId === identity?.tabId) { invalidate(); status("The original tab navigated. Read the current document again."); } });
  api.tabs.onActivated.addListener(() => { if (identity) { invalidate(); status("Active tab changed. Read the current document again."); } });
  const ready = (async () => {
    if (token) {
      try { await helper("/health", undefined, undefined, true); return; } catch { /* Restart a stopped companion through its native host. */ }
    }
    await connection();
  })();
  ready.catch(() => {});
  try { await discover(); await ready; status("Local companion ready. Read the active document to begin."); }
  catch (error) { status(error.message); }
}
initialize();
