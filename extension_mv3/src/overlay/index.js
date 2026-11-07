export class Highlighter {
  constructor(adapter) { this.adapter = adapter; this.findings = []; this.raf = 0; this.paintBound = () => this.schedule(); }
  apply(findings) {
    this.clear();
    this.findings = findings;
    const document = this.adapter.root.ownerDocument, window = document.defaultView;
    this.custom = !!(window.CSS?.highlights && window.Highlight && this.adapter.ranges);
    if (this.custom) {
      const groups = new Map();
      for (const finding of findings) {
        const name = this.name(finding);
        if (!groups.has(name)) groups.set(name, []);
        try { groups.get(name).push(...this.adapter.ranges(finding.start_offset, finding.end_offset)); } catch { /* Stale/invalid spans are ignored, never guessed. */ }
      }
      for (const [name, ranges] of groups) window.CSS.highlights.set(name, new window.Highlight(...ranges));
      this.style = document.createElement("style");
      this.style.setAttribute("data-local-ai-root", "highlight-style");
      this.style.textContent = "::highlight(verity-copy){background:#fbbf2466}::highlight(verity-ai){background:#a78bfa66}::highlight(verity-claim){background:#38bdf866}";
      document.documentElement.append(this.style);
    } else {
      this.host = document.createElement("div");
      this.host.setAttribute("data-local-ai-root", "overlay");
      this.host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483646";
      this.shadow = this.host.attachShadow({ mode: "closed" });
      document.documentElement.append(this.host);
      window.addEventListener("scroll", this.paintBound, true);
      window.addEventListener("resize", this.paintBound);
      this.resize = new window.ResizeObserver(this.paintBound);
      this.resize.observe(this.adapter.root);
      this.schedule();
    }
  }
  name(finding) { return finding.category === "AI_GENERATED_CANDIDATE" ? "verity-ai" : ["EXACT_OVERLAP", "REORDERED_TEXT", "SEMANTIC_PARAPHRASE"].includes(finding.category) ? "verity-copy" : "verity-claim"; }
  schedule() {
    const window = this.adapter.root.ownerDocument.defaultView;
    if (!this.raf) this.raf = window.requestAnimationFrame(() => { this.raf = 0; this.paint(); });
  }
  paint() {
    if (!this.host || !this.adapter.root.isConnected) return;
    if (!this.host.isConnected) this.adapter.root.ownerDocument.documentElement.append(this.host);
    this.shadow.replaceChildren();
    const document = this.adapter.root.ownerDocument;
    for (const finding of this.findings) {
      let rectangles = [];
      try { rectangles = this.adapter.mapOffsetsToRects(finding.start_offset, finding.end_offset); } catch { continue; }
      for (const rect of rectangles) {
        const left = Math.max(0, rect.left), top = Math.max(0, rect.top), right = Math.min(document.defaultView.innerWidth, rect.right), bottom = Math.min(document.defaultView.innerHeight, rect.bottom);
        if (right <= left || bottom <= top) continue;
        const mark = document.createElement("div");
        const color = this.name(finding) === "verity-copy" ? "#fbbf24" : this.name(finding) === "verity-ai" ? "#a78bfa" : "#38bdf8";
        mark.style.cssText = `position:fixed;left:${left}px;top:${top}px;width:${right-left}px;height:${bottom-top}px;background:${color}33;border-bottom:2px solid ${color};box-sizing:border-box;`;
        this.shadow.append(mark);
      }
    }
  }
  clear() {
    const window = this.adapter.root.ownerDocument.defaultView;
    if (this.raf) window.cancelAnimationFrame(this.raf);
    this.raf = 0;
    for (const name of ["verity-copy", "verity-ai", "verity-claim"]) window.CSS?.highlights?.delete(name);
    this.style?.remove(); this.host?.remove(); this.resize?.disconnect();
    window.removeEventListener("scroll", this.paintBound, true); window.removeEventListener("resize", this.paintBound);
    this.findings = [];
  }
  destroy() { this.clear(); }
}
