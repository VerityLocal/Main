# Phase 0 implementation and validation report

Date: 2026-11-04. This report covers the executable **foundation**, not trained
engines, browser integrations, or production-readiness certification.

## Files created

- Root: `README.md`, `pyproject.toml`, generated `uv.lock`, `.gitignore`,
  `.env.example`. Setup also created a git-ignored `.env` with independent
  random secrets, `.venv/`, and an isolated `.tooling/` uv installation.
- `configs/`: hardware, model, stylometry, retrieval, and evaluation YAML.
- `backend/app/core/`: validated configuration, safe logging, ASGI security,
  hardware snapshot contracts and GPU allocation guard.
- `backend/app/document/`: canonical builder, UTF-16 index, normalization map.
- `backend/app/schemas/`: document, finding, event and API response contracts.
- `backend/app/services/document_manager.py`: bounded TTL revision registry.
- `backend/app/api/v1/routes.py` and `backend/app/main.py`: secured API and CLI.
- `backend/app/runtime/profiling.py`: CPU/RAM, driver and optional torch probes.
- `backend/scripts/`: secret initialization, schema export/check, manual
  UTF-8 document construction. Package `__init__.py` files were also created.
- `backend/datasets/`: empty registry and dataset requirements; no private data.
- `shared/schemas/`: three generated JSON Schema artifacts;
  `shared/contracts/README.md`: semantic cross-language validation requirements.
- `tests/`: unit, API/security, real loopback/CLI, capacity/concurrency checks;
  `tests/browser/README.md` documents the future browser acceptance fixtures.
- `docs/`: architecture/dataflow/interfaces, complete target tree, contracts,
  coordinates, exactly 24 feature definitions, tensor shapes, resource budget,
  security, evaluation, model candidates, compatibility matrix and decisions.
- `artifacts/`: artifact policy, this report, and git-ignored `hardware.json`.

Future-phase paths in the target tree were not generated as empty core stubs.

## Implemented behavior

Strict documents preserve original text, block IDs, revisions, adapter references,
UTF-16 half-open ranges and conservative normalization provenance. Input arrays
are frozen without coercing scalar types. Unpaired surrogates, invalid maps,
wrong block positions and stale registered revisions are rejected.

The API authenticates every request, requires a separate CSRF secret for POST,
validates exact Host/Origin, handles trusted preflight, caps advertised and actual
streaming bodies, and applies read/execution deadlines and rate/concurrency
limits. Ordinary logs and safe errors do not include private document text.
There are two real endpoints: health and document registration, not inference.

Hardware profiling records actual machine data without model downloads. The
GPU guard distinguishes current allocation, reservation, historical peaks and
driver usage, and fails closed when allocator measurements are unavailable.
It is a measured post-check, not a tensor-allocator cap or proof of model fit.

## Commands executed and actual results

Working directory: `local-ai-analysis-platform/`.

| Command | Actual result |
|---|---|
| `python -m venv .tooling` | Isolated tooling environment created |
| `.tooling\Scripts\python.exe -m pip install uv==0.6.17` | uv installed |
| `.tooling\Scripts\uv.exe lock` | 32 packages resolved; real lock generated |
| `.tooling\Scripts\uv.exe sync --frozen --group dev` | Isolated project environment installed |
| `.venv\Scripts\python.exe -m backend.scripts.export_schemas` | Three schemas exported |
| `.tooling\Scripts\uv.exe run --frozen pytest` | **138 passed, 1 warning, 2.80 seconds** |
| `.venv\Scripts\ruff.exe check .` | All checks passed |
| `.venv\Scripts\ruff.exe format --check .` | 41 Python files already formatted |
| `.venv\Scripts\python.exe -m backend.scripts.export_schemas --check` | All three match source definitions |
| `.venv\Scripts\local-ai-init.exe` | Private `.env` created; existing files are not overwritten |
| `.venv\Scripts\python.exe -m backend.app.runtime.profiling --output artifacts/hardware.json` | Real snapshot written |

The warning is a Starlette TestClient / AnyIO `BlockingPortal` deprecated alias.
It was not hidden; it did not fail these tests. Dependencies remain frozen;
a deliberate compatibility update is preferable to suppressing warnings.

The real TCP test launches the actual loopback CLI in an owned subprocess on
an available local port, checks unauthenticated 401, authenticated health 200,
Unicode document registration 200, and stale revision 409, then stops only its
own process. No browser tests or inference benchmarks were executed.
The suite duration is a test-run observation, **not inference latency**.

## Observed hardware (snapshot, not a benchmark)

From `artifacts/hardware.json`, timestamp `2026-11-04T16:08:29.469457Z`:

- Python 3.11.9; Windows platform reported `Windows-10-10.0.26200-SP0`.
- CPU: 11th Gen Intel Core i5-11400H @ 2.70GHz; 6 physical / 12 logical CPUs.
- System RAM total: 16,952,647,680 bytes; available: 5,336,133,632 bytes.
- NVIDIA GeForce RTX 3050 Laptop GPU; driver `621.01`.
- Driver-reported VRAM total: 4,294,967,296 bytes (**4 GiB**);
  free: 3,969,908,736 bytes; used: 185,597,952 bytes.
- Profiler process RSS: 29,855,744 bytes. This is not model-inference RAM.
- No PyTorch in `.venv`; PyTorch/CUDA build versions, CUDA availability and
  tensor allocation/reservation/peaks are **unknown**. Driver usage/free values
  are separate measurements, not substituted allocator metrics.

Memory availability changes with other processes. No assertion is made that
the combined models fit this GPU, or that allocated and reserved memory agree.

## How to run the already installed project

```powershell
cd local-ai-analysis-platform
.\.venv\Scripts\local-ai-server.exe
```

In another PowerShell window in this directory:

```powershell
.\.venv\Scripts\pytest.exe
.\.venv\Scripts\ruff.exe check .
```

Fresh setup, authenticated API examples and profiling commands are in
`README.md`. The server is not left running by the tests.

## Limitations and remaining decisions

- No AI detector, similarity engine, claim verifier, model training, live SSE,
  model leases, ONNX deployment or MV3 extension yet; no mock predictions.
- JSON Schema is structural; semantic offset, normalization and revision
  checks are also required. A future browser client must pass the same fixtures.
- The revision registry is one-process memory only. TTL expiry or restart loses
  history, so clients must re-register their current revision. It is not a
  persistent, multi-worker anti-replay store.
- Async deadlines are cooperative; cancellation does not forcibly stop an
  already running synchronous Python thread. GPU admission/worker isolation
  and cancellation checkpoints are Phase 4 work.
- The 1 MiB wire cap includes offset arrays; schema character caps alone are
  not a promise that a large document fits in a request.
- Launching uvicorn directly can bypass the loopback-only CLI; do not expose
  it publicly. Windows secret-file ACLs inherit the project directory policy.
- Source/editable installation is tested; standalone wheel deployment with
  bundled configuration and dependency security auditing is not certified.
- Exact model/tokenizer revisions/licenses, PyTorch/CUDA build, approved data
  and split rules, feature resources/profiles, claim/NLI/reranker models,
  calibration thresholds, evidence corpus, SSE retention and independently
  supported editor APIs remain decisions documented in `docs/decisions.md`.
- Browser support, model accuracy, calibration, GPU fit and latency all require
  later executable integrations and measured experiments.

Recommended next increment: **Phase 1 AI detection**, beginning with resource
and dataset decisions and a frozen feature pipeline before training.
