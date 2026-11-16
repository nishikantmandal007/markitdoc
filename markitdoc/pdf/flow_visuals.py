import logging
import io
import re
from fpdf.enums import XPos, YPos
from PIL import Image

from markitdoc.markup.elements import chart_data, chart_sizes, settings_from
from markitdoc.pdf.flow_pages import FlowPages, body_size
from markitdoc.pdf.flow_text import add_heading, add_list_item
from markitdoc.pdf.pages import escaped
from markitdoc.visuals.charts import render_chart
from markitdoc.visuals.diagrams import canvas_width, diagram_as_text, diagram_title, render_diagram, zoom
from markitdoc.visuals.infographics import render_infographic

logger = logging.getLogger(__name__)

box_drawing = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬"


def room_for(pdf: FlowPages, width, height, reserve):
    room = pdf.page_break_trigger - pdf.get_y() - reserve
    if height > room >= height * 0.6:
        return width * room / height, room
    return width, height


def add_picture(pdf: FlowPages, picture, width, height, description=""):
    width, height = room_for(pdf, width, height, 6)
    if pdf.will_page_break(height + 6):
        pdf.add_page()
    pdf.image(picture, x=pdf.l_margin + (pdf.area - width) / 2, w=width, h=height, alt_text=description or None)
    pdf.ln(4)


def add_fence(pdf: FlowPages, language: str, content: str):
    settings = settings_from(language[language.find("{"):]) if "{" in language else {}
    language = language.split("{")[0].strip()
    width = (pdf.area) * chart_sizes.get(settings.get("size", "full"), 1.0)
    if language in ("", "text", "plain", "plaintext") and sum(content.count(mark) for mark in box_drawing) >= 6:
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
        add_diagram(pdf, content)
        return
    if language == "chart":
        data = chart_data(content)
        if not data:
            logger.warning("Chart skipped: invalid JSON, unknown type, no values, or a value count that differs from the labels")
        else:
            data["colors"] = ["#" + pdf.theme.colors[role].lstrip("#") for role in ("mood", "second", "muted", "primary", "success", "danger")]
            data["background"], data["font"] = "#" + pdf.theme.colors["paper"].lstrip("#"), str(pdf.theme.fonts["body"])
            try:
                image = render_chart(data, width_inches=width / 25.4, height_inches=width * 0.5 / 25.4)
            except Exception as error:
                logger.warning("Chart skipped: %s", type(error).__name__)
                return
            add_picture(pdf, io.BytesIO(image), width, width * 0.5, f"Chart: {data.get('title') or data['type']}")
        return
    pdf.set_font("Mono", "", 8)
    pdf.set_fill_color(*pdf.theme.rgb("surface"))
    pdf.set_text_color(*pdf.theme.rgb("ink"))
    pdf.multi_cell(0, 4.2, content.rstrip(), fill=True, padding=3, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


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


def add_diagram(pdf: FlowPages, source: str):
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
        natural, ratio = picture.width / zoom * pdf.area / canvas_width, picture.height / picture.width
    direction = re.match(r"\s*(flowchart|graph)\s+(TB|TD|BT)\b", source)
    if direction and ratio > 1.4:
        taller = render_diagram(source[:direction.start(2)] + "LR" + source[direction.end(2):], pdf.theme)
        if taller:
            path = taller
            with Image.open(path) as picture:
                natural, ratio = picture.width / zoom * pdf.area / canvas_width, picture.height / picture.width
    width = min(pdf.area, max(natural, pdf.area * 0.6))
    height = min(width * ratio, pdf.h * 0.4)
    width = height / ratio
    width, height = room_for(pdf, width, height, 12)
    if pdf.will_page_break(height + 12):
        pdf.add_page()
    pdf.image(str(path), x=pdf.l_margin + (pdf.area - width) / 2, w=width, h=height, alt_text=f"Diagram: {title}")
    pdf.ln(1.5)
    if titled:
        pdf.figure_count += 1
        pdf.set_font("Brand", "I", body_size * pdf.scale * 0.85)
        pdf.set_text_color(*pdf.theme.rgb("muted"))
        pdf.multi_cell(pdf.area, body_size * pdf.scale * 0.45, f"Figure {pdf.figure_count}. {escaped(title)}", align="C",
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


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
