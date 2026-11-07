"""Primary lightweight PDF parser. Bytes only: never accept a user URL or local path."""
from io import BytesIO

MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_TEXT = 200_000
MAX_PAGES = 200


def extract_pdf(data):
    if len(data) > MAX_PDF_BYTES or not data.lstrip().startswith(b"%PDF-"):
        raise ValueError("The active document is not a supported PDF (limit: 16 MB)")
    from docling_parse.pdf_parser import ContentConfig, ContentLevel, DecodeConfig, DoclingPdfParser

    parser = DoclingPdfParser(loglevel="fatal")
    doc = parser.load(
        path_or_stream=BytesIO(data),
        decode_config=DecodeConfig(do_sanitization=True, keep_glyphs=False),
        content_config=ContentConfig(
            char_cells_content_level=ContentLevel.SKIP,
            word_cells_content_level=ContentLevel.SKIP,
            line_cells_content_level=ContentLevel.COMPUTE_AND_MATERIALIZE,
            shapes_content_level=ContentLevel.SKIP,
            bitmaps_content_level=ContentLevel.SKIP,
        ),
    )
    blocks, empty_pages = [], []
    try:
        if doc.number_of_pages() > MAX_PAGES:
            raise ValueError("This PDF exceeds the 200-page limit")
        for page_no, page in doc.iterate_pages():
            # Parser-order lines preserve PDF text cells. No claim of ML layout ordering.
            lines = [cell.text.strip() for cell in page.textline_cells if cell.text.strip()]
            if not lines:
                empty_pages.append(page_no)
            # Join wrapped lines into paragraphs; preserve large vertical gaps/headings.
            grouped, current, previous = [], [], None
            page_box = page.dimension.rect.to_bounding_box()
            page_height = abs(page_box.t - page_box.b)
            for cell in page.textline_cells:
                value = cell.text.strip()
                if not value:
                    continue
                box = cell.rect.to_bounding_box().to_top_left_origin(page_height)
                gap = box.t - previous.b if previous else 0
                heading_change = previous and (abs(box.b - box.t) > 1.3 * abs(previous.b - previous.t) or abs(previous.b - previous.t) > 1.3 * abs(box.b - box.t))
                if previous and (heading_change or gap > max(abs(previous.b - previous.t) * 0.8, 8) or box.l < previous.l - 50):
                    grouped.append(" ".join(current))
                    current = []
                current.append(value)
                previous = box
            if current:
                grouped.append(" ".join(current))
            blocks.extend({"page": page_no, "text": value} for value in grouped)
            if sum(len(block["text"]) for block in blocks) > MAX_TEXT:
                raise ValueError("This PDF exceeds the 200,000-character limit")
    finally:
        doc.unload()
    text = "\n\n".join(block["text"] for block in blocks)
    if not text.strip():
        raise ValueError("No readable text was found. Image-only or protected PDFs need a text layer")
    return {"text": text, "blocks": blocks, "empty_pages": empty_pages, "note": "Review extraction order before scanning. Complex layouts may need correction."}
