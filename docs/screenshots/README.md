# Verity Local screenshots

These are actual Chrome extension captures using the included synthetic `docs/examples/verity-local-demo.pdf`, both real local detectors, and the default 0.5 threshold. The demonstration has no authorship labels; the displayed percentages are interface examples, not accuracy measurements.

- `install-extension.webp`: Chrome's extensions page with Developer mode and the Verity Local card.
- `settings.webp`: a successful loopback connection; the bearer token stays masked.
- `popup.webp`: actual toolbar popup after manual PDF selection and local analysis.
- `review-overview.webp`: the same result opened in the detailed review tab.
- `evidence.webp`: an analyzed passage highlighted at its original PDF location.
- `capture.json`: document hash, capture dimensions, and observed result summaries.

Reproduce with `node scripts/capture_screenshots.mjs` after launching an isolated visible Chrome for Testing profile on loopback DevTools port 9223, loading `extension/`, and starting the backend on port 8000 with that profile's extension ID. See the capture script's header. No website permissions or local-file-access overrides are needed; the PDF is explicitly selected through the file input.
