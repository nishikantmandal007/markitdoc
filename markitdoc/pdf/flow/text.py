import io
import logging
from dataclasses import replace

from fpdf.enums import MethodReturnValue, XPos, YPos

from markitdoc.markup.elements import BULLET_MARKERS, CALLOUT_KINDS, LIST_SCHEMES, NUMBERING_SCHEMES
from markitdoc.markup.inline import SUPERSCRIPT_DIGITS, inline_maths
from markitdoc.pdf.flow.pages import (
    BODY_SIZE,
    HIGHLIGHT_LINK,
    LINE_MM,
    LINE_RATIO,
    FlowPages,
    can_hyphenate,
    hanging_note,
    hyphenated,
)
from markitdoc.pdf.pages import escaped
from markitdoc.themes.theme_constants import SMALL_CAPS_SCALE
from markitdoc.visuals.equations import equation_drawing, mathtext_ready, svg_size
from markitdoc.visuals.icons import strip_icon
from markitdoc.visuals.photo_fit import fitted_image

logger = logging.getLogger(__name__)

HEADING_SIZES = {1: 24, 2: 14.5, 3: 12, 4: 10.5}
HEADING_ABOVE, HEADING_BELOW, PARAGRAPH_AFTER = 7, 2.5, 3
TEXT_WIDTH = 160
KEEP_WITH_NEXT = 28
FIGURE_RATIO = 3 / 2
CODE_SCALE = 0.9


# draws an equation in the PDF or falls back to readable TeX text
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
    pdf.image(io.BytesIO(svg), x=pdf.l_margin + (min(TEXT_WIDTH, pdf.area) - width) / 2, w=width, h=height, alt_text=tex)
    pdf.ln(3)


# checks whether text runs need styled rendering, a look meaning the document uses language v2 styles
def needs_runs(runs, look=None):
    return any(run.role or run.highlight or run.script or run.code or (look is not None and (run.style or look.caps or look.tracking))
               for run in runs)


# sets font, size and colour from a look, falling back to the given defaults, and returns the size in points
def apply_look(pdf: FlowPages, look, family, size, style="", role="body", scale=1):
    size = (look.size * pdf.scale if look and look.size else size) * scale
    bold = "B" if style == "B" or (look and look.bold) else ""
    pdf.set_font(pdf.family_of(look, family), bold + ("I" if look and look.italic else ""), size)
    pdf.set_text_color(*(look.rgb if look and look.rgb else pdf.theme.rgb(role)))
    return size


# upper-cases text for caps=all and caps=small
def capped(text, look):
    return text.upper() if look and look.caps else text


# draws styled text runs with alignment and paragraph spacing
def draw_runs(pdf: FlowPages, runs, align="L", indent=0, width=None, after=PARAGRAPH_AFTER, look=None):
    if align == "J" and not can_hyphenate(pdf.lang):
        align = "L"
    width = width if width is not None else min(TEXT_WIDTH, pdf.area) - indent
    size = apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale)
    with pdf.text_columns(text_align={"C": "CENTER", "R": "RIGHT", "J": "JUSTIFY"}.get(align, "LEFT"),
                          l_margin=pdf.l_margin + indent, r_margin=pdf.w - pdf.l_margin - indent - width,
                          line_height=LINE_RATIO * pdf.spacing) as columns:
        with columns.paragraph() as paragraph:
            for run in runs:
                mine = pdf.styles.span_look(run.style, look) if look and run.style else look
                text = hyphenated(run.text, pdf.lang) if (align == "J" or pdf.narrow) and not run.code else run.text
                run_size = size * CODE_SCALE if run.code else (mine.size * pdf.scale if mine and mine.size else size)
                run_size *= SMALL_CAPS_SCALE if mine and mine.caps == "small" else 1
                pdf.set_font("Mono" if run.code else pdf.family_of(mine, "Brand"),
                             ("B" if run.bold or (mine and mine.bold) else "") + ("I" if run.italic or (mine and mine.italic) else ""), run_size)
                pdf.set_text_color(*(pdf.theme.rgb(run.role) if run.role else mine.rgb if mine and mine.rgb else pdf.theme.rgb("body")))
                pdf.set_char_spacing(mine.tracking or 0 if mine else 0)
                pdf.char_vpos = run.script or "LINE"
                paragraph.write(capped(text, mine), link=HIGHLIGHT_LINK if run.highlight else run.link or None)
    pdf.set_char_spacing(0)
    pdf.paint_highlights()
    pdf.char_vpos = "LINE"
    pdf.set_text_color(*pdf.theme.rgb("body"))
    pdf.set_x(pdf.l_margin)
    pdf.ln(after * pdf.spacing)


# draws a numbered notes section in the PDF
def add_notes(pdf: FlowPages, notes):
    pdf.ln(3)
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 40, pdf.get_y())
    pdf.ln(2.5)
    pdf.set_text_color(*pdf.theme.rgb("muted"))
    for number, note in notes:
        hanging_note(pdf, str(number).translate(SUPERSCRIPT_DIGITS), note, min(TEXT_WIDTH, pdf.area), 0.82)
        pdf.ln(0.8)


# places a matched image in the PDF with its caption and credit
def add_figure(pdf: FlowPages, query: str):
    path, caption, credit, source = pdf.flow_images.get(query) or (None, "", "", "")
    if not path:
        logger.info("Figure skipped (no image found or images are off): %s", query[:60])
        return
    width = min(TEXT_WIDTH, pdf.area)
    height = width / FIGURE_RATIO
    pdf.figure_count += 1
    if pdf.will_page_break(height + 14):
        pdf.add_page()
    picture = fitted_image(path, width, height, pdf.work_folder, (), pdf.photos, pdf.theme) if pdf.work_folder else str(path)
    pdf.image(picture, x=pdf.l_margin, w=width, h=height, alt_text=caption)
    pdf.ln(1.5)
    pdf.set_font("Brand", "I", BODY_SIZE * pdf.scale * 0.85)
    pdf.set_text_color(*pdf.theme.rgb("muted"))
    credit_link = f" · [{escaped(credit)}]({source})" if credit and source else ""
    pdf.multi_cell(width, BODY_SIZE * pdf.scale * 0.45, f"Figure {pdf.figure_count}. {escaped(caption)}{credit_link}", markdown=True, align="L",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


# draws a section heading and tracks its outline level
def add_heading(pdf: FlowPages, text: str, level: int, target=None, following=0, look=None):
    plain_text = text.replace("**", "").replace("__", "")
    if pdf.numbering and 2 <= level <= 4:
        pdf.headings[level - 1] += 1
        pdf.headings[level:] = [0] * (4 - level)
        plain_text = ".".join(str(number) for number in pdf.headings[1:level]) + "  " + plain_text
    size = (16 if pdf.plain and level == 1 else HEADING_SIZES.get(level, 11)) * pdf.scale
    if look and look.size:
        size = look.size * pdf.scale * (SMALL_CAPS_SCALE if look.caps == "small" else 1)
    if level == 2:
        pdf.current_section = plain_text
    if pdf.will_page_break(max(KEEP_WITH_NEXT, size * 0.5 + 8 + following)):
        pdf.add_page()
    if level == 2 and pdf.styles:
        pdf.page_section.setdefault(pdf.page_no(), plain_text)
    if level <= 3:
        pdf.start_section(plain_text, level=level - 1, strict=False)
    if target and target in pdf.targets:
        pdf.set_link(name=target, page=pdf.page_no(), y=pdf.get_y())
    pdf.ln(HEADING_ABOVE - PARAGRAPH_AFTER)
    bold = look.bold is not False if look else True
    pdf.set_font(pdf.family_of(look, "Head" if level <= 3 else "Brand"), ("B" if bold else "") + ("I" if look and look.italic else ""), size)
    pdf.set_text_color(*(look.rgb if look and look.rgb else pdf.theme.rgb("ink")))
    pdf.set_char_spacing(look.tracking or 0 if look else 0)
    pdf.multi_cell(min(TEXT_WIDTH, pdf.area), size * 0.42, capped(plain_text, look), align=look.align if look and look.align else "L",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_char_spacing(0)
    pdf.ln(HEADING_BELOW)


# draws a paragraph with the requested alignment and leading
def add_paragraph(pdf: FlowPages, text: str, align="L", indent=0, lead=False, after=PARAGRAPH_AFTER, following=0, look=None):
    if align == "J" and not can_hyphenate(pdf.lang):
        align = "L"
    if align == "J" or pdf.narrow:
        text = hyphenated(text, pdf.lang)
    size = apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale, role="ink" if lead else "body", scale=1.2 if lead else 1)
    width, line_height = min(TEXT_WIDTH, pdf.area) - indent, size * LINE_MM * pdf.spacing
    lines = len(pdf.multi_cell(width, line_height, text, markdown=True, dry_run=True, output=MethodReturnValue.LINES))
    if following and lines <= 2 and pdf.will_page_break(lines * line_height + after + following):
        pdf.add_page()
    room = int((pdf.page_break_trigger - pdf.get_y()) // line_height)
    if lines >= 2 and (room < 2 or (lines - room == 1)) and room < lines:
        pdf.add_page()
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(min(TEXT_WIDTH, pdf.area) - indent, line_height, text, markdown=True, align=align,
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(after * pdf.spacing)


# draws a numbered or bulleted list item at its nesting level
def add_list_item(pdf: FlowPages, text: str, list_stack, runs=(), look=None):
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
        scheme = LIST_SCHEMES.get(current["scheme"]) or NUMBERING_SCHEMES[depth % 3]
        marker = f"{scheme(current['number'])}."
    else:
        marker = BULLET_MARKERS[depth % 3]
    current["number"] += 1
    indent = 5 * len(list_stack)
    pdf.set_font("Brand", "B" if current["ordered"] else "", (BODY_SIZE * pdf.scale))
    pdf.set_text_color(*pdf.theme.rgb("ink" if pdf.plain else "mood"))
    pdf.set_x(pdf.l_margin + indent - 4)
    if marker in ("☐", "☑"):
        pdf.set_font("Symbols", "", (BODY_SIZE * pdf.scale))
    pdf.cell(6, (BODY_SIZE * pdf.scale) * 0.5, marker)
    size = apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale)
    if runs and needs_runs(runs, look):
        if runs[0].text.startswith(("☐ ", "☑ ")):
            runs = [replace(runs[0], text=runs[0].text[2:]), *runs[1:]]
        pdf.set_y(pdf.get_y())
        draw_runs(pdf, runs, look.align if look and look.align else "L", indent + 2, min(TEXT_WIDTH, pdf.area) - indent - 2, after=1, look=look)
        return
    pdf.set_x(pdf.l_margin + indent + 2)
    pdf.multi_cell(min(TEXT_WIDTH, pdf.area) - indent - 2, size * LINE_MM * pdf.spacing, text, markdown=True,
                   align=look.align if look and look.align else "L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1 * pdf.spacing)


# draws a colored callout around the paragraph text
def add_callout(pdf: FlowPages, text: str, look=None):
    kind = next((name for name in CALLOUT_KINDS if text.startswith(f"**{name}:**")), None)
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
        pdf.write_at(label_x, top + 3, min(TEXT_WIDTH, pdf.area) - (label_x - pdf.l_margin), label, 10.5, "B", line_height=1.4, rich=True)
        pdf.set_xy(pdf.l_margin, max(pdf.get_y(), top + 22) + 5)
        return
    pdf.ln(1)
    pdf.set_fill_color(*(pdf.theme.rgb("surface")))
    size = apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale, role="ink")
    align = look.align if look and look.align else "L"
    label = f"**{kind.upper()}**   " if kind else ""
    lines = pdf.multi_cell(pdf.area - 10, size * LINE_MM, label + body, markdown=True, dry_run=True, output=MethodReturnValue.LINES)
    if pdf.will_page_break(len(lines) * size * LINE_MM + 8):
        pdf.add_page()
    top, page = pdf.get_y(), pdf.page_no()
    pdf.multi_cell(0, size * LINE_MM, label + body, markdown=True, fill=True, padding=(3, 4, 3, 6), align=align,
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if pdf.page_no() == page:
        pdf.set_fill_color(*pdf.theme.rgb(role))
        pdf.rect(pdf.l_margin, top, 1.4, pdf.get_y() - top, "F")
    pdf.ln(3)
