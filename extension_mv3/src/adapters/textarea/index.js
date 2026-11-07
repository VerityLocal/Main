import { checkedSpan } from "../../coordinates/index.js";

const STYLES = ["fontFamily", "fontSize", "fontWeight", "fontStyle", "lineHeight", "letterSpacing", "wordSpacing", "textIndent", "textTransform", "tabSize", "direction", "writingMode", "paddingTop", "paddingBottom", "paddingLeft", "paddingRight", "borderTopWidth", "borderBottomWidth", "borderLeftWidth", "borderRightWidth", "boxSizing", "width", "height"];

export class TextControlAdapter {
  constructor(element) { this.root = element; this.surface = "textarea"; this.blockId = `block_${crypto.randomUUID()}`; }
  detect() { return this.root?.matches("textarea,input[type=text],input[type=search],input[type=url],input[type=email],input[type=tel],input:not([type])") && this.root.type !== "password"; }
  extractText() {
    if (!this.detect()) throw new Error("Unsupported or private input control");
    const text = this.root.value;
    this.snapshot = { extracted_text: text, blocks: text.length ? [{ block_id: this.blockId, original_text: text, start_offset: 0, end_offset: text.length, adapter_ref: { surface: "textarea", locator: this.blockId } }] : [] };
    return this.snapshot;
  }
  mapOffsetsToRects(start, end) {
    checkedSpan(this.snapshot.extracted_text, start, end);
    if (this.root.value !== this.snapshot.extracted_text) return [];
    const document = this.root.ownerDocument;
    const style = document.defaultView.getComputedStyle(this.root), bounds = this.root.getBoundingClientRect();
    if (!this.host) {
      this.host = document.createElement("div");
      this.host.setAttribute("data-local-ai-root", "mirror");
      this.host.style.cssText = "position:fixed;top:0;left:0;width:0;height:0;pointer-events:none;z-index:-1";
      this.shadow = this.host.attachShadow({ mode: "closed" });
      document.documentElement.append(this.host);
    }
    this.shadow.replaceChildren();
    const mirror = document.createElement("div");
    for (const key of STYLES) mirror.style[key] = style[key];
    mirror.style.cssText += `;position:fixed;left:${bounds.left}px;top:${bounds.top}px;margin:0;white-space:${this.root.tagName === "TEXTAREA" ? "pre-wrap" : "pre"};overflow:hidden;overflow-wrap:break-word;border-style:solid;border-color:transparent;color:transparent;`;
    mirror.style.width = `${this.root.clientWidth + parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth)}px`;
    mirror.append(document.createTextNode(this.snapshot.extracted_text.slice(0, start)));
    const selected = document.createElement("span");
    selected.textContent = this.snapshot.extracted_text.slice(start, end);
    mirror.append(selected, document.createTextNode(this.snapshot.extracted_text.slice(end) || "\u200b"));
    this.shadow.append(mirror);
    mirror.scrollTop = this.root.scrollTop;
    mirror.scrollLeft = this.root.scrollLeft;
    const range = document.createRange();
    range.selectNodeContents(selected);
    return [...range.getClientRects()].map(rect => ({ left: Math.max(rect.left, bounds.left), top: Math.max(rect.top, bounds.top), right: Math.min(rect.right, bounds.right), bottom: Math.min(rect.bottom, bounds.bottom) })).filter(rect => rect.right > rect.left && rect.bottom > rect.top);
  }
  subscribeToChanges(callback) {
    this.onInput = callback;
    this.root.addEventListener("input", callback);
    return () => this.root.removeEventListener("input", callback);
  }
  destroy() { if (this.onInput) this.root.removeEventListener("input", this.onInput); this.host?.remove(); }
}
