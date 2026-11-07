import { StaticDomAdapter } from "../static_dom/index.js";
export class LexicalAdapter extends StaticDomAdapter {
  constructor(root) { super(root, "lexical"); }
  detect() { return this.root?.matches("[data-lexical-editor='true']") && super.detect(); }
}
