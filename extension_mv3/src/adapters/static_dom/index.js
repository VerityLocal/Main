import { checkedSpan, rangeForSegments } from "../../coordinates/index.js";

const EXCLUDE = "script,style,noscript,nav,footer,aside,button,textarea,input,select,[hidden],[aria-hidden='true'],[data-local-ai-root]";
const BLOCK = "p,li,h1,h2,h3,h4,h5,h6,blockquote,pre,td,div";

export class StaticDomAdapter {
  constructor(root, surface = "static_dom") {
    this.root = root;
    this.surface = surface;
    this.ids = new WeakMap();
    this.snapshot = null;
    this.observer = null;
  }
  detect() { return !!this.root?.isConnected; }
  visible(element) {
    if (!element || element.closest(EXCLUDE)) return false;
    for (let parent = element; parent; parent = parent.parentElement) {
      const style = parent.ownerDocument.defaultView.getComputedStyle(parent);
      if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse" || style.opacity === "0") return false;
    }
    return true;
  }
  extractText() {
    const document = this.root.ownerDocument;
    const grouped = [];
    const visited = new Set();
    const append = (owner, node, text) => {
      if (grouped.at(-1)?.owner !== owner) grouped.push({ owner, nodes: [] });
      grouped.at(-1).nodes.push({ node, text });
    };
    const visit = root => {
      const walker = document.createTreeWalker(root, document.defaultView.NodeFilter.SHOW_ELEMENT | document.defaultView.NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if (node.nodeType === 1) {
          if (node.shadowRoot && this.visible(node)) visit(node.shadowRoot);
          if (node.tagName === "BR" && this.visible(node)) append(node.parentElement.closest(BLOCK) || this.root, null, "\n");
          continue;
        }
        const parent = node.parentElement || node.getRootNode().host;
        if (visited.has(node) || !this.visible(parent)) continue;
        visited.add(node);
        const owner = parent.closest(BLOCK) || this.root;
        append(owner, node, node.data);
      }
    };
    visit(this.root);
    const blocks = [], segments = [];
    const runs = new Map();
    let start = 0;
    for (const { owner, nodes } of grouped) {
      const text = nodes.map(item => item.text).join("");
      if (!text.trim()) continue;
      if (!this.ids.has(owner)) this.ids.set(owner, `block_${crypto.randomUUID()}`);
      let cursor = start;
      for (const item of nodes) {
        segments.push({ node: item.node, start: cursor, end: cursor + item.text.length });
        cursor += item.text.length;
      }
      const run = runs.get(owner) || 0; runs.set(owner, run + 1);
      const id = `${this.ids.get(owner)}_run_${run}`;
      blocks.push({ block_id: id, original_text: text, start_offset: start, end_offset: start + text.length,
        adapter_ref: { surface: this.surface, locator: id } });
      start += text.length + 2;
    }
    this.snapshot = { blocks, extracted_text: blocks.map(block => block.original_text).join("\n\n"), segments };
    return this.snapshot;
  }
  ranges(start, end) {
    checkedSpan(this.snapshot.extracted_text, start, end);
    return rangeForSegments(this.snapshot.segments, start, end);
  }
  mapOffsetsToRects(start, end) {
    return this.ranges(start, end).flatMap(range => [...range.getClientRects()]);
  }
  subscribeToChanges(callback) {
    this.observer = new this.root.ownerDocument.defaultView.MutationObserver(records => {
      const meaningful = records.some(record => {
        if (record.target.parentElement?.closest("[data-local-ai-root]")) return false;
        if (record.type === "childList" && [...record.addedNodes, ...record.removedNodes].length && [...record.addedNodes, ...record.removedNodes].every(node => node.nodeType === 1 && node.hasAttribute("data-local-ai-root"))) return false;
        return true;
      });
      if (meaningful) callback();
    });
    this.observer.observe(this.root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["class", "style", "hidden", "aria-hidden"] });
    for (const element of this.root.querySelectorAll("*")) {
      if (element.shadowRoot) this.observer.observe(element.shadowRoot, { subtree: true, childList: true, characterData: true });
    }
    return () => this.observer?.disconnect();
  }
  destroy() { this.observer?.disconnect(); this.snapshot = null; }
}
