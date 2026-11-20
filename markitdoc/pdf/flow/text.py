import io
import logging
import re
from dataclasses import replace

from fpdf.enums import Align, MethodReturnValue, XPos, YPos
from fpdf.line_break import MultiLineBreak

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
from markitdoc.themes.theme_constants import HEADING_SIZES, POINT_MM, SMALL_CAPS_SCALE
from markitdoc.visuals.equations import equation_drawing, mathtext_ready, svg_size
from markitdoc.visuals.icons import strip_icon
from markitdoc.visuals.photo_fit import fitted_image

logger = logging.getLogger(__name__)

HEADING_ABOVE, HEADING_BELOW, PARAGRAPH_AFTER = 7, 2.5, 3
TEXT_WIDTH = 160
FIGURE_RATIO = 3 / 2
CODE_SCALE = 0.9
CAP_HEIGHT, DROPCAP_GAP, DROPCAP_BASELINE, LEADER_NUMBER, WRAP_SAFETY = 0.7, 1.5, 0.75, 14, 0.97


# draws an equation in the PDF or falls back to readable TeX text
def add_equation(pdf: FlowPages, tex: str, ident=""):
    target = pdf.numbers.get(ident)
    tex = mathtext_ready(tex)
    try:
        svg = equation_drawing(tex, "#" + pdf.theme.colors["ink"].lstrip("#"))
    except ValueError as error:
        logger.warning("Equation shown as text (unsupported TeX): %s", str(error).splitlines()[0][:80])
        pdf.mark_target(ident)
        add_paragraph(pdf, escaped(inline_maths(tex)).replace("\u0001", "**").replace("\u0002", "**"), "C")
        return
    width, height = svg_size(svg)
    scale = min(1.0, pdf.area * 0.9 / width)
    width, height = width * scale, height * scale
    if pdf.will_page_break(height + 6):
        pdf.add_page()
    pdf.ln(2)
    pdf.mark_target(ident)
    top = pdf.get_y()
    pdf.image(io.BytesIO(svg), x=pdf.l_margin + (min(TEXT_WIDTH, pdf.area) - width) / 2, w=width, h=height, alt_text=tex)
    if target:
        pdf.set_font("Brand", "", BODY_SIZE * pdf.scale)
        pdf.set_text_color(*pdf.theme.rgb("body"))
        pdf.set_xy(pdf.l_margin, top + height / 2 - BODY_SIZE * pdf.scale * 0.25)
        pdf.cell(min(TEXT_WIDTH, pdf.area), BODY_SIZE * pdf.scale * 0.5, target.mark, align="R")
        pdf.set_xy(pdf.l_margin, top + height)
    pdf.ln(3)


# checks whether text runs need styled rendering, a look adding the styles a document asks for
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


# breaks a plain Markdown paragraph with the same shaping and margins used by fpdf's multicell
def paragraph_lines(pdf, text, width, align):
    text = pdf.normalize_text(text).replace("\r", "")
    fragments = (pdf._preload_bidirectional_text(text, markdown=True) if pdf.text_shaping
                 else pdf._preload_font_styles(text, markdown=True))
    breaker = MultiLineBreak(fragments, width, (pdf.c_margin, pdf.c_margin), Align.coerce(align))
    return list(iter(breaker.get_line, None))


# draws measured paragraph lines in page groups with at least two lines on either side of a break
def write_lines(pdf, lines, indent, height=None, following=0, prefix=None):
    while lines:
        heights = [height or line.height for line in lines]
        room = pdf.page_break_trigger - pdf.get_y()
        fit, used = 0, 0
        for pitch in heights:
            if used + pitch > room:
                break
            used += pitch
            fit += 1
        if 0 < fit < len(lines) and len(lines) - fit == 1:
            fit -= 1
        if (fit < min(len(lines), 2) or (len(lines) <= 3 and used + following > room)) and pdf.get_y() > pdf.t_margin + 0.01:
            if pdf.will_page_break(max(heights[0], used + following, room + 0.01)):
                pdf.add_page()
                continue
        if not pdf.auto_page_break:
            fit = len(lines)
        fit = max(1, fit)
        if prefix:
            prefix()
            prefix = None
        for line, pitch in zip(lines[:fit], heights):
            pdf.set_x(pdf.l_margin + indent)
            pdf._render_styled_text_line(line, h=pitch, border=0, new_x=XPos.LEFT, new_y=YPos.NEXT, fill=False)
        lines = lines[fit:]
        if lines:
            pdf.add_page()
    pdf.set_x(pdf.l_margin)


# draws styled text runs with alignment and paragraph spacing
def draw_runs(pdf: FlowPages, runs, align="L", indent=0, width=None, after=PARAGRAPH_AFTER, look=None, following=0, prefix=None):
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
                text = hyphenated(run.text, dict(run.style).get("lang") or pdf.lang) if (align == "J" or pdf.narrow) and not run.code else run.text
                run_size = size * CODE_SCALE if run.code else (mine.size * pdf.scale if mine and mine.size else size)
                run_size *= SMALL_CAPS_SCALE if mine and mine.caps == "small" else 1
                pdf.set_font("Mono" if run.code else pdf.family_of(mine, "Brand"),
                             ("B" if run.bold or (mine and mine.bold) else "") + ("I" if run.italic or (mine and mine.italic) else ""), run_size)
                pdf.set_text_color(*(pdf.theme.rgb(run.role) if run.role else mine.rgb if mine and mine.rgb else pdf.theme.rgb("body")))
                pdf.set_char_spacing(mine.tracking or 0 if mine else 0)
                pdf.char_vpos = run.script or "LINE"
                paragraph.write(capped(text, mine), link=HIGHLIGHT_LINK if run.highlight else run.link or None)
        lines = [wrapped.line for wrapped in columns.collect_lines()]
    write_lines(pdf, lines, indent, following=following, prefix=prefix)
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
    path, caption, credit, source, focus = pdf.flow_images.get(query) or (None, "", "", "", "")
    if not path:
        logger.info("Figure skipped (no image found or images are off): %s", query[:60])
        return
    width = min(TEXT_WIDTH, pdf.area)
    height = width / FIGURE_RATIO
    pdf.figure_count += 1
    if pdf.will_page_break(height + 14):
        pdf.add_page()
    picture = fitted_image(path, width, height, pdf.work_folder, (), pdf.photos, pdf.theme, focus) if pdf.work_folder else str(path)
    pdf.image(picture, x=pdf.l_margin, w=width, h=height, alt_text=caption)
    pdf.ln(1.5)
    size = caption_font(pdf)
    credit_link = f" · [{escaped(credit)}]({source})" if credit and source else ""
    pdf.multi_cell(width, size * 0.53, f"Figure {pdf.figure_count}. {escaped(caption)}{credit_link}", markdown=True, align="L",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)


# applies the caption rule, retaining the small italic default
def caption_font(pdf):
    look = pdf.look("caption")
    if not look or not any(source.endswith(":set.caption") for _, source in look.props.values()):
        pdf.set_font("Brand", "I", BODY_SIZE * pdf.scale * 0.85)
        pdf.set_text_color(*pdf.theme.rgb("muted"))
        return BODY_SIZE * pdf.scale * 0.85
    return apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale * 0.85, role="muted")


# draws a centred figure caption under a chart or diagram
def add_caption(pdf: FlowPages, text: str):
    size = caption_font(pdf)
    pdf.multi_cell(pdf.area, size * 0.53, escaped(text), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


# draws a section heading and tracks its outline level
def add_heading(pdf: FlowPages, text: str, level: int, target=None, following=0, look=None, numbered=True):
    plain_text = text.replace("**", "").replace("__", "")
    if pdf.numbering and numbered and 2 <= level <= 4:
        pdf.headings[level - 1] += 1
        pdf.headings[level:] = [0] * (4 - level)
        plain_text = ".".join(str(number) for number in pdf.headings[1:level]) + "  " + plain_text
    size = (16 if pdf.plain and level == 1 else HEADING_SIZES.get(level, 11)) * pdf.scale
    if look and look.size:
        size = look.size * pdf.scale * (SMALL_CAPS_SCALE if look.caps == "small" else 1)
    bold = look.bold is not False if look else True
    pdf.set_font(pdf.family_of(look, "Head" if level <= 3 else "Brand"), ("B" if bold else "") + ("I" if look and look.italic else ""), size)
    pdf.set_char_spacing(look.tracking or 0 if look else 0)
    align = look.align if look and look.align else "L"
    width = min(TEXT_WIDTH, pdf.area)
    heading = capped(plain_text, look)
    line_height = size * 0.42
    lines = pdf.multi_cell(width, line_height, heading, align=align, dry_run=True, output=MethodReturnValue.LINES)
    if level == 2:
        pdf.current_section = plain_text
    if pdf.will_page_break(len(lines) * line_height + HEADING_ABOVE - PARAGRAPH_AFTER + HEADING_BELOW + following):
        pdf.add_page()
    if level == 2:
        pdf.page_section.setdefault(pdf.page_no(), plain_text)
    if level <= 3:
        pdf.start_section(plain_text, level=level - 1, strict=False)
    if target and target in pdf.targets:
        pdf.mark_target(target)
    pdf.ln(HEADING_ABOVE - PARAGRAPH_AFTER)
    pdf.set_text_color(*(look.rgb if look and look.rgb else pdf.theme.rgb("ink")))
    pdf.multi_cell(min(TEXT_WIDTH, pdf.area), line_height, heading, align=align,
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_char_spacing(0)
    pdf.ln(HEADING_BELOW)


# draws a paragraph with the requested alignment and leading
def add_paragraph(pdf: FlowPages, text: str, align="L", indent=0, lead=False, after=PARAGRAPH_AFTER, following=0, look=None):
    if align == "J" and not can_hyphenate(pdf.lang):
        align = "L"
    if align == "J" or pdf.narrow:
        text = hyphenated(text, pdf.lang)
    sized_lead = lead and look and look.props.get("size", ("", ""))[1].endswith(":styles.lead")
    size = apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale, role="ink" if lead else "body", scale=1.2 if lead and not sized_lead else 1)
    width, line_height = min(TEXT_WIDTH, pdf.area) - indent, size * LINE_MM * pdf.spacing
    lines = paragraph_lines(pdf, text, width, align)
    write_lines(pdf, lines, indent, line_height, following + after if following else 0)
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
    def draw_marker():
        with pdf.local_context():
            pdf.set_font("Symbols" if marker in ("☐", "☑") else "Brand",
                         "B" if current["ordered"] and marker not in ("☐", "☑") else "", BODY_SIZE * pdf.scale)
            pdf.set_text_color(*pdf.theme.rgb("ink" if pdf.plain else "mood"))
            pdf.set_x(pdf.l_margin + indent - 4)
            pdf.cell(6, BODY_SIZE * pdf.scale * 0.5, marker + " ")

    align = look.align if look and look.align else "L"
    indent += 2
    if runs and needs_runs(runs, look):
        if runs[0].text.startswith(("☐ ", "☑ ")):
            runs = [replace(runs[0], text=runs[0].text[2:]), *runs[1:]]
        draw_runs(pdf, runs, align, indent, after=1, look=look, prefix=draw_marker)
        return
    size = apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale)
    width = min(TEXT_WIDTH, pdf.area) - indent
    write_lines(pdf, paragraph_lines(pdf, text, width, align), indent, size * LINE_MM * pdf.spacing, prefix=draw_marker)
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


# the paragraph split for a drop cap of the given lines as (letter, cap size, line pitch, lines, offset, runs beside, runs below), None when too short or not starting with a letter
def dropcap_plan(pdf: FlowPages, runs, lines, look, indent):
    runs = [run for run in runs if run.text]
    if not runs or runs[0].code or runs[0].link or not runs[0].text[:1].isalpha():
        return None
    size = apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale)
    pitch = size * LINE_MM * pdf.spacing
    cap_size = ((lines - 1) * pitch + size * POINT_MM * CAP_HEIGHT) / (POINT_MM * CAP_HEIGHT)
    pdf.set_font("Head", "B", cap_size)
    letter = runs[0].text[0]
    offset = pdf.get_string_width(letter) + DROPCAP_GAP
    beside = min(TEXT_WIDTH, pdf.area) - indent - offset
    runs = [replace(runs[0], text=runs[0].text[1:]), *runs[1:]]
    used, count = 0.0, 1
    for number, run in enumerate(runs):
        pdf.set_font("Mono" if run.code else pdf.family_of(look, "Brand"), ("B" if run.bold else "") + ("I" if run.italic else ""), size)
        for word in re.finditer(r"\S+\s*|\s+", run.text):
            if used and used + pdf.get_string_width(word.group(0)) > beside * WRAP_SAFETY:
                count, used = count + 1, 0.0
                if count > lines:
                    return (letter, cap_size, pitch, lines, offset, [*runs[:number], replace(run, text=run.text[:word.start()].rstrip())],
                            [replace(run, text=run.text[word.start():]), *runs[number + 1:]])
            used += pdf.get_string_width(word.group(0))
    return (letter, cap_size, pitch, lines, offset, runs, []) if count == lines else None


# draws a paragraph that starts with a large initial in the heading font and accent colour, the first lines wrapped beside it
def add_dropcap(pdf: FlowPages, plan, align, indent, look):
    letter, cap_size, pitch, lines, offset, beside, below = plan
    if pdf.will_page_break((lines + (2 if below else 0)) * pitch):
        pdf.add_page()
    top = pdf.get_y()
    pdf.set_font("Head", "B", cap_size)
    pdf.set_text_color(*pdf.theme.rgb("mood"))
    pdf.text(pdf.l_margin + indent, top + (lines - 1 + DROPCAP_BASELINE) * pitch, letter)
    draw_runs(pdf, beside, align, indent + offset, min(TEXT_WIDTH, pdf.area) - indent - offset, after=0, look=look)
    pdf.set_y(max(pdf.get_y(), top + lines * pitch))
    if below:
        draw_runs(pdf, below, align, indent, look=look)
    else:
        pdf.ln(PARAGRAPH_AFTER * pdf.spacing)


# draws a list entry with its caption, dot leaders and right-aligned page number, both linked to the target
def add_leader_row(pdf: FlowPages, runs, last=False, look=None):
    name, _, number = "".join(run.text for run in runs).rpartition("\t")
    link = next((run.link for run in runs if run.link), "")
    apply_look(pdf, look, "Brand", BODY_SIZE * pdf.scale)
    name = name[:90]
    leader = " ." * max(0, int((pdf.area - LEADER_NUMBER - pdf.get_string_width(name)) / pdf.get_string_width(" .")))
    if pdf.will_page_break(6):
        pdf.add_page()
    pdf.cell(pdf.area - LEADER_NUMBER, 6, name + leader, link=link)
    pdf.cell(LEADER_NUMBER, 6, number, align="R", link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4 if last else 0.5)
