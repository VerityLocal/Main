import { StaticDomAdapter } from "../static_dom/index.js";
export class QuillAdapter extends StaticDomAdapter {
  constructor(root) { super(root, "quill"); }
  detect() { return this.root?.matches(".ql-editor") && super.detect(); }
}
