# Browser compatibility and risk matrix

Actual automated checks use installed Chrome on Windows; the exact version and
passed cases are recorded in `artifacts/browser_validation.json`. These are
**fixture tests**, not universal website/editor certification.

| Surface / risk | Implemented method | Tested / limitation |
|---|---|---|
| Static article | TreeWalker, original text-node offsets, CSS Custom Highlights | Inline/BR/emoji/combining marks, exclusions, geometry and unchanged DOM fixtures |
| Mutations / revisions | MutationObserver, input events, document identity, stale-result rejection | DOM/input mutation and stale-highlight fixtures; exhaustive SPA lifecycle unverified |
| Open shadow roots | Recursive rendered extraction and DOM ranges | Open-root extraction fixture; slot/closed-root completeness unsupported |
| Textarea / text input | Actual value, styled closed-shadow mirror, clipped overlay | Wrapping/scroll/selection/emoji fixture; exhaustive RTL, tabs, zoom, transforms unverified |
| Passwords | Excluded | Unit tests reject extraction |
| ProseMirror / Lexical / Quill / Slate | Separate surface classes reading rendered DOM | Editor-shaped fixtures only; not framework state-to-DOM integrations |
| Overlay fallback | External closed-shadow overlay, resize/scroll repaint | Text-control fixture; complex stacking/overlapping host pages unverified |
| Google Docs | Explicit refusal | Canvas/document-model integration disabled; use pasted text |
| Iframes / closed roots / virtualized text | None | Not extracted; no full-document assertion |
| MV3 lifecycle | Side panel fetch SSE; persistent request/cursor; replay from zero on reopen | SSE parsing/unit tests and synthetic panel transport; actual extension install/worker termination still a manual acceptance gate |

The manifest uses `activeTab`, `scripting`, `storage`, `sidePanel`, and only
`http://127.0.0.1:8787/*` as a host permission. It requests no `<all_urls>` access.
Injection uses the default isolated world; no private editor globals or MAIN-world
bridge are implemented. Pasted mode does not touch page content.
