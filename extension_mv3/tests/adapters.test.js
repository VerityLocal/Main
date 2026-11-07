import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { StaticDomAdapter } from "../src/adapters/static_dom/index.js";
import { TextControlAdapter } from "../src/adapters/textarea/index.js";
import { chooseAdapter } from "../src/adapters/index.js";
import { checkedSpan } from "../src/coordinates/index.js";
import { isGoogleDocs } from "../src/adapters/google_docs/index.js";

const dom = html => new JSDOM(html, { url: "https://fixture.example/article" });
test("static DOM preserves UTF-16, inline order, BR, stable IDs and exclusions", () => {
  const { window } = dom('<article><div>Before<p>😀 Café <b>bold</b><br>next</p>After</div><nav>navigation</nav><p hidden>hidden</p><textarea>control</textarea></article>');
  const adapter = new StaticDomAdapter(window.document.querySelector("article"));
  const first = adapter.extractText();
  assert.equal(first.extracted_text, "Before\n\n😀 Café bold\nnext\n\nAfter");
  assert.equal(new Set(first.blocks.map(b => b.block_id)).size, first.blocks.length);
  assert.deepEqual(adapter.extractText().blocks.map(b => b.block_id), first.blocks.map(b => b.block_id));
  const start = first.extracted_text.indexOf("Café"), end = first.extracted_text.indexOf("\nnext");
  assert.equal(adapter.ranges(start, end).map(r => r.toString()).join(""), "Café bold");
  let cursor = 0;
  for (const block of first.blocks) {
    assert.equal(block.start_offset, cursor);
    assert.equal(first.extracted_text.slice(block.start_offset, block.end_offset), block.original_text);
    cursor = block.end_offset + 2;
  }
});
test("mutation subscription invalidates text but ignores extension-owned roots", async () => {
  const { window } = dom("<article><p>Text</p></article>");
  const root = window.document.querySelector("article"), adapter = new StaticDomAdapter(root);
  let changes = 0;
  adapter.subscribeToChanges(() => changes++);
  const overlay = window.document.createElement("div"); overlay.setAttribute("data-local-ai-root", "overlay");
  root.append(overlay);
  await Promise.resolve();
  assert.equal(changes, 0);
  root.querySelector("p").firstChild.data = "New text";
  await Promise.resolve();
  assert.equal(changes, 1);
  adapter.destroy();
});
test("text controls use values, never password text", () => {
  const { window } = dom('<textarea>original</textarea><input type="password" value="private">');
  const textarea = window.document.querySelector("textarea"); textarea.value = "😀 edited";
  assert.equal(new TextControlAdapter(textarea).extractText().extracted_text, "😀 edited");
  const password = new TextControlAdapter(window.document.querySelector("input"));
  assert.equal(password.detect(), false);
  assert.throws(() => password.extractText(), /private/);
});
test("editor-shaped adapters and explicit Google Docs refusal", () => {
  for (const [markup, surface] of [['class="ProseMirror"', "prosemirror"], ['data-lexical-editor="true"', "lexical"], ['class="ql-editor"', "quill"], ['data-slate-editor="true"', "slate"]]) {
    const { window } = dom(`<div ${markup} contenteditable="true"><p>Editor text</p></div>`);
    assert.equal(chooseAdapter(window.document).surface, surface);
  }
  assert.equal(isGoogleDocs("https://docs.google.com/document/d/id/edit"), true);
  assert.equal(isGoogleDocs("https://docs.google.com.evil.example/document/"), false);
  const document = new JSDOM("<p>Canvas</p>", { url: "https://docs.google.com/document/d/id/edit" }).window.document;
  assert.throws(() => chooseAdapter(document), /disabled/);
});
test("half-open span validation rejects split emoji and invalid ranges", () => {
  checkedSpan("a😀b", 1, 3);
  assert.throws(() => checkedSpan("a😀b", 1, 2), /surrogate/);
  assert.throws(() => checkedSpan("abc", 2, 1), /Invalid/);
});
