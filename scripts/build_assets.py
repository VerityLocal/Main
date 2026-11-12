"""Rebuild Verity Local's icons and public demonstration PDF (requires dev dependencies)."""

from pathlib import Path
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parent.parent


def icons():
    directory = ROOT / "extension" / "icons"
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 511, 511), radius=140, fill="#162d29")
    draw.line(((128, 176), (256, 368), (384, 176)), fill="#b3e5bc", width=48, joint="curve")
    for x, y in ((128, 176), (256, 368), (384, 176)):
        draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill="#b3e5bc")
    for size in (16, 32, 48, 128):
        image.resize((size, size), Image.Resampling.LANCZOS).save(directory / f"icon-{size}.png")


def demo():
    directory = ROOT / "docs" / "examples"
    directory.mkdir(parents=True, exist_ok=True)
    pdf = Canvas(str(directory / "verity-local-demo.pdf"), pagesize=(612, 792), invariant=1)
    pdf.setTitle("Verity Local — demonstration document")
    pdf.setAuthor("Verity Local")

    def heading(number, subtitle):
        pdf.setFillColor(colors.HexColor("#162d29"))
        pdf.rect(0, 692, 612, 100, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#b3e5bc"))
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(48, 755, "VERITY LOCAL / PUBLIC DEMONSTRATION")
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 23)
        pdf.drawString(48, 716, subtitle)
        pdf.setFillColor(colors.HexColor("#53665f"))
        pdf.setFont("Helvetica", 9)
        pdf.drawString(48, 35, "Synthetic example for learning the interface. No authorship labels.")
        pdf.drawRightString(564, 35, str(number))

    heading(1, "A closer look at a simple experiment")
    paragraphs = [
        "Our team investigated how the resistance of a component affects the current in a small electrical circuit. We connected a resistor to a variable power supply and used a multimeter to measure the voltage across it. Each reading was written in a notebook before the voltage was changed. We repeated the measurements to check whether the pattern was consistent.",
        "The current increased as the applied voltage increased. For the range of values tested, the relationship was approximately linear. This observation agrees with the expectation for an ordinary resistor operating at a steady temperature. Small differences between repeated readings may be explained by instrument resolution, loose contacts, or changes in the temperature of the component.",
        "We also wrote a short program to summarize the measurements. The program keeps valid numerical readings, calculates their average, and reports the difference between the highest and lowest values. This helped us identify a reading that had been entered incorrectly. We checked the original notebook before changing that value, so the summary remained traceable to the measurements.",
        "The experiment illustrates why a result should be examined alongside the evidence that produced it. A summary value can help a reader find a pattern, but it cannot explain every detail of a measurement. The next step would be to repeat the procedure with additional components and a wider range of temperatures. More observations would help us distinguish a consistent effect from a one-off variation."
    ]
    y = 654
    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.HexColor("#253c34"))
    for paragraph in paragraphs:
        for line in simpleSplit(paragraph, "Helvetica", 11, 516):
            pdf.drawString(48, y, line)
            y -= 17
        y -= 18
    pdf.showPage()
    heading(2, "The source behind the summary")
    code = '''def summarize_readings(readings):
    # Retain numeric observations in their original order.
    valid = []
    for reading in readings:
        if isinstance(reading, (int, float)):
            valid.append(reading)
    if not valid:
        return {"count": 0, "average": None}
    total = sum(valid)
    average = total / len(valid)
    return {"count": len(valid), "average": average}


def measurement_spread(readings):
    valid = [value for value in readings
             if isinstance(value, (int, float))]
    if len(valid) < 2:
        return 0
    smallest = min(valid)
    largest = max(valid)
    return largest - smallest


def compare_trials(first_trial, second_trial):
    first = summarize_readings(first_trial)
    second = summarize_readings(second_trial)
    if not first["count"] or not second["count"]:
        return None
    return second["average"] - first["average"]
'''
    pdf.setFillColor(colors.HexColor("#253c34"))
    pdf.setFont("Courier", 10)
    for index, line in enumerate(code.splitlines()):
        pdf.drawString(48, 653 - index * 17, line)
    pdf.showPage()
    pdf.save()
    (directory / "measurements.py").write_text(code, encoding="utf-8")
    (directory / "experiment.txt").write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")


if __name__ == "__main__":
    icons()
    demo()
    print("Built extension icons and public demonstration files.")
