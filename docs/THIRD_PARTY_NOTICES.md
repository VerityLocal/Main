# Third-party notices

Verity Local uses these upstream components. Their licenses apply to their respective materials.

| Component | Source | License information |
| --- | --- | --- |
| PDF.js | [mozilla/pdf.js](https://github.com/mozilla/pdf.js) | Apache-2.0; `extension/vendor/PDFJS-LICENSE` is copied into built downloads. Font, CMap, and WASM notices are retained alongside their assets. |
| Text detector | [desklib/ai-text-detector-v1.01](https://huggingface.co/desklib/ai-text-detector-v1.01) | Upstream model card declares MIT; attribution: Desklib. |
| DeBERTa backbone | [microsoft/DeBERTa](https://github.com/microsoft/DeBERTa) | MIT; Microsoft Corporation. |
| CodeBERT backbone | [microsoft/CodeBERT](https://github.com/microsoft/CodeBERT) | MIT; Microsoft Corporation. |
| PyTorch | [pytorch.org](https://pytorch.org/) | BSD-style; installed by pip with its own notices. |
| Transformers / safetensors | [huggingface](https://github.com/huggingface) | Apache-2.0; installed by pip with their own notices. |
| pdfplumber | [jsvine/pdfplumber](https://github.com/jsvine/pdfplumber) | MIT; installed by pip. |
| Tesseract (optional) | [tesseract-ocr](https://github.com/tesseract-ocr/tesseract) | Apache-2.0; system installation. |
| PyMuPDF (optional) | [pymupdf.io](https://pymupdf.io/) | AGPL/commercial licensing; not included in the default requirements. |

## MIT license — model components above

Copyright (c) Microsoft Corporation (DeBERTa and CodeBERT).

Desklib's text model is attributed to Desklib and designated MIT in its upstream model card. The upstream repository does not supply a separate copyright-notice file.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The custom code adapter and Verity Local source are distinct from these upstream materials. This notice does not relicense the project or its evaluation documents.
