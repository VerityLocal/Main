# Browser test plan, not implemented integrations

This is the historical acceptance plan. Executable JS unit and installed-Chrome
fixture checks now live under `extension_mv3/tests`; see `docs/compatibility.md`.
They do not establish full real-editor or MV3 lifecycle compatibility.

Phase 5 must add representative static/dynamic articles, long/non-BMP text,
textareas/inputs, each editor fixture, scrolling/resizing/zoom, rerendering,
accessible shadow roots/frames and stale-result tests. Assert no original DOM
text or input values changed. Google Docs remains disabled until an isolated
method passes corresponding compatibility tests. No browser results are
claimed by the Python foundation tests.
