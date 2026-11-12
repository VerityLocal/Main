# Verity Local dependencies

## Default setup

The pinned [`requirements.txt`](../requirements.txt) installs the backend, CPU-capable model runtime, native PDF extraction, and image support. Use Python 3.11+ in a virtual environment:

```sh
python -m pip install -r requirements.txt
python -m backend.scripts.download_models
```

The validated local environment uses Python 3.14.6, torch 2.13.0, transformers 5.22.2, safetensors 0.8.0, FastAPI 0.143.0, Pydantic 2.14.1, uvicorn 0.54.0, pdfplumber 0.11.10, and Pillow 12.3.0. Development tests add httpx 0.28.1 and ReportLab 5.1.0.

The ready-to-load extension includes PDF.js 6.5.438, fonts, CMaps, WASM, and their licenses. A Git clone builds those assets with `npm ci --ignore-scripts` and `npm run build` in `extension/`.

## Optional OCR

Scanned regions require a local **Tesseract executable**, English `eng` traineddata, and a renderer. pdfplumber's pypdfium2 dependency provides a renderer in the default environment.

macOS with Homebrew:

```sh
brew install tesseract
```

Ubuntu / Debian / WSL:

```sh
sudo apt install tesseract-ocr tesseract-ocr-eng
```

Check with `tesseract --list-langs`. Restart the backend after installation. Override paths using `PDF_AI_TESSERACT_COMMAND` and `PDF_AI_TESSDATA_DIR` if the tools are not on PATH. The launcher also recognizes a project-local `.tools-ocr/bin/tesseract` and `.tools-ocr/share/tessdata`.

OCR prose can be analyzed when extraction and content gates pass. OCR code is displayed but withheld by default because recognition errors can change source semantics.

## Optional isolated PyMuPDF

The default parser is pdfplumber. PyMuPDF can be installed in a separate `.venv-extraction/` environment, subject to its own AGPL/commercial terms. Set `PDF_AI_EXTRACTION_PYTHON` to that environment's Python. The launcher discovers `.venv-extraction/bin/python` automatically. The parser environment needs the extraction/image dependencies; it does not need to load detector weights.

## Optional Docling layout assets

Docling is not invoked merely because its package is installed. Configure `PDF_AI_DOCLING_ASSETS_DIR` to a local asset directory containing `approved-manifest.json`:

```json
{"files":{"relative/path/to/asset":"its_actual_sha256"}}
```

The manifest must enumerate every asset required by the selected pipeline. Missing, unlisted, or mismatched files are rejected. Missing assets/conversion errors produce a visible native-fallback warning. Parser workers use offline Hugging Face settings, a private cache, disabled Python network connections, and disabled remote Docling services. Tesseract OCR is handled separately.

See [model provenance](../docs/MODELS.md) and [third-party notices](../docs/THIRD_PARTY_NOTICES.md).
