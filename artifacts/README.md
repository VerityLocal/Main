# Local artifacts

Hardware snapshots, benchmark observations, training/calibration artifacts and
model weights belong here or in private storage. Most files are git-ignored.
Phase 0 records actual checks in `phase0_validation.md` after execution.
Current checks are in `implementation_validation.md`; `browser_validation.json`
records installed-Chrome fixture results and `extension_panel.png` previews the UI.
`cpu_fixture_benchmark.json` is a labeled synthetic timing observation, not accuracy.
`model_setup_validation_2026-11-05.md` and `model_setup_smoke_2026-11-05.json`
record subsequent local smoke checks after four pinned models were installed.
`cuda_training_validation_2026-11-05.md` and `cuda_training_smoke_2026-11-05.json`
record the installed CUDA environment and real pinned-backbone gradient checks
on synthetic inputs, including measured VRAM and FP32 CPU merge parity.
`llmtrace_import_validation_2026-11-05.md` records the verified public-data import,
span-label conversion, exact/near-duplicate grouping and selected pilot splits.
`feature_extraction_optimization_2026-11-05.json` records equal feature/mask/offset
outputs on 32 pilot documents before and after removing repeated tokenizer
vocabulary-size checks, with one warm timing observation per implementation.
`llmtrace_training_interruption_2026-11-05.md` records the first attempt's CUDA
failure, preserved partial output and the conditions of its fresh retry.
`llmtrace_pilot_validation_2026-11-05.md` records the completed three-epoch CUDA
retry, validation-selected epoch, fitted temperatures, genuine held-out metrics,
strata, limitations, file hashes and live deployment handoff.
`detector-deployment-2026-11-05.json` records passing authenticated HTTP/SSE checks
against the configured calibrated checkpoint, including original UTF-16 spans,
stale-revision rejection and exact 512/513-token input-profile behavior.
Hardware snapshots contain machine details but no user documents or secrets.
Do not publish private datasets or claim training results that do not exist.
