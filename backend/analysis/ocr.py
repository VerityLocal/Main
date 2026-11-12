"""Selective local Tesseract OCR; never fetch language data."""

import csv
from io import StringIO
from statistics import mean
import subprocess

from backend.analysis.types import SourceLine


def parse_tsv(text: str, page: int, bbox: list[float], image_size: tuple[int, int]) -> list[SourceLine]:
    groups = {}
    for row in csv.DictReader(StringIO(text), delimiter="\t"):
        if row.get("level") != "5" or not row.get("text", "").strip():
            continue
        key = tuple(row[name] for name in ("block_num", "par_num", "line_num"))
        groups.setdefault(key, []).append(row)
    lines = []
    sx, sy = (bbox[2] - bbox[0]) / image_size[0], (bbox[3] - bbox[1]) / image_size[1]
    leftmost = min((int(row["left"]) for group in groups.values() for row in group), default=0)
    for group in groups.values():
        group.sort(key=lambda row: int(row["left"]))
        x = min(int(row["left"]) for row in group)
        y = min(int(row["top"]) for row in group)
        right = max(int(row["left"]) + int(row["width"]) for row in group)
        bottom = max(int(row["top"]) + int(row["height"]) for row in group)
        char_width = max(1.0, mean(int(row["width"]) / max(1, len(row["text"])) for row in group))
        value = " " * min(80, round((x - leftmost) / char_width))
        previous_right = x
        for i, row in enumerate(group):
            if i:
                value += " " * max(1, min(40, round((int(row["left"]) - previous_right) / char_width)))
            value += row["text"]
            previous_right = int(row["left"]) + int(row["width"])
        confidence = mean(max(0, float(row["conf"])) for row in group)
        lines.append(SourceLine(value, page, [bbox[0] + x*sx, bbox[1] + y*sy,
                                             bbox[0] + right*sx, bbox[1] + bottom*sy],
                                method="ocr", confidence=confidence))
    return lines


def recognize(image, page: int, bbox: list[float], directory, timeout: float,
              command="tesseract", tessdata_dir=None) -> list[SourceLine]:
    path = directory / "ocr.png"
    image.save(path)
    args = [command, str(path), "stdout", "-l", "eng", "--psm", "6"]
    if tessdata_dir:
        args += ['--tessdata-dir', str(tessdata_dir)]
    result = subprocess.run(
        args + ["tsv"],
        capture_output=True, text=True, timeout=timeout, check=True,
    )
    return parse_tsv(result.stdout, page, bbox, image.size)
