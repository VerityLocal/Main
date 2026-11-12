"""Disposable parser/OCR process. All paths are created by the backend, never clients."""

import hashlib
import json
import math
from pathlib import Path
import socket
from statistics import median
import subprocess
import sys

from backend.analysis.capabilities import capabilities
from backend.analysis.ocr import recognize
from backend.analysis.types import AnalysisError, Document, Page, SourceLine
from backend.analysis.regions import deduplicate_regions
from backend.config import Settings


def emit(stage, current=0, total=1):
    print("PDF_AI_EVENT " + json.dumps({"stage": stage, "current": current, "total": total}), flush=True)


def intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def bounded_box(box, width, height):
    box = [float(value) for value in box]
    if not all(math.isfinite(value) for value in box):
        raise AnalysisError("invalid_geometry", "PDF contains invalid page geometry.")
    return [max(0, min(width, box[0])), max(0, min(height, box[1])),
            max(0, min(width, box[2])), max(0, min(height, box[3]))]


def check_page_count(count, settings):
    if count == 0:
        raise AnalysisError("empty_pdf", "PDF has no pages.")
    if count > settings.max_pages:
        raise AnalysisError("page_limit", f"PDF exceeds the {settings.max_pages}-page limit; no subset was analyzed.")


def check_chars(pages, settings):
    if sum(len(line.text) for page in pages for line in page.lines) > settings.max_extracted_chars:
        raise AnalysisError("content_limit", "Extracted content exceeds the configured resource limit.")


def source_code_cells(tables, text_lines):
    """Recognize source inside a table cell; a form's border is not a data modality."""
    from backend.analysis.segmentation import CODE, PSEUDO, code_language
    cells=[]
    for table in tables:
        columns={}
        for box in table.cells:
            if box is not None:
                columns.setdefault((round(box[0],1),round(box[2],1)),[]).append(box)
        groups=[]
        for column in columns.values():
            cluster=[]
            for cell in sorted(column,key=lambda box:box[1]):
                if cluster and cell[1]-max(box[3] for box in cluster) > 2:
                    groups.append(cluster)
                    cluster=[]
                cluster.append(cell)
            if cluster:
                groups.append(cluster)
        for boxes in groups:
            # Ruled code boxes can be reported as one cell per source line.
            box=[min(cell[0] for cell in boxes),min(cell[1] for cell in boxes),
                 max(cell[2] for cell in boxes),max(cell[3] for cell in boxes)]
            values=[text for line_box,text in text_lines if intersection(line_box,box)/max(
                1,(line_box[2]-line_box[0])*(line_box[3]-line_box[1]))>.7]
            anchors=sum(bool(CODE.search(text)) for text in values)
            pseudo=any(PSEUDO.search(text) and not CODE.search(text) for text in values)
            if not pseudo and anchors>=3 and anchors/max(1,len(values))>=.25 and code_language("\n".join(values)) in {
                    "python","javascript","outside_validation_domain"}:
                cells.extend(boxes)
    return cells


def plumber_extract(path, settings):
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    pages = []
    try:
        with pdfplumber.open(path) as pdf:
            # Reject even PDFs which open with an empty password: permissions are not bypassed.
            if pdf.doc.encryption:
                raise AnalysisError("encrypted_pdf", "Encrypted PDFs are not supported; provide an unlocked copy.")
            check_page_count(len(pdf.pages), settings)
            for i, page in enumerate(pdf.pages):
                if len(page.chars) > settings.max_extracted_chars:
                    raise AnalysisError("content_limit", "A PDF page exceeds the content limit.")
                raw = page.extract_text_lines(layout=False, return_chars=True)
                baseline = min((line["x0"] for line in raw if line["top"] > page.height*.12), default=36)
                # A single-column border around prose/code is not a data table.
                grid_tables = [table for table in page.find_tables() if len(table.columns) > 1]
                tables = [table.bbox for table in grid_tables]
                code_cells = source_code_cells(grid_tables,[(
                    [line["x0"],line["top"],line["x1"],line["bottom"]],line["text"]) for line in raw])
                result = Page(i + 1, float(page.width), float(page.height))
                for line in raw:
                    chars = line["chars"]
                    sizes = [float(char.get("size", 11)) for char in chars]
                    size = median(sizes) if sizes else 11
                    fonts = " ".join(str(char.get("fontname", "")) for char in chars).lower()
                    text = line["text"]
                    # Infer leading indentation from PDF geometry; internal extracted whitespace is retained.
                    text = " " * min(80, max(0, round((line["x0"] - baseline) / max(1, size*.4)))) + text
                    box = bounded_box([line["x0"], line["top"], line["x1"], line["bottom"]], page.width, page.height)
                    area = max(1, (box[2]-box[0])*(box[3]-box[1]))
                    table_hint = any(intersection(box, table) / area > .7 for table in tables)
                    result.lines.append(SourceLine(text, i+1, box, mono=any(
                        name in fonts for name in ("courier", "consolas", "mono", "menlo")),
                        bold="bold" in fonts, size=size,
                        hint="code" if any(intersection(box,cell)/area>.7 for cell in code_cells) else "table" if table_hint else ""))
                result.regions = [{"bbox": bounded_box([image["x0"], image["top"], image["x1"], image["bottom"]],
                                                         page.width, page.height), "status": "unclassified_image"}
                                  for image in page.images]
                if not result.lines and not result.regions:
                    result.status = "blank_or_vector_only"
                    result.warnings.append("No native text or raster images; vector-only figures/text may be unaccounted for.")
                pages.append(result)
                check_chars(pages, settings)
                emit("extracting", i+1, len(pdf.pages))
                page.close()
    except PDFPasswordIncorrect as exc:
        raise AnalysisError("encrypted_pdf", "Encrypted PDFs are not supported.") from exc
    except PdfminerException as exc:
        if exc.args and isinstance(exc.args[0], PDFPasswordIncorrect):
            raise AnalysisError("encrypted_pdf", "Encrypted PDFs are not supported.") from exc
        raise
    return Document(pages, "pdfplumber", ["Interim native fallback: Docling/PyMuPDF layout parity is not established.",
                                           "PDF indentation is inferred from geometry; extraction may alter original formatting."])


def mupdf_extract(path, settings):
    import pymupdf

    pages = []
    with pymupdf.open(path) as pdf:
        if pdf.is_encrypted:
            raise AnalysisError("encrypted_pdf", "Encrypted PDFs are not supported.")
        check_page_count(len(pdf), settings)
        for i, page in enumerate(pdf):
            # All provenance uses unrotated crop-box, top-left coordinates. This
            # is an in-memory change only; the submitted PDF is never rewritten.
            page.set_rotation(0)
            record = Page(i+1, float(page.rect.width), float(page.rect.height))
            blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
            native_lines = [line for block in blocks if block.get("type") == 0 for line in block["lines"]]
            baseline = min((line["bbox"][0] for line in native_lines if line["bbox"][1] > record.height*.12), default=36)
            grid_tables = [table for table in page.find_tables().tables if table.col_count > 1]
            tables = [list(table.bbox) for table in grid_tables]
            code_cells = source_code_cells(grid_tables,[(line["bbox"],"".join(span["text"] for span in line["spans"]))
                                                         for line in native_lines])
            for line in sorted(native_lines, key=lambda value: (round(value["bbox"][1], 1), value["bbox"][0])):
                spans = line["spans"]
                size = median([span["size"] for span in spans]) if spans else 11
                fonts = " ".join(span.get("font", "") for span in spans).lower()
                text = " " * min(80, max(0, round((line["bbox"][0]-baseline)/max(1, size*.4))))
                previous = None
                for span in spans:
                    if previous is not None and span["bbox"][0] - previous > size*.3:
                        text += " " * max(1, min(40, round((span["bbox"][0]-previous)/max(1, size*.4))))
                    text += span["text"]
                    previous = span["bbox"][2]
                box = bounded_box(line["bbox"], record.width, record.height)
                area = max(1, (box[2]-box[0])*(box[3]-box[1]))
                record.lines.append(SourceLine(text, i+1, box, mono=any(name in fonts for name in
                                                  ("courier", "consolas", "mono", "menlo")), bold="bold" in fonts,
                                               size=size,hint="code" if any(intersection(box,cell)/area>.7 for cell in code_cells)
                                               else "table" if any(intersection(box,t)/area>.7 for t in tables) else ""))
            record.regions = [{"bbox": bounded_box(list(image["bbox"]), record.width, record.height),
                               "status": "unclassified_image"} for image in page.get_image_info()]
            pages.append(record)
            check_chars(pages, settings)
            emit("extracting", i+1, len(pdf))
    return Document(pages, "pymupdf", ["PDF indentation is inferred from geometry; original whitespace is not guaranteed."])


def verify_layout_assets(directory):
    manifest_path = directory / "approved-manifest.json"
    if manifest_path.stat().st_size > 2_000_000:
        raise ValueError("Asset manifest is too large")
    manifest = json.loads(manifest_path.read_text())
    expected = manifest["files"]
    if not isinstance(expected,dict) or not expected or len(expected) > 10000:
        raise ValueError("An explicit, nonempty asset manifest is required")
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
              and path != manifest_path}
    if actual != set(expected):
        raise ValueError("Every local layout asset must be explicitly hash-manifested")
    for name, digest in expected.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError("Unsafe or missing local asset")
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                raise ValueError("Layout asset hash mismatch")


def docling_layout(path, document, settings):
    """Use approved local Docling layout to label native spans, without re-generating code."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    verify_layout_assets(settings.docling_assets_dir)
    options = PdfPipelineOptions(artifacts_path=settings.docling_assets_dir, do_ocr=False,
                                 do_table_structure=True, enable_remote_services=False,
                                 generate_page_images=False, generate_picture_images=False)
    converter = DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    converted = converter.convert(path, max_num_pages=settings.max_pages,
                                   max_file_size=settings.max_upload_bytes).document
    for item, _ in converted.iterate_items():
        label = str(getattr(item.label, "value", item.label))
        for provenance in getattr(item, "prov", []):
            number = provenance.page_no
            if not 1 <= number <= len(document.pages):
                continue
            page = document.pages[number-1]
            bbox = provenance.bbox.to_top_left_origin(page_height=page.height)
            box = [bbox.l, bbox.t, bbox.r, bbox.b]
            for line in page.lines:
                area = max(1, (line.bbox[2]-line.bbox[0])*(line.bbox[3]-line.bbox[1]))
                if intersection(box, line.bbox)/area > .7:
                    if not (line.hint=="code" and label=="table"):
                        line.hint = label
    document.engine = "docling+" + document.engine


def ocr_regions(document, settings):
    pending = []
    for page in document.pages:
        deduplicate_regions(page)
        area = max(1, page.width*page.height)
        for region in page.regions:
            box = region["bbox"]
            fraction = (box[2]-box[0])*(box[3]-box[1])/area
            overlaps = [(line,intersection(line.bbox,box)) for line in page.lines if line.method=="native"]
            letters = sum(len(line.text.strip()) for line,overlap in overlaps if overlap > 0)
            covered = sum(overlap for _,overlap in overlaps)/max(1,(box[2]-box[0])*(box[3]-box[1]))
            if fraction < .005:
                region["status"] = "ignored_small_image"
            elif letters > 40 and covered >= .4:
                region["status"] = "native_text_present"
            else:
                region["status"] = "needs_ocr"
                pending.append((page, region))
    return pending


def render(path, page, box, engine, settings):
    # pdfplumber renders the full media box before cropping. Bound that backing
    # image too, not just the requested small screenshot region.
    width,height = (box[2]-box[0],box[3]-box[1]) if "pymupdf" in engine else (page.width,page.height)
    scale = min(2.0, math.sqrt(settings.max_render_pixels / max(1,(width+4)*(height+4))))
    if scale < .25:
        raise ValueError("Image region exceeds rendering limits")
    if "pymupdf" in engine:
        import pymupdf
        from PIL import Image
        with pymupdf.open(path) as pdf:
            original = pdf[page.number-1]
            original.set_rotation(0)
            pixmap = original.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=pymupdf.Rect(box), alpha=False)
            return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        rendered = pdf.pages[page.number-1].crop(tuple(box)).to_image(resolution=72*scale,force_mediabox=True)
        try:
            if rendered.original.width*rendered.original.height > settings.max_render_pixels:
                raise ValueError("Rendered image exceeds the pixel limit")
            return rendered.original.copy()
        finally:
            rendered.original.close()
            rendered.annotated.close()


def extract(path, settings):
    caps = capabilities(settings)
    document = None
    failures = []
    for engine in caps["native_engines"]:
        try:
            document = (mupdf_extract if engine == "pymupdf" else plumber_extract)(path, settings)
            break
        except AnalysisError:
            raise
        except Exception:
            failures.append(engine)
    if document is None:
        raise AnalysisError("invalid_pdf" if failures else "pdf_tools_missing",
                            "PDF could not be parsed safely." if failures else "No local PDF extractor is installed.")
    if failures:
        document.warnings.append("Failed extractors: " + ", ".join(failures))
    if caps["docling_configured"]:
        try:
            docling_layout(path, document, settings)
        except Exception:
            document.warnings.append("Docling layout failed or local assets were incomplete; native fallback used.")
    else:
        document.warnings.append("Docling unavailable or approved local layout assets not configured.")
    pending = ocr_regions(document, settings)
    available = caps["ocr_configured"]
    if available:
        try:
            command = [settings.tesseract_command]
            if settings.tessdata_dir:
                command += ['--tessdata-dir', str(settings.tessdata_dir)]
            languages = subprocess.run(command + ["--list-langs"], capture_output=True, text=True,
                                       timeout=10, check=True).stdout.splitlines()
            available = "eng" in languages
        except Exception:
            available = False
    counts = {}
    for i, (page, region) in enumerate(pending):
        emit("ocr", i, len(pending))
        counts[page.number] = counts.get(page.number, 0) + 1
        if not available:
            region["status"] = "ocr_unavailable"
        elif counts[page.number] > settings.max_ocr_regions_per_page:
            region["status"] = "ocr_region_limit"
        else:
            try:
                image = render(path, page, region["bbox"], document.engine, settings)
                try:
                    lines = recognize(image, page.number, region["bbox"], path.parent, timeout=20,
                                      command=settings.tesseract_command, tessdata_dir=settings.tessdata_dir)
                finally:
                    image.close()
                region["status"] = "ocr_extracted" if lines else "no_readable_text"
                page.lines.extend(line for line in lines if not any(
                    line.text.strip() == existing.text.strip() and intersection(line.bbox, existing.bbox) > 0
                    for existing in page.lines))
                page.lines.sort(key=lambda line: (round(line.bbox[1], 1), line.bbox[0]))
                check_chars(document.pages, settings)
            except AnalysisError:
                raise
            except Exception:
                region["status"] = "ocr_failed"
    if pending:
        document.warnings.append("Image regions may contain code, tables, diagrams, or text; OCR coverage is not authorship coverage.")
        if not available:
            document.warnings.append("OCR unavailable: scanned/screenshot content was not scored.")
    return document


def main():
    payload = json.loads(Path(sys.argv[1]).read_text())
    settings = Settings(**payload["settings"])
    # Deny Python network connections in the disposable extraction process.
    def deny_network(*args, **kwargs):
        raise OSError("Network access is disabled in local PDF extraction")
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    try:
        result = {"document": extract(Path(payload["input"]), settings).to_dict()}
    except AnalysisError as exc:
        result = {"error": {"code": exc.code, "message": str(exc)}}
    except Exception:
        result = {"error": {"code": "extraction_failed", "message": "PDF extraction failed; no scores were produced."}}
    Path(payload["output"]).write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
