import { consumeSSE, acceptEvent } from "../messaging/sse.js";

const $ = id => document.getElementById(id);
const extension = typeof chrome !== "undefined" && !!chrome.runtime?.id;
const API = "http://127.0.0.1:8787/api/v1";
let preferences = { auth: "", csrf: "", excluded: [] }, extraction = null, tabId = null, analysis = null, controller = null;
let manualRevision = 0, manualId = `document_${crypto.randomUUID()}`, findings = new Map();
const statuses = new Map();
let generation = 0;
function invalidate() {
  generation++;
  const previous = analysis;
  controller?.abort(); analysis = null; findings.clear(); statuses.clear(); render();
  $("cancel").classList.add("hidden"); $("analyze").disabled = false;
  if (previous?.tabId != null && extension) chrome.tabs.sendMessage(previous.tabId, { type: "verity.clear" }).catch(() => {});
  if (previous && !previous.terminal) api(`/analyses/${previous.request_id}/cancel`, { method: "POST", body: "{}" }).catch(() => {});
  saveState().catch(() => {});
}
function status(message) { $("status").textContent = message; }
async function saveState() { if (extension) await chrome.storage.local.set({ analysisState: analysis }); }
function headers(post = false) { return { "X-Local-Token": preferences.auth, ...(post ? { "X-CSRF-Token": preferences.csrf, "Content-Type": "application/json" } : {}) }; }
async function api(path, options = {}) {
  const response = await fetch(API + path, { ...options, headers: { ...headers(!!options.method), ...options.headers }, signal: options.signal || AbortSignal.timeout(12000), credentials: "omit", cache: "no-store" });
  if (!response.ok) {
    let message = `Local backend returned ${response.status}`;
    try { message = (await response.json()).error?.message || message; } catch {}
    throw new Error(message);
  }
  return response;
}
async function connect() {
  try {
    const health = await (await api("/health")).json();
    $("connection-dot").classList.add("connected");
    $("connection-label").textContent = "Connected to your local backend";
    const models = await (await api("/models/status")).json();
    $("external-consent").disabled = !models.external_search_enabled;
    $("engine-ai").parentElement.querySelector("small").textContent = models.detector_checkpoint_configured ? "Local checkpoint configured" : "No trained checkpoint — unavailable";
    await refreshSources();
    status(`Local analysis ready. ${health.hardware.driver_gpus?.[0]?.name || "CPU profile"}. No model-fit guarantee.`);
    return true;
  } catch (error) {
    $("connection-dot").classList.remove("connected");
    $("connection-label").textContent = "Local backend disconnected";
    status(error.message.includes("Failed to fetch") ? "Start the backend, pair this extension origin, and enter both local tokens." : error.message);
    return false;
  }
}
function safeURL(value) { try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : null; } catch { return null; } }
function textElement(tag, text, className) { const element = document.createElement(tag); element.textContent = text; if (className) element.className = className; return element; }
function render() {
  $("results").replaceChildren(); $("engine-statuses").replaceChildren();
  $("finding-count").textContent = `${findings.size} FINDINGS`;
  $("empty-state").classList.toggle("hidden", !!findings.size || !!statuses.size);
  for (const [engine, result] of statuses) {
    let message = `${engine.replaceAll("_", " ")}: ${result.status}. ${result.reason || ""}`;
    if (engine === "ai_detection" && Number.isFinite(result.document_score)) {
      const label = result.diagnostics?.document_label_policy === "contains_annotated_ai_v1" ? "Chance the document contains AI text (including mixed writing)" : "Document AI estimate";
      message += ` ${label}: ${Math.round(result.document_score * 100)}%.`;
      if (!result.diagnostics?.calibrated) message += " Uncalibrated.";
    }
    $("engine-statuses").append(textElement("div", message, `engine-summary ${result.status}`));
  }
  for (const finding of findings.values()) {
    const item = textElement("li", "", "finding");
    const head = textElement("div", "", "finding-head");
    head.append(textElement("strong", finding.category.replaceAll("_", " ").toLowerCase()));
    head.append(textElement("small", finding.confidence == null ? "uncalibrated / candidate" : `calibrated estimate ${Math.round(finding.confidence * 100)}%`));
    item.append(head);
    const excerpt = finding.original_text || extraction?.extracted_text.slice(finding.start_offset, finding.end_offset) || "";
    if (excerpt) item.append(textElement("p", excerpt.slice(0, 350)));
    const source = finding.source_title || finding.evidence?.[0]?.title;
    const url = safeURL(finding.source_url || finding.evidence?.[0]?.url);
    if (source) {
      const citation = textElement(url ? "a" : "small", `↗ ${source}`);
      if (url) { citation.href = url; citation.target = "_blank"; citation.rel = "noopener noreferrer"; }
      item.append(citation);
    }
    const details = document.createElement("details");
    details.append(textElement("summary", "Offsets & evidence"), textElement("pre", JSON.stringify(finding, null, 2)));
    item.append(details);
    if (analysis?.tabId != null) {
      const jump = textElement("button", "Highlight this span", "text-button");
      jump.addEventListener("click", () => highlight([finding])); item.append(jump);
    }
    $("results").append(item);
  }
  $("clear-highlights").classList.toggle("hidden", !findings.size || analysis?.tabId == null);
}
async function highlight(items = [...findings.values()]) {
  if (!extension || analysis?.tabId == null || analysis.terminal_kind !== "analysis.completed") return;
  try {
    const response = await chrome.tabs.sendMessage(analysis.tabId, { type: "verity.highlight", document_id: analysis.document_id, revision: analysis.document_revision, findings: items });
    if (response?.error) status(response.error);
  } catch { status("The original tab is unavailable. Findings were not applied to another page."); }
}
async function streamEvents() {
  controller?.abort(); controller = new AbortController();
  const signal = controller.signal;
  const active = analysis;
  let delay = 250;
  while (analysis && !analysis.terminal && !signal.aborted) {
    try {
      const response = await api(`/analyses/${analysis.request_id}/events`, { signal, headers: { "Last-Event-ID": String(analysis.sequence || 0) } });
      await consumeSSE(response, async (name, event) => {
        if (signal.aborted || analysis !== active || !acceptEvent(active, event)) return;
        if (name.endsWith(".completed") && name !== "analysis.completed") {
          const key = name.split(".")[0]; statuses.set(key, event.payload);
          for (const finding of event.payload.findings || []) findings.set(`${key}:${finding.finding_id}`, finding);
        }
        if (name === "claim_verification.partial" && event.payload.finding) findings.set(`claim_verification:${event.payload.finding.finding_id}`, event.payload.finding);
        if (name === "analysis.started") status("Analyzing locally. CPU model calls may take time; you can cancel.");
        if (["analysis.completed", "analysis.error"].includes(name)) {
          analysis.terminal = true; $("cancel").classList.add("hidden"); $("analyze").disabled = false;
          analysis.terminal_kind = name;
          status(name === "analysis.error" ? `${event.payload.code}: ${event.payload.message}` : "Analysis complete. Findings are signals, not definitive judgments.");
        }
        render(); await saveState();
      }, signal);
      delay = 250;
    } catch (error) {
      if (signal.aborted) return;
      status(`Stream disconnected: ${error.message}. Reconnecting with saved sequence…`);
      if (/history|resubmit|sequence|cursor/i.test(error.message)) {
        analysis.terminal = true; $("analyze").disabled = false; $("cancel").classList.add("hidden"); await saveState(); return;
      }
      delay = Math.min(delay * 2, 5000);
    }
    if (analysis && !analysis.terminal) await new Promise(resolve => setTimeout(resolve, delay));
  }
  if (analysis === active && !signal.aborted) await highlight();
}
function manualExtraction(text) {
  return { document_id: manualId, revision: manualRevision, language: "en", offset_unit: "utf16_code_unit", extracted_text: text,
    blocks: [{ block_id: `${manualId}_block`, original_text: text, start_offset: 0, end_offset: text.length, text_revision: manualRevision, adapter_ref: { surface: "manual", locator: "paste" } }],
    extraction_metadata: { surface: "manual", scope: "manual", adapter_version: "1.0.0" } };
}
$("settings-toggle").addEventListener("click", () => $("settings").classList.toggle("hidden"));
$("save-settings").addEventListener("click", async () => {
  preferences = { auth: $("auth-token").value.trim(), csrf: $("csrf-token").value.trim(), excluded: $("excluded-domains").value.split(",").map(value => value.trim().toLowerCase()).filter(Boolean) };
  if (extension) await chrome.storage.local.set({ preferences });
  if (await connect()) $("settings").classList.add("hidden");
});
$("document-text").addEventListener("input", () => { invalidate(); manualRevision++; extraction = null; $("character-count").textContent = `${$("document-text").value.length.toLocaleString()} UTF-16 units`; });
$("read-page").addEventListener("click", async () => {
  invalidate();
  try {
    if (!extension) throw new Error("Load the unpacked Chrome extension to read a page");
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = new URL(tab.url);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("Chrome internal pages and file surfaces are not supported");
    if (preferences.excluded.some(domain => url.hostname === domain || url.hostname.endsWith("." + domain))) throw new Error("This domain is excluded. No content was extracted.");
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    const response = await chrome.tabs.sendMessage(tab.id, { type: "verity.extract" });
    if (response.error) throw new Error(response.error);
    extraction = response.extraction; tabId = tab.id;
    $("document-text").value = extraction.extracted_text; $("document-text").readOnly = true;
    $("surface-badge").textContent = extraction.extraction_metadata.surface.toUpperCase();
    $("surface-note").textContent = response.limitation; $("surface-note").classList.remove("hidden");
    $("manual-mode").classList.remove("hidden"); $("read-page").classList.add("hidden");
    $("character-count").textContent = `${extraction.extracted_text.length.toLocaleString()} UTF-16 units`;
    status("Surface extracted locally. Click Analyze to send it to the local backend.");
  } catch (error) { status(error.message); }
});
$("manual-mode").addEventListener("click", () => {
  invalidate();
  extraction = null; tabId = null; manualId = `document_${crypto.randomUUID()}`; manualRevision = 0;
  $("document-text").readOnly = false; $("surface-badge").textContent = "PASTED TEXT";
  $("surface-note").classList.add("hidden"); $("manual-mode").classList.add("hidden"); $("read-page").classList.remove("hidden");
});
$("analyze").addEventListener("click", async () => {
  if ($("analyze").disabled) return;
  $("analyze").disabled = true;
  const submittedGeneration = generation;
  try {
    const text = $("document-text").value;
    if (!text.trim()) throw new Error("Add some text first");
    if (text.length > 20_000) throw new Error("This profile is limited to 20,000 UTF-16 units in the extension");
    if (!extraction) extraction = manualExtraction(text);
    else if (extraction.extraction_metadata.surface === "manual") extraction = manualExtraction(text);
    const engines = [["engine-ai", "ai_detection"], ["engine-copy", "plagiarism"], ["engine-claims", "claim_verification"]].filter(([id]) => $(id).checked).map(([,name]) => name);
    if (!engines.length) throw new Error("Select at least one engine");
    controller?.abort(); findings.clear(); statuses.clear(); render();
    const created = await (await api("/analyses/text", { method: "POST", body: JSON.stringify({ extraction, engines, external_search_consent: $("external-consent").checked }) })).json();
    if (generation !== submittedGeneration) {
      api(`/analyses/${created.request_id}/cancel`, { method: "POST", body: "{}" }).catch(() => {});
      return;
    }
    analysis = { ...created, tabId, sequence: 0, terminal: false };
    await saveState(); $("analyze").disabled = true; $("cancel").classList.remove("hidden");
    await streamEvents();
  } catch (error) { if (generation === submittedGeneration) { $("analyze").disabled = false; status(error.message); } }
});
$("cancel").addEventListener("click", async () => {
  if (!analysis) return;
  try { await api(`/analyses/${analysis.request_id}/cancel`, { method: "POST", body: "{}" }); } catch (error) { status(error.message); }
});
$("clear-highlights").addEventListener("click", () => { if (extension && analysis?.tabId != null) chrome.tabs.sendMessage(analysis.tabId, { type: "verity.clear" }).catch(() => {}); });
$("source-toggle").addEventListener("click", () => $("source-form").classList.toggle("hidden"));
async function refreshSources() {
  const data = await (await api("/sources")).json();
  $("source-count").textContent = `${data.sources.length} reference source${data.sources.length === 1 ? "" : "s"} · stored on this device`;
  $("source-list").replaceChildren();
  for (const source of data.sources) {
    const item = document.createElement("li"); item.append(textElement("span", `${source.title} · ${source.characters.toLocaleString()} chars`));
    const remove = textElement("button", "Remove", "text-button");
    remove.addEventListener("click", async () => { try { await api(`/sources/${source.source_id}/remove`, { method: "POST", body: "{}" }); await refreshSources(); } catch (error) { status(error.message); } });
    item.append(remove); $("source-list").append(item);
  }
}
$("add-source").addEventListener("click", async () => {
  try {
    await api("/sources", { method: "POST", body: JSON.stringify({ source_id: `source_${crypto.randomUUID()}`, title: $("source-title").value, text: $("source-text").value, url: $("source-url").value || null, reliability: $("source-trusted").checked ? "user_trusted" : "unrated" }) });
    $("source-title").value = ""; $("source-text").value = ""; $("source-url").value = ""; $("source-trusted").checked = false;
    $("source-form").classList.add("hidden"); await refreshSources(); status("Reference source stored locally.");
  } catch (error) { status(error.message); }
});
async function initialize() {
  $("pair-command").textContent = extension ? `python -m backend.scripts.pair_extension ${chrome.runtime.id}` : "Browser preview. Load extension_mv3/dist in Chrome to connect.";
  if (!extension) return;
  const stored = await chrome.storage.local.get(["preferences", "analysisState"]);
  if (stored.preferences) preferences = stored.preferences;
  $("auth-token").value = preferences.auth; $("csrf-token").value = preferences.csrf; $("excluded-domains").value = preferences.excluded.join(", ");
  if (!preferences.auth) $("settings").classList.remove("hidden");
  if (preferences.auth && await connect() && stored.analysisState) {
    analysis = { ...stored.analysisState, sequence: 0, terminal: false }; // Rebuild UI from persisted history, not an empty UI with a nonzero cursor.
    $("cancel").classList.remove("hidden"); $("analyze").disabled = true;
    streamEvents();
  }
  chrome.storage.onChanged.addListener(async (changes, area) => {
    if (area !== "local" || analysis?.tabId == null) return;
    const current = changes[`revision:${analysis.tabId}`]?.newValue;
    if (current?.document_id === analysis.document_id && current.revision > analysis.document_revision) {
      invalidate(); extraction = null; tabId = null; $("document-text").value = ""; $("document-text").readOnly = false;
      $("manual-mode").classList.add("hidden"); $("read-page").classList.remove("hidden");
      $("surface-badge").textContent = "PASTED TEXT"; $("surface-note").classList.add("hidden");
      $("character-count").textContent = "0 UTF-16 units";
      status("Page changed. Old findings were cleared; extract the new surface before analyzing."); await saveState();
    }
  });
}
initialize();
