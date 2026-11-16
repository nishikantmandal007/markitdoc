import fitz
from fpdf import FPDF
import logging
import io
import re
import matplotlib.pyplot as plt
import ziamath
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=64)
def equation_svg(tex, color):
    previous = {key: plt.rcParams[key] for key in ("svg.fonttype", "svg.hashsalt", "mathtext.fontset")}
    plt.rcParams.update({"svg.fonttype": "path", "svg.hashsalt": "docgen", "mathtext.fontset": "stix"})
    figure = plt.figure(figsize=(0.01, 0.01))
    try:
        figure.text(0, 0, f"${tex}$", fontsize=15, color=color)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="svg", bbox_inches="tight", pad_inches=0.03, transparent=True, metadata={"Date": None})
        return re.sub(rb"<metadata>.*?</metadata>", b"", buffer.getvalue(), flags=re.S)
    finally:
        plt.close(figure)
        plt.rcParams.update(previous)


mathtext_equivalents = {r"\implies": r"\Rightarrow", r"\impliedby": r"\Leftarrow", r"\iff": r"\Leftrightarrow",
                        r"\dfrac": r"\frac", r"\tfrac": r"\frac", r"\operatorname": r"\mathrm", r"\lvert": "|",
                        r"\rvert": "|", r"\lVert": r"\Vert", r"\rVert": r"\Vert", r"\le ": r"\leq ", r"\ge ": r"\geq "}


def mathtext_ready(tex):
    tex = " ".join(tex.split())
    for command, equivalent in mathtext_equivalents.items():
        tex = re.sub(re.escape(command) + r"(?![A-Za-z])", lambda _: equivalent, tex)
    return tex


@lru_cache(maxsize=64)
def typeset_svg(tex, color):
    return ziamath.Latex(tex, size=15, color=color).svg().encode()


def equation_drawing(tex, color):
    try:
        return typeset_svg(tex, color)
    except Exception as error:
        logger.info("Equation typeset with the fallback engine: %s", type(error).__name__)
    return equation_svg(tex, color)


def svg_size(svg):
    width = re.search(rb'width="([\d.]+)(pt|px)?"', svg)
    height = re.search(rb'height="([\d.]+)(pt|px)?"', svg)
    unit = 0.3528 if width and width.group(2) == b"pt" else 0.2646
    return (float(width.group(1)) * unit, float(height.group(1)) * unit) if width and height else (60.0, 12.0)


def equation_png(deck, tex):
    return equation_png_bytes(mathtext_ready(tex), "#" + deck.theme.colors["ink"].lstrip("#"))


def equation_png_bytes(tex, color):
    svg = equation_drawing(tex, color)
    width, height = svg_size(svg)
    sheet = FPDF(unit="mm", format=(width, height))
    sheet.set_margins(0, 0, 0)
    sheet.add_page()
    sheet.image(io.BytesIO(svg), x=0, y=0, w=width, h=height)
    with fitz.open(stream=bytes(sheet.output()), filetype="pdf") as drawing:
        return io.BytesIO(drawing[0].get_pixmap(dpi=400, alpha=True).tobytes("png")), (width, height)
