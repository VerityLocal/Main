"""First-party functional acceptance input; not calibration/evaluation data."""
import textwrap

SOURCE_TEXT = "A rain garden is a shallow planted area that collects water from roofs and paved surfaces. Its soil and vegetation help water soak into the ground instead of rushing into storm drains."
ORIGINAL_TEXT = "I planted three shrubs beside the old shed last April. The smallest one survived because my neighbor watered it whenever I was away, and the bare patch has finally turned green."


def pdf(title, paragraphs, blank=False):
    def escape(value):
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines = ["BT /F1 18 Tf 50 750 Td (" + escape(title) + ") Tj", "/F1 11 Tf 0 -35 Td"]
    for paragraph in paragraphs:
        for line in textwrap.wrap(paragraph, width=85):
            lines.append("(" + escape(line) + ") Tj 0 -17 Td")
        lines.append("0 -18 Td")
    stream = ("\n".join(lines) + "\nET").encode("ascii") if not blank else b""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"]
    output, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(output)
