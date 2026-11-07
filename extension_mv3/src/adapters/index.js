import { StaticDomAdapter } from "./static_dom/index.js";
import { TextControlAdapter } from "./textarea/index.js";
import { ProseMirrorAdapter } from "./prosemirror/index.js";
import { LexicalAdapter } from "./lexical/index.js";
import { QuillAdapter } from "./quill/index.js";
import { SlateAdapter } from "./slate/index.js";
import { isGoogleDocs, GOOGLE_DOCS_MESSAGE } from "./google_docs/index.js";

export function chooseAdapter(document, selectedControl) {
  if (isGoogleDocs(document.location.href)) throw new Error(GOOGLE_DOCS_MESSAGE);
  const control = selectedControl || document.activeElement;
  const text = new TextControlAdapter(control);
  if (text.detect()) return text;
  if (control?.matches("input[type=password]")) throw new Error("Password fields are never analyzed");
  for (const [selector, Adapter] of [[".ProseMirror", ProseMirrorAdapter], ["[data-lexical-editor='true']", LexicalAdapter], [".ql-editor", QuillAdapter], ["[data-slate-editor='true']", SlateAdapter]]) {
    const root = control?.closest(selector) || document.querySelector(selector);
    if (root) return new Adapter(root);
  }
  return new StaticDomAdapter(document.querySelector("article") || document.querySelector("main") || document.body);
}
