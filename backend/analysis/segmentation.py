"""Conservative layout + syntax heuristics; ambiguous content is not forced into a model."""

from collections import Counter
import re

from backend.analysis.types import Document, Segment
from backend.analysis.languages import code_language, withholding_reason, language_evidence


HEADINGS = re.compile(
    r"^(?:\d+[.)]?\s*)?(aim|objective|resources?\s*(?:used|required)?|theory|introduction|"
    r"procedure|methodology|implementation|source\s*code|code|program(?:\s+code)?|(?:expected\s+|sample\s+|actual\s+)?output|results?|"
    r"observations?|discussion|conclusions?|references|bibliography|algorithm|pseudocode)\s*[:：]?\s*(.*)$", re.I)
CODE = re.compile(
    r"^\s*(?:def\s+\w+\s*\(|class\s+\w+\s*[:({]|package\s+[\w.]+\s*;|(?:from\s+[\w.]+\s+)?import\s+[\w.*]+|"
    r"(?:async\s+)?function\b|(?:const|let|var)\s+\w+\s*=|#\s*include\b|int\s+main\s*\(|"
    r"(?:public|private|protected)\s+(?:static\s+)?(?:class|void)|"
    r"(?:for|while|if|elif|except|with)\s+.+[:{]\s*$|(?:else|try|finally)\s*[:{]\s*$|"
    r"(?:return|yield|raise)\s+|[\w.\[\]'\"]+\s*(?:=|\+=|-=|\*=)\s*[^=]|"
    r"(?:print|console\.log|plt\.\w+|\w+\.append)\s*\(|\w+\s*=\s*require\s*\()")
SYMBOL_LINE = re.compile(r"^\s*(?:[{}\[\]();,]+|#(?!\s*include).+|//.*|/\*.*|\*.*|break;?|continue;?|pass|return;?)\s*$")
CONTINUATION = re.compile(r"^\s*(?:[\[\]{}()]+|['\"].*[,}]\s*$|\w+\s*\()")
PSEUDO = re.compile(r"^\s*(?:\d+[.)]?\s*)?(?:BEGIN|END IF|ENDIF|END FOR|ENDFOR|INPUT|OUTPUT|GOTO|REPEAT|UNTIL)\b|←")
META = re.compile(r"^(?:batch\b|roll\s*no|experiment\s*(?:no|number)|name\s*:|date\s*:|submitted\s*(?:by|to)|"
                  r"resources?\s*(?:used|required)|aim\s*:|objective\s*:)", re.I)
ENGLISH_WORDS = set("the a an and or to of in on for with is are was were this that these those it its "
                    "we our by from as at be have has can will not which when used using each into "
                    "data values between also their there during results obtained compare measured".split())


def english_gate(text: str) -> str:
    """A conservative English-support gate, not a calibrated language identifier."""
    letters = [char for char in text if char.isalpha()]
    if not letters or sum(char.isascii() for char in letters)/len(letters) < .85:
        return "non_english_or_unknown"
    words = re.findall(r"[A-Za-z]+", text.lower())
    hits = [word for word in words if word in ENGLISH_WORDS]
    if len(set(hits)) < 3 or len(hits)/max(1, len(words)) < .08:
        return "non_english_or_unknown"
    return "english_likely"


def margin_key(line):
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", line.text.strip().lower()))


def segment_document(document: Document) -> list[Segment]:
    if document.source_text is not None:
        from backend.analysis.source import segment_source
        return segment_source(document)
    repeats = Counter()
    for page in document.pages:
        repeats.update(set(margin_key(line) for line in page.lines
                           if line.bbox[1] < page.height*.09 or line.bbox[3] > page.height*.94))
    threshold = max(2, round(len(document.pages)*.5))
    segments = []
    section, scope = "", ""
    active = []
    active_kind, active_reason = "", ""
    previous = None

    def flush():
        nonlocal active, active_kind, active_reason
        if not active:
            return
        text, sources = "", []
        for line in active:
            if text:
                text += "\n"
            start = len(text)
            text += line.text
            sources.append({"page": line.page, "bbox": line.bbox, "method": line.method,
                            "ocr_confidence": line.confidence, "start": start, "end": len(text),
                            "source_start": 0, "source_end": len(line.text)})
        language = code_language(text) if active_kind == "code" else (english_gate(text) if active_kind == "text" else "unknown")
        reason = active_reason
        if active_kind == "text" and language != "english_likely":
            reason = "non_english_or_unknown"
        if active_kind == "code" and language not in {"python", "javascript"}:
            reason = withholding_reason(language)
        if active_kind == "code" and any(line.method == "ocr" for line in active):
            reason = "ocr_code_uncertain"  # OCR punctuation/indentation errors can change source semantics.
        segments.append(Segment(f"s{len(segments)+1}", active_kind, text, sources, section, language, reason))
        active = []
        active_kind, active_reason = "", ""

    for page in document.pages:
        lines = page.lines
        anchors = [bool(CODE.search(line.text) or line.hint == "code" or language_evidence(line.text)) for line in lines]
        for i, line in enumerate(lines):
            text = line.text.strip()
            if not text:
                continue
            heading = HEADINGS.match(text) if len(text) < 160 and not anchors[i] else None
            if heading and heading.group(2) and ":" not in text and "：" not in text:
                heading = None  # A wrapped sentence beginning "results were..." is not a heading.
            if heading:
                flush()
                section = heading.group(1).lower()
                scope = ("output" if section.endswith("output") or section in {"observation", "observations"}
                         else "references" if section in {"references", "bibliography"}
                          else "pseudocode" if section in {"algorithm", "pseudocode"}
                          else "code" if section in {"source code", "code", "program", "program code"} else "")
                segments.append(Segment(f"s{len(segments)+1}", "excluded", line.text,
                                        [{"page":line.page,"bbox":line.bbox,"method":line.method,
                                          "start":0,"end":len(line.text),"source_start":0,"source_end":len(line.text),
                                          "ocr_confidence":line.confidence}], section, reason="section_heading"))
                # Do not discard inline discussion/conclusion prose with its heading.
                suffix = heading.group(2)
                if suffix and section in {"theory", "discussion", "conclusion", "conclusions", "introduction"}:
                    offset = line.text.find(suffix)
                    quality_bad = "\ufffd" in suffix or (line.method == "ocr" and (line.confidence or 0) < 85)
                    language = english_gate(suffix)
                    reason = "extraction_quality" if quality_bad else "" if language=="english_likely" else "non_english_or_unknown"
                    segments.append(Segment(f"s{len(segments)+1}", "uncertain" if quality_bad else "text", suffix,
                                            [{"page":line.page,"bbox":line.bbox,"method":line.method,
                                              "start":0,"end":len(suffix),"source_start":offset,
                                              "source_end":offset+len(suffix),"ocr_confidence":line.confidence}],
                                            section, language, reason))
                    # The heading exclusion covers the prefix only, not this scored suffix.
                    heading_segment = segments[-2]
                    heading_segment.text = line.text[:offset]
                    heading_segment.sources[0]["end"] = offset
                    heading_segment.sources[0]["source_end"] = offset
                previous = None
                continue
            if scope == "output" and line.bold and len(text)<100 and len(text.split())>=2 and not anchors[i]:
                # Educational reports interleave small output examples and new
                # explanatory subheadings; don't let one example consume the rest.
                flush()
                section,scope = text,""
                active_kind,active_reason = "excluded","section_heading"
                active=[line]
                flush()
                previous=None
                continue
            kind, reason = "text", ""
            margin = line.bbox[1] < page.height*.09 or line.bbox[3] > page.height*.94
            if (margin and repeats[margin_key(line)] >= threshold) or re.fullmatch(r"(?:page\s*)?\d+(?:\s*(?:/|of)\s*\d+)?", text, re.I):
                kind, reason = "excluded", "boilerplate"
            elif META.match(text) or line.hint in {"page_header", "page_footer", "caption", "picture", "formula"}:
                kind, reason = "excluded", "metadata_or_figure"
            elif scope == "references":
                kind, reason = "excluded", "references"
            elif scope == "output":
                kind, reason = "excluded", "program_output_or_results"
            elif scope == "pseudocode" or (not anchors[i] and PSEUDO.search(text)):
                kind, reason = "uncertain", "pseudocode"
            elif line.hint == "table":
                kind, reason = ("uncertain", "code_or_pseudocode_table") if anchors[i] else ("excluded", "data_table")
            elif scope == "code" or anchors[i] or (SYMBOL_LINE.match(text) and any(anchors[max(0,i-2):min(len(lines),i+3)])):
                kind = "code"
            elif line.mono and (re.search(r"[{};=]|\w+\([^)]*\)", text) or active_kind == "code"):
                kind = "code"
            elif active_kind == "code" and CONTINUATION.search(text):
                kind = "code"
            elif re.search(r"(?:=>|</?\w+>|\bSELECT\b.+\bFROM\b)", text):
                kind = "code"
            elif re.fullmatch(r"[\d\s.,+\-*/=<>()[\]:%]+", text):
                kind, reason = "excluded", "numeric_output_or_formula"
            if "\ufffd" in text or (line.method == "ocr" and (line.confidence or 0) < 85):
                kind, reason = "uncertain", "extraction_quality"
            gap = previous is not None and previous.page == line.page and line.bbox[1]-previous.bbox[3] > max(12, line.size*.9)
            if kind != active_kind or reason != active_reason or (gap and kind == "text"):
                flush()
            active_kind, active_reason = kind, reason
            active.append(line)
            previous = line
    flush()
    return segments
