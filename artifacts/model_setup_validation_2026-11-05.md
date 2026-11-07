# Local model setup validation — 2026-11-05

The running backend reported the pinned BGE, STSB, NLI and MS MARCO snapshots
available on CPU. No AI detector checkpoint is configured, and the dataset
registry remains empty. Earlier reports describe the original, model-disabled
baseline; this report records the subsequent local setup.

## Screenshot regression fix

The setup example appeared as both exact overlap and semantic paraphrase.
Lexical alignment excludes terminal punctuation, while semantic passage spans
include it. The old containment check therefore missed the existing exact match.

The similarity engine now checks coverage of the query's lexical tokens and
the corresponding source passage before STS verification. This avoids redundant
verification and duplicate classifications. Partial lexical overlap and different
passages within the same source remain eligible semantic candidates.

Four regression cases cover ordinary punctuation, non-BMP/Unicode text, partial
matches and distinct source passages. Focused validation:

```powershell
.\.venv\Scripts\pytest.exe -q tests/unit/test_engines.py tests/integration/test_analysis_runtime.py
```

Observed: **29 passed, 1 warning in 7.81 seconds**. The warning is the existing
Starlette/AnyIO `BlockingPortal` deprecation. Changed-file lint and formatting
checks passed. The broader suite was not rerun for this focused change.

## Actual pinned-model smoke checks

[Raw observations](model_setup_smoke_2026-11-05.json) were recorded using local
model files in a separate CPU process with synthetic, nonprivate examples and
one serialized model manager. The check made no required network requests and
unloaded its model on completion.

- BGE retrieval plus the revised exact-copy pipeline returned one `EXACT_OVERLAP`
  and skipped its already-aligned semantic candidate.
- STSB returned finite sigmoid-scale similarity values for identical text and a
  paraphrase candidate.
- NLI returned finite, normalized entailment/contradiction/neutral distributions
  for a repeated statement and an opposing statement.
- MS MARCO returned a finite raw relevance logit for a question/evidence pair.

These checks demonstrate execution on a handful of inputs. They are not a
dataset accuracy evaluation, threshold calibration, performance benchmark,
generalization guarantee or GPU-fit measurement.

## Apply and continue

The existing backend process still has its previously imported code. Restart
it and submit a new analysis to apply the duplicate fix; replayed earlier
analyses retain their original findings. No extension rebuild is needed.

The remaining AI-writing step requires licensed human/AI labeled documents and
sentence annotations, leakage-separated splits, training and separate calibration.
No labels were fabricated and no detector training was started.
