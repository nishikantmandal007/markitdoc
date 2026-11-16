import logging
import io
from dataclasses import replace
from fpdf.enums import MethodReturnValue, XPos, YPos

from markitdoc.markup.elements import bullet_markers, callout_kinds, list_schemes, numbering_schemes
from markitdoc.markup.inline import inline_maths, superscript_digits
from markitdoc.pdf.flow_pages import FlowPages, body_size, can_hyphenate, hanging_note, highlight_link, hyphenated
from markitdoc.pdf.pages import escaped
from markitdoc.visuals.equations import equation_drawing, mathtext_ready, svg_size
from markitdoc.visuals.icons import strip_icon
from markitdoc.visuals.photos import fitted_image

logger = logging.getLogger(__name__)

heading_sizes = {1: 24, 2: 17, 3: 13, 4: 11}
text_width = 160
keep_with_next = 28
figure_ratio = 3 / 2


def add_equation(pdf: FlowPages, tex: str):
    tex = mathtext_ready(tex)
    try:
        svg = equation_drawing(tex, "#" + pdf.theme.colors["ink"].lstrip("#"))
    except ValueError as error:
        logger.warning("Equation shown as text (unsupported TeX): %s", str(error).splitlines()[0][:80])
        add_paragraph(pdf, escaped(inline_maths(tex)).replace("\u0001", "**").replace("\u0002", "**"), "C")
        return
    width, height = svg_size(svg)
    scale = min(1.0, pdf.area * 0.9 / width)
    width, height = width * scale, height * scale
    if pdf.will_page_break(height + 6):
        pdf.add_page()
    pdf.ln(2)
    pdf.image(io.BytesIO(svg), x=pdf.l_margin + (min(text_width, pdf.area) - width) / 2, w=width, h=height, alt_text=tex)
    pdf.ln(3)


def needs_runs(runs):
    return any(run.role or run.highlight or run.script for run in runs)


def draw_runs(pdf: FlowPages, runs, align="L", indent=0, width=None, after=2.5):
    if align == "J" and not can_hyphenate(pdf.lang):
        align = "L"
    size = body_size * pdf.scale
    width = width if width is not None else min(text_width, pdf.area) - indent
    pdf.set_font("Brand", "", size)
    with pdf.text_columns(text_align={"C": "CENTER", "R": "RIGHT", "J": "JUSTIFY"}.get(align, "LEFT"),
                          l_margin=pdf.l_margin + indent, r_margin=pdf.w - pdf.l_margin - indent - width,
                          line_height=0.52 / 0.3528 * pdf.spacing) as columns:
        with columns.paragraph() as paragraph:
            for run in runs:
                text = hyphenated(run.text, pdf.lang) if align == "J" or pdf.narrow else run.text
                pdf.set_font("Brand", ("B" if run.bold else "") + ("I" if run.italic else ""), size)
                pdf.set_text_color(*pdf.theme.rgb(run.role or "body"))
                pdf.char_vpos = run.script or "LINE"
                paragraph.write(text, link=highlight_link if run.highlight else run.link or None)
    pdf.paint_highlights()
    pdf.char_vpos = "LINE"
    pdf.set_text_color(*pdf.theme.rgb("body"))
    pdf.set_x(pdf.l_margin)
    pdf.ln(after * pdf.spacing)


def add_notes(pdf: FlowPages, notes):
    pdf.ln(3)
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 40, pdf.get_y())
    pdf.ln(2.5)
    pdf.set_text_color(*pdf.theme.rgb("muted"))
    for number, note in notes:
        hanging_note(pdf, str(number).translate(superscript_digits), note, min(text_width, pdf.area), 0.82)
        pdf.ln(0.8)


def add_figure(pdf: FlowPages, query: str):
    path, caption, credit, source = pdf.flow_images.get(query) or (None, "", "", "")
    if not path:
        logger.info("Figure skipped (no image found or images are off): %s", query[:60])
        return
    width = min(text_width, pdf.area)
    height = width / figure_ratio
    pdf.figure_count += 1
    if pdf.will_page_break(height + 14):
        pdf.add_page()
    picture = fitted_image(path, width, height, pdf.work_folder, (), pdf.photos, pdf.theme) if pdf.work_folder else str(path)
    pdf.image(picture, x=pdf.l_margin, w=width, h=height, alt_text=caption)
    pdf.ln(1.5)
    pdf.set_font("Brand", "I", body_size * pdf.scale * 0.85)
    pdf.set_text_color(*pdf.theme.rgb("muted"))
    credit_link = f" · [{escaped(credit)}]({source})" if credit and source else ""
    pdf.multi_cell(width, body_size * pdf.scale * 0.45, f"Figure {pdf.figure_count}. {escaped(caption)}{credit_link}", markdown=True, align="L",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


def add_heading(pdf: FlowPages, text: str, level: int, target=None, following=0):
    plain_text = text.replace("**", "").replace("__", "")
    if pdf.numbering and 2 <= level <= 4:
        pdf.headings[level - 1] += 1
        pdf.headings[level:] = [0] * (4 - level)
        plain_text = ".".join(str(number) for number in pdf.headings[1:level]) + "  " + plain_text
    size = (16 if pdf.plain and level == 1 else heading_sizes.get(level, 11)) * pdf.scale
    if level == 2:
        pdf.current_section = plain_text
    if pdf.will_page_break(max(keep_with_next, size * 0.5 + 8 + following)):
        pdf.add_page()
    if level <= 3:
        pdf.start_section(plain_text, level=level - 1, strict=False)
    if target and target in pdf.targets:
        pdf.set_link(name=target, page=pdf.page_no(), y=pdf.get_y())
    pdf.ln(4 if level > 1 else 2)
    pdf.set_font("Head" if level <= 3 else "Brand", "B", size)
    pdf.set_text_color(*pdf.theme.rgb("ink"))
    pdf.multi_cell(min(text_width, pdf.area), size * 0.42, plain_text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if level == 2 and not pdf.plain:
        pdf.set_fill_color(*pdf.theme.rgb("mood"))
        pdf.rect(pdf.l_margin, pdf.get_y() + 1, 14, 0.9, "F")
        pdf.ln(4)
    else:
        pdf.ln(2)


def add_paragraph(pdf: FlowPages, text: str, align="L", indent=0, lead=False, after=2.5):
    if align == "J" and not can_hyphenate(pdf.lang):
        align = "L"
    if align == "J" or pdf.narrow:
        text = hyphenated(text, pdf.lang)
    size = body_size * pdf.scale * (1.2 if lead else 1)
    pdf.set_font("Brand", "", size)
    pdf.set_text_color(*pdf.theme.rgb("ink" if lead else "body"))
    width, line_height = min(text_width, pdf.area) - indent, size * 0.52 * pdf.spacing
    lines = len(pdf.multi_cell(width, line_height, text, markdown=True, dry_run=True, output=MethodReturnValue.LINES))
    room = int((pdf.page_break_trigger - pdf.get_y()) // line_height)
    if lines >= 2 and (room < 2 or (lines - room == 1)) and room < lines:
        pdf.add_page()
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(min(text_width, pdf.area) - indent, line_height, text, markdown=True, align=align,
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(after * pdf.spacing)


def add_list_item(pdf: FlowPages, text: str, list_stack, runs=()):
    current, depth = list_stack[-1], len(list_stack) - 1
    icon, text = strip_icon(text)
    if icon and runs:
        runs = [replace(runs[0], text=strip_icon(runs[0].text)[1]), *runs[1:]]
    if text.startswith(("☐ ", "☑ ")):
        marker, text = text[0], text[2:]
    elif current["ordered"] and current["scheme"] == "legal":
        parents = [str(level["number"] - 1) for level in list_stack[:-1] if level["ordered"]]
        marker = ".".join([*parents, str(current["number"])])
    elif current["ordered"]:
        scheme = list_schemes.get(current["scheme"]) or numbering_schemes[depth % 3]
        marker = f"{scheme(current['number'])}."
    else:
        marker = bullet_markers[depth % 3]
    current["number"] += 1
    indent = 5 * len(list_stack)
    pdf.set_font("Brand", "B" if current["ordered"] else "", (body_size * pdf.scale))
    pdf.set_text_color(*pdf.theme.rgb("ink" if pdf.plain else "mood"))
    pdf.set_x(pdf.l_margin + indent - 4)
    if marker in ("☐", "☑"):
        pdf.set_font("Symbols", "", (body_size * pdf.scale))
    pdf.cell(6, (body_size * pdf.scale) * 0.5, marker)
    pdf.set_font("Brand", "", (body_size * pdf.scale))
    pdf.set_text_color(*pdf.theme.rgb("body"))
    if runs and needs_runs(runs):
        if runs[0].text.startswith(("☐ ", "☑ ")):
            runs = [replace(runs[0], text=runs[0].text[2:]), *runs[1:]]
        pdf.set_y(pdf.get_y())
        draw_runs(pdf, runs, "L", indent + 2, min(text_width, pdf.area) - indent - 2, after=1)
        return
    pdf.set_x(pdf.l_margin + indent + 2)
    pdf.multi_cell(min(text_width, pdf.area) - indent - 2, (body_size * pdf.scale) * 0.52 * pdf.spacing, text, markdown=True, align="L",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1 * pdf.spacing)


def add_callout(pdf: FlowPages, text: str):
    kind = next((name for name in callout_kinds if text.startswith(f"**{name}:**")), None)
    body = text.replace(f"**{kind}:**", "", 1).strip() if kind else text
    role = "danger" if kind == "Risk" else "mood"
    value, _, label = body.partition(" — ")
    if kind == "Key figure" and (not label or len(value.replace("**", "")) > 14):
        kind = "Note"
    if kind == "Key figure":
        if pdf.will_page_break(30):
            pdf.add_page()
        top = pdf.get_y() + 2
        pdf.bar(pdf.l_margin, top, 1.4, 22, role="mood")
        size = pdf.fitting_size(value.replace("**", ""), 70, 26, 16)
        pdf.write_at(pdf.l_margin + 7, top + 2, 70, value.replace("**", ""), size, "B", "mood", line_height=1.0)
        pdf.set_font("Head", "B", size)
        label_x = pdf.l_margin + 7 + pdf.get_string_width(value.replace("**", "")) + 8
        pdf.write_at(label_x, top + 3, min(text_width, pdf.area) - (label_x - pdf.l_margin), label, 10.5, "B", line_height=1.4, rich=True)
        pdf.set_xy(pdf.l_margin, max(pdf.get_y(), top + 22) + 5)
        return
    pdf.ln(1)
    pdf.set_fill_color(*(pdf.theme.rgb("surface")))
    pdf.set_font("Brand", "", (body_size * pdf.scale))
    pdf.set_text_color(*pdf.theme.rgb("ink"))
    label = f"**{kind.upper()}**   " if kind else ""
    lines = pdf.multi_cell(pdf.area - 10, (body_size * pdf.scale) * 0.52, label + body, markdown=True, dry_run=True, output=MethodReturnValue.LINES)
    if pdf.will_page_break(len(lines) * (body_size * pdf.scale) * 0.52 + 8):
        pdf.add_page()
    top, page = pdf.get_y(), pdf.page_no()
    pdf.multi_cell(0, (body_size * pdf.scale) * 0.52, label + body, markdown=True, fill=True, padding=(3, 4, 3, 6), align="L",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if pdf.page_no() == page:
        pdf.set_fill_color(*pdf.theme.rgb(role))
        pdf.rect(pdf.l_margin, top, 1.4, pdf.get_y() - top, "F")
    pdf.ln(3)
