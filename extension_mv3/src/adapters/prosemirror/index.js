import { StaticDomAdapter } from "../static_dom/index.js";
export class ProseMirrorAdapter extends StaticDomAdapter {
  constructor(root) { super(root, "prosemirror"); }
  detect() { return this.root?.matches(".ProseMirror") && super.detect(); }
}
