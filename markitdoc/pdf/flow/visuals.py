import io
import logging
import re

from fpdf.enums import XPos, YPos
from PIL import Image

from markitdoc.markup.elements import CHART_SIZES, chart_data, settings_from
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.references import caption_of
from markitdoc.pdf.flow.pages import BODY_SIZE, FlowPages
from markitdoc.pdf.flow.text import add_caption, add_heading, add_list_item
from markitdoc.pdf.pages import escaped
from markitdoc.visuals.charts import render_chart
from markitdoc.visuals.diagrams import CANVAS_WIDTH, ZOOM, diagram_as_text, diagram_title, render_diagram
from markitdoc.visuals.infographics import render_infographic

logger = logging.getLogger(__name__)

SHORT_CODE_LINES = 12
BOX_DRAWING = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬"


# shrinks an image proportionally when only part of it fits on the page
def room_for(pdf: FlowPages, width, height, reserve):
    room = pdf.page_break_trigger - pdf.get_y() - reserve
    if height > room >= height * 0.6:
        return width * room / height, room
    return width, height


# places a centered picture on the PDF page with alternative text
def add_picture(pdf: FlowPages, picture, width, height, description="", ident=""):
    target = pdf.numbers.get(ident)
    width, height = room_for(pdf, width, height, 6)
    if pdf.will_page_break(height + 6 + (8 if target else 0)):
        pdf.add_page()
    pdf.mark_target(ident)
    pdf.image(picture, x=pdf.l_margin + (pdf.area - width) / 2, w=width, h=height, alt_text=description or None)
    if target:
        pdf.ln(1.5)
        add_caption(pdf, caption_of(target))
    pdf.ln(4)


# renders a code fence as text, chart, diagram, or code
def add_fence(pdf: FlowPages, language: str, content: str):
    settings = settings_from(language[language.find("{"):]) if "{" in language else {}
    ident = parse_attributes(language[language.find("{"):]).id if "{" in language else ""
    language = language.split("{")[0].strip()
    width = (pdf.area) * CHART_SIZES.get(settings.get("size", "full"), 1.0)
    if language in ("", "text", "plain", "plaintext") and sum(content.count(mark) for mark in BOX_DRAWING) >= 6:
        add_text_art(pdf, content)
        return
    if language.split()[:1] == ["infographic"]:
        syntax = f"{language}\n{content}" if " " in language else content
        path = render_infographic(syntax, pdf.theme)
        if path:
            with Image.open(path) as picture:
                height = width * picture.height / picture.width
            title = next((line.strip()[6:] for line in syntax.splitlines() if line.strip().startswith("title ")), "Infographic")
            add_picture(pdf, str(path), width, height, title)
        else:
            logger.warning("Infographic shown as a list instead")
            add_infographic_as_list(pdf, syntax)
        return
    if language == "mermaid":
        add_diagram(pdf, content, ident)
        return
    if language == "chart":
        data = chart_data(content)
        if not data:
            logger.warning("Chart skipped: invalid JSON, unknown type, no values, or a value count that differs from the labels")
        else:
            data["colors"] = ["#" + pdf.theme.colors[role].lstrip("#") for role in ("mood", "second", "muted", "primary", "success", "danger")]
            data["background"], data["font"] = "#" + pdf.theme.colors["paper"].lstrip("#"), str(pdf.theme.fonts["body"])
            reserve = 6 + (8 if ident in pdf.numbers else 0)
            width, height = room_for(pdf, width, width * (0.56 if data.get("source") else 0.5), reserve)
            try:
                image = render_chart(data, width_inches=width / 25.4, height_inches=height / 25.4)
            except Exception as error:
                logger.warning("Chart skipped: %s", type(error).__name__)
                return
            add_picture(pdf, io.BytesIO(image), width, height, f"Chart: {data.get('title') or data['type']}", ident)
        return
    lines = content.rstrip().count("\n") + 1
    if lines <= SHORT_CODE_LINES and pdf.will_page_break(lines * 4.2 + 6):
        pdf.add_page()
    pdf.set_font("Mono", "", 8)
    pdf.set_fill_color(*pdf.theme.rgb("surface"))
    pdf.set_text_color(*pdf.theme.rgb("ink"))
    pdf.multi_cell(0, 4.2, content.rstrip(), fill=True, padding=3, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


# draws box-drawing text while keeping its characters aligned
def add_text_art(pdf: FlowPages, content: str):
    lines = content.strip("\n").splitlines()
    pdf.set_font("Mono", "", 10)
    widest = max(pdf.get_string_width(line) for line in lines) or 1
    size = max(5.0, min(9.0, 10 * (pdf.area - 8) / widest))
    pdf.set_font("Mono", "", size)
    step = size * 0.3528 * 1.18
    width, height = max(pdf.get_string_width(line) for line in lines), step * len(lines)
    if pdf.will_page_break(height + 8):
        pdf.add_page()
    left, top = pdf.l_margin + (pdf.area - width) / 2, pdf.get_y() + 2
    pdf.set_text_color(*pdf.theme.rgb("ink"))
    for number, line in enumerate(lines):
        pdf.set_xy(left, top + number * step)
        pdf.cell(width, step, line)
    pdf.set_xy(pdf.l_margin, top + height + 4)


# renders a diagram or falls back to a readable list of steps
def add_diagram(pdf: FlowPages, source: str, ident=""):
    target = pdf.numbers.get(ident)
    lines = source.strip().splitlines()
    titled = any(line.strip().startswith(("title ", "pie title ")) for line in lines)
    title = diagram_title(source)
    source = "\n".join("pie" if line.strip().startswith("pie title ") else line for line in lines
                       if not line.strip().startswith("title "))
    path = render_diagram(source, pdf.theme)
    if not path:
        logger.warning("Diagram shown as a list instead")
        for line in diagram_as_text(source):
            add_list_item(pdf, line, [{"ordered": False, "number": 1}])
        return
    with Image.open(path) as picture:
        natural, ratio = picture.width / ZOOM * pdf.area / CANVAS_WIDTH, picture.height / picture.width
    direction = re.match(r"\s*(flowchart|graph)\s+(TB|TD|BT)\b", source)
    if direction and ratio > 1.4:
        taller = render_diagram(source[:direction.start(2)] + "LR" + source[direction.end(2):], pdf.theme)
        if taller:
            path = taller
            with Image.open(path) as picture:
                natural, ratio = picture.width / ZOOM * pdf.area / CANVAS_WIDTH, picture.height / picture.width
    width = min(pdf.area, max(natural, pdf.area * 0.6))
    height = min(width * ratio, pdf.h * 0.4)
    width = height / ratio
    width, height = room_for(pdf, width, height, 12)
    if pdf.will_page_break(height + 12):
        pdf.add_page()
    pdf.mark_target(ident)
    pdf.image(str(path), x=pdf.l_margin + (pdf.area - width) / 2, w=width, h=height, alt_text=f"Diagram: {title}")
    pdf.ln(1.5)
    if target:
        add_caption(pdf, caption_of(target))
    elif titled:
        pdf.figure_count += 1
        pdf.set_font("Brand", "I", BODY_SIZE * pdf.scale * 0.85)
        pdf.set_text_color(*pdf.theme.rgb("muted"))
        pdf.multi_cell(pdf.area, BODY_SIZE * pdf.scale * 0.45, f"Figure {pdf.figure_count}. {escaped(title)}", align="C",
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


# turns infographic labels and descriptions into a readable list
def add_infographic_as_list(pdf: FlowPages, syntax: str):
    items, current = [], None
    for line in syntax.splitlines():
        stripped = line.strip()
        if stripped.startswith("- label "):
            current = [stripped[8:], ""]
            items.append(current)
        elif stripped.startswith("desc ") and current:
            current[1] = stripped[5:]
        elif stripped.startswith("title ") and not items:
            add_heading(pdf, stripped[6:], 3)
    for label, description in items:
        add_list_item(pdf, f"**{label}**" + (f" — {description}" if description else ""), [{"ordered": False, "number": 1}])
