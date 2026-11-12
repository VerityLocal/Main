from dataclasses import asdict, dataclass, field


class AnalysisError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class SourceLine:
    text: str
    page: int
    bbox: list[float]
    method: str = "native"
    mono: bool = False
    bold: bool = False
    size: float = 11.0
    hint: str = ""
    confidence: float | None = None


@dataclass
class Page:
    number: int
    width: float
    height: float
    lines: list[SourceLine] = field(default_factory=list)
    regions: list[dict] = field(default_factory=list)
    status: str = "extracted"
    warnings: list[str] = field(default_factory=list)
    duplicate_regions_removed: int = 0


@dataclass
class Document:
    pages: list[Page]
    engine: str
    warnings: list[str] = field(default_factory=list)
    source_text: str | None = None
    source_format: str = "pdf"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            [Page(**{**page, "lines": [SourceLine(**line) for line in page["lines"]]}) for page in data["pages"]],
            data["engine"], data["warnings"], data.get("source_text"), data.get("source_format", "pdf"),
        )


@dataclass
class Segment:
    id: str
    kind: str
    text: str
    sources: list[dict]
    section: str = ""
    language: str = "unknown"
    reason: str = ""


@dataclass
class Chunk:
    id: str
    kind: str
    text: str
    content_tokens: int
    input_tokens: int
    sources: list[dict]
    section: str
    language: str
    reason: str = ""


def slice_sources(sources: list[dict], start: int, end: int) -> list[dict]:
    result = []
    for source in sources:
        left, right = max(start, source["start"]), min(end, source["end"])
        if left < right:
            result.append({**source, "start": left - start, "end": right - start,
                           "source_start": source.get("source_start", 0) + left - source["start"],
                           "source_end": source.get("source_start", 0) + right - source["start"]})
    return result
