import { StaticDomAdapter } from "../static_dom/index.js";
export class SlateAdapter extends StaticDomAdapter {
  constructor(root) { super(root, "slate"); }
  detect() { return this.root?.matches("[data-slate-editor='true']") && super.detect(); }
}
