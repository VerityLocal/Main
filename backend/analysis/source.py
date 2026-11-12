"""UTF-8 source ingestion; exact source slices, no fabricated PDF coordinates."""

import re

from backend.analysis.languages import code_language, withholding_reason
from backend.analysis.types import AnalysisError, Document, Segment


FORMATS = {'pdf': 'application/pdf', 'text': 'text/plain',
           'python': 'text/x-python', 'javascript': 'text/javascript'}


def decode_source(data, settings):
    if len(data) > settings.max_upload_bytes:
        raise AnalysisError('upload_limit', 'File exceeds the upload limit.')
    try:
        # BOM is an encoding marker, not a submitted source character.
        text = data.decode('utf-8-sig', errors='strict')
    except UnicodeDecodeError as exc:
        raise AnalysisError('invalid_encoding', 'Source files must use UTF-8 encoding.') from exc
    if not text.strip():
        raise AnalysisError('empty_source', 'Source file has no readable content.')
    if any(ord(char) < 32 and char not in '\t\r\n\f' for char in text):
        raise AnalysisError('binary_source', 'Binary/control-byte content is not supported.')
    if len(text) > settings.max_extracted_chars:
        raise AnalysisError('content_limit', 'Source exceeds the character limit.')
    return text


def source_document(data, file_format, settings):
    return Document([], 'original_utf8', [], decode_source(data, settings), file_format)


def segment_source(document):
    from backend.analysis.segmentation import english_gate
    text = document.source_text
    segments = []
    # Declared source listings are gated as a whole, so mixed language code cannot
    # become eligible by splitting it into convenient individual chunks.
    spans = [(0, len(text))] if document.source_format != 'text' else [
        (match.start(), match.end()) for match in re.finditer(r'[\s\S]+?(?:\r?\n[ \t]*\r?\n|\Z)', text)]
    for start, end in spans:
        value = text[start:end]
        if not value.strip():
            continue
        language = code_language(value)
        is_code = document.source_format != 'text' or language != 'unknown'
        kind = 'code' if is_code else 'text'
        reason = withholding_reason(language) if is_code else ''
        if is_code and not reason and document.source_format in {'python', 'javascript'} and language != document.source_format:
            reason = 'declared_language_mismatch'
        if not is_code:
            language = english_gate(value)
            reason = '' if language == 'english_likely' else 'non_english_or_unknown'
        # One source range per original line supports exact highlighting even
        # after chunks are sliced and paragraphs are combined.
        sources = []
        offset = start
        line_number = text.count('\n', 0, start)+1
        for line in value.splitlines(keepends=True):
            sources.append({'method': 'source', 'line': line_number,
                            'start': offset-start, 'end': offset-start+len(line),
                            'source_start': offset, 'source_end': offset+len(line)})
            offset += len(line)
            line_number += line.count('\n')
        segments.append(Segment(f's{len(segments)+1}', kind, value, sources, 'Original source', language, reason))
    return segments
