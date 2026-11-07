import { chooseAdapter } from "../adapters/index.js";
import { Highlighter } from "../overlay/index.js";

if (!globalThis.__verityLocalInstalled) {
  globalThis.__verityLocalInstalled = true;
  const documentId = `document_${crypto.randomUUID()}`;
  let revision = 0, adapter = null, highlighter = null, snapshot = null, focusedControl = null;
  document.addEventListener("focusin", event => { if (event.target.matches("textarea,input")) focusedControl = event.target; }, true);
  function changed() {
    revision++;
    highlighter?.clear();
    snapshot = null;
    chrome.runtime.sendMessage({ type: "verity.document.changed", document_id: documentId, revision }).catch(() => {});
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return;
    try {
      if (message.type === "verity.extract") {
        const selected = chooseAdapter(document, focusedControl);
        if (!adapter?.root.isConnected || selected.root !== adapter.root) {
          highlighter?.destroy(); adapter?.destroy();
          if (adapter) revision++;
          adapter = selected;
          highlighter = new Highlighter(adapter);
          adapter.subscribeToChanges(changed);
        }
        const extracted = adapter.extractText();
        if (!extracted.extracted_text.trim()) throw new Error("No analyzable text was found");
        if (extracted.extracted_text.length > 20_000) throw new Error("Surface exceeds the current 20,000-character profile. Paste a shorter selection instead.");
        snapshot = { document_id: documentId, revision, language: document.documentElement.lang || "und",
          blocks: extracted.blocks.map(block => ({ ...block, text_revision: revision })), extracted_text: extracted.extracted_text,
          offset_unit: "utf16_code_unit", extraction_metadata: { surface: adapter.surface, scope: "rendered_content", adapter_version: "rendered_v1", source_url: location.origin + location.pathname } };
        respond({ extraction: snapshot, limitation: "Only the rendered surface is inspected; virtualized text and frames are not included." });
      } else if (message.type === "verity.highlight") {
        if (!snapshot || message.document_id !== documentId || message.revision !== revision) throw new Error("Stale findings were rejected");
        const current = adapter.extractText().extracted_text;
        if (current !== snapshot.extracted_text) { changed(); throw new Error("Document text changed; analyze the new revision"); }
        highlighter.apply(message.findings);
        respond({ applied: true });
      } else if (message.type === "verity.clear") { highlighter?.clear(); respond({ cleared: true }); }
    } catch (error) { respond({ error: error.message }); }
    return false;
  });
  let pageURL = location.href;
  const navigation = new MutationObserver(() => {
    if (pageURL !== location.href || (adapter && !adapter.root.isConnected)) {
      pageURL = location.href;
      changed();
      if (adapter && !adapter.root.isConnected) { highlighter?.destroy(); adapter.destroy(); adapter = null; }
    }
  });
  navigation.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("popstate", changed);
  window.addEventListener("hashchange", changed);
}
