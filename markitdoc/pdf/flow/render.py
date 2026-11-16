import logging
import re

from fpdf.enums import XPos, YPos

from markitdoc.markup.elements import (
    LIST_SCHEMES,
    PARAGRAPH_ALIGNMENTS,
    TABLE_STYLES,
    closing_index,
    column_alignments,
    element_settings,
    only_display_maths,
    settings_from,
    without_display_maths,
)
from markitdoc.markup.inline import ANCHOR, inline_runs, parser
from markitdoc.pdf.flow.pages import BODY_SIZE, FlowPages, measured, place_notes, probe_of, top_height
from markitdoc.pdf.flow.tables import add_table, table_rows
from markitdoc.pdf.flow.text import (
    add_callout,
    add_equation,
    add_figure,
    add_heading,
    add_list_item,
    add_notes,
    add_paragraph,
    draw_runs,
    needs_runs,
)
from markitdoc.pdf.flow.visuals import add_fence
from markitdoc.pdf.pages import escaped, inline_markup
from markitdoc.utils.helpers import lifted

logger = logging.getLogger(__name__)
PAGE_BREAK_MARKER = "+++"
PLAIN_STYLE = "plain"


INDENT_STEP = 8
SOFT_BREAK_SHARE = 0.35


# parses and renders markdown into flowing PDF pages
def render_flow(pdf: FlowPages, markdown: str):
    render_tokens(pdf, parser.parse(markdown))


# renders markdown tokens into the current output format
def render_tokens(pdf: FlowPages, tokens):
    index, list_stack, notes, indent, pending = 0, [], [], 0, ""
    note_texts, placed = {}, set()
    if pdf.notes_at_page_bottom:
        for position, token in enumerate(tokens):
            if token.type == "footnote_open":
                end = closing_index(tokens, position, "footnote_open", "footnote_close")
                note_texts[token.meta["id"]] = " ".join(inline_markup(t, pdf.targets) for t in tokens[position:end] if t.type == "inline")
    while index < len(tokens):
        token = tokens[index]
        if pdf.back_to_portrait and token.level == 0 and token.type.endswith("_open"):
            pdf.back_to_portrait = False
            pdf.add_page(orientation="P")
        if token.type == "list_item_open":
            list_stack[-1]["fresh"] = True
        if token.type == "footnote_block_open":
            end = closing_index(tokens, index, "footnote_block_open", "footnote_block_close")
            notes = [inline_markup(t, pdf.targets) for t in tokens[index:end] if t.type == "inline"]
            index = end + 1
            continue
        if token.type.startswith("container_") and token.type.endswith("_open"):
            kind = token.type[len("container_"):-len("_open")]
            end = closing_index(tokens, index, token.type, f"container_{kind}_close")
            add_container(pdf, kind, token.info, tokens[index + 1:end])
            index = end + 1
            continue
        if token.type == "heading_open":
            level = int(token.tag[1])
            target = ANCHOR.search(tokens[index + 1].content)
            text = ANCHOR.sub("", inline_markup(tokens[index + 1], pdf.targets))
            add_heading(pdf, text, level, target.group(1) if target else None, opening_height(pdf, tokens, index + 3))
            index += 3
            continue
        if token.type == "paragraph_open":
            inline, equations = without_display_maths(tokens[index + 1])
            picture = next((child for child in inline.children or [] if child.type == "image"), None)
            text = inline_markup(inline, pdf.targets)
            settings_line = re.search(r"\n?\{([^{}]*)\}\s*$", inline.content)
            style = settings_from(settings_line.group(1)).get("class", "") if settings_line else ""
            if settings_line:
                text = re.sub(r"\s*\{[^{}]*\}\s*$", "", text)
            if not text and picture is None:
                for equation in equations:
                    add_equation(pdf, equation)
                pending = style if not equations else pending
                index += 3
                continue
            if text.startswith("Table:") and not list_stack:
                pdf.table_count += 1
                caption = f"__Table {pdf.table_count}. {text[6:].strip()}__"
                if index + 3 < len(tokens) and tokens[index + 3].type == "table_open":
                    pdf.pending_caption = caption
                    index += 3
                    continue
                if pdf.will_page_break(8 * pdf.scale + opening_height(pdf, tokens, index + 3)):
                    pdf.add_page()
                add_paragraph(pdf, caption, after=1.5)
                index += 3
                continue
            if picture is not None:
                add_figure(pdf, picture.content or str(picture.attrs.get("alt", "")))
            elif only_display_maths(inline):
                add_equation(pdf, next(child.content for child in inline.children if child.type == "math_inline_double"))
            elif needs_runs(inline_runs(inline, pdf.targets)) and not list_stack:
                place_notes(pdf, inline, note_texts, placed)
                draw_runs(pdf, inline_runs(inline, pdf.targets), PARAGRAPH_ALIGNMENTS.get(style, "L"),
                          indent + (INDENT_STEP if "indent" in style else 0))
            elif text == PAGE_BREAK_MARKER:
                if pdf.page_break_trigger - pdf.get_y() < pdf.eph * SOFT_BREAK_SHARE:
                    pdf.add_page()
                else:
                    logger.info("Page break marker ignored: %.0f%% of the page is still free", 100 * (pdf.page_break_trigger - pdf.get_y()) / pdf.eph)
            elif list_stack and not list_stack[-1].get("fresh"):
                add_paragraph(pdf, text, "L", 5 * len(list_stack) + 2, after=1)
            elif list_stack:
                list_stack[-1]["fresh"] = False
                place_notes(pdf, inline, note_texts, placed)
                add_list_item(pdf, text, list_stack, inline_runs(inline, pdf.targets))
            else:
                place_notes(pdf, inline, note_texts, placed)
                add_paragraph(pdf, text, PARAGRAPH_ALIGNMENTS.get(style, "L"), indent + (INDENT_STEP if "indent" in style else 0),
                              lead="lead" in style)
            for equation in equations:
                add_equation(pdf, equation)
            index += 3
            continue
        if token.type in ("bullet_list_open", "ordered_list_open"):
            scheme = pending if pending in LIST_SCHEMES else (list_stack[-1]["scheme"] if list_stack and list_stack[-1]["scheme"] == "legal" else "")
            list_stack.append({"ordered": token.type == "ordered_list_open", "number": int(token.attrs.get("start", 1) or 1),
                               "scheme": scheme})
            pending = ""
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            list_stack.pop()
            pdf.ln(1.5)
        elif token.type == "dt_open":
            add_paragraph(pdf, f"**{inline_markup(tokens[index + 1], pdf.targets)}**", "L", indent, after=0.5)
            index = closing_index(tokens, index, "dt_open", "dt_close") + 1
            continue
        elif token.type == "dd_open":
            indent += INDENT_STEP
        elif token.type == "dd_close":
            indent -= INDENT_STEP
        elif token.type == "blockquote_open":
            end = closing_index(tokens, index, "blockquote_open", "blockquote_close")
            add_callout(pdf, " ".join(inline_markup(t, pdf.targets) for t in tokens[index:end] if t.type == "inline"))
            index = end + 1
            continue
        elif token.type == "table_open":
            end = closing_index(tokens, index, "table_open", "table_close")
            cell_roles = []
            rows, settings = table_rows(tokens[index:end], pdf.targets, cell_roles), element_settings(tokens, end + 1)
            if settings.get("class") not in TABLE_STYLES:
                settings = {}
            skip = 3 if settings else 0
            last = rows[-1] if len(rows) > 1 else []
            if last and last[0].startswith("{") and last[0].endswith("}") and not any(last[1:]):
                settings, rows = settings_from(last[0][1:-1]), rows[:-1]
            add_table(pdf, rows, settings.get("class"), column_alignments(tokens[index:end]), cell_roles)
            index = end + 1 + skip
            continue
        elif token.type == "fence":
            add_fence(pdf, token.info.strip(), token.content)
        elif token.type == "math_block":
            add_equation(pdf, token.content)
        elif token.type == "hr":
            pdf.set_draw_color(*pdf.theme.rgb("rule"))
            pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
            pdf.ln(5)
        index += 1
    remaining = [(number, note) for number, note in enumerate(notes, 1) if number - 1 not in placed]
    if remaining:
        add_notes(pdf, remaining)


# measures the page count and final-page fill for flowing content
def flow_tail(pdf: FlowPages, markdown: str, spacing: float):
    probe = probe_of(pdf, pdf.t_margin)
    probe.spacing = spacing
    render_flow(probe, markdown)
    return probe.page_no(), (probe.get_y() - probe.t_margin) / (probe.page_break_trigger - probe.t_margin)


# tightens text spacing when it avoids a nearly empty final page
def fitted_spacing(pdf: FlowPages, markdown: str):
    pages, tail = flow_tail(pdf, markdown, 1.0)
    if pages < 2 or tail > 0.2:
        return 1.0
    for spacing in (0.95, 0.9):
        if flow_tail(pdf, markdown, spacing)[0] < pages:
            logger.info("Tightened a text section to %.0f%% spacing to avoid a near-empty last page", spacing * 100)
            return spacing
    return 1.0


# renders a columns or box container in flowing PDF content
def add_container(pdf: FlowPages, kind: str, info: str, inner):
    if kind == "columns":
        add_columns(pdf, inner)
        return
    title = (re.search(r'title="([^"]*)"', info) or re.search(r"title=(\S+)", info) or [None, ""])[1].rstrip("}")
    full, pad = pdf.area, 5
    width = full if kind == "box" else full * 0.5
    left = pdf.l_margin + full - width
    margins = (pdf.l_margin, pdf.r_margin)

    def fill(target):
        target.narrow = True
        target.set_left_margin(left + pad + 2)
        target.set_right_margin(target.w - left - width + pad)
        target.set_xy(target.l_margin, target.get_y() + pad)
        if title:
            target.set_font("Head", "B", BODY_SIZE * target.scale)
            target.set_text_color(*target.theme.rgb("ink"))
            target.multi_cell(target.area, BODY_SIZE * target.scale * 0.55, escaped(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            target.ln(1.5)
        render_tokens(target, inner)
        target.narrow = False

    height, overflowed = measured(pdf, fill)
    height += pad - 2
    if overflowed and height < pdf.eph * 0.8:
        pdf.add_page()
    top = pdf.get_y() + 1
    if top + height <= pdf.page_break_trigger:
        pdf.set_fill_color(*lifted(pdf.theme.rgb("surface"), 0.1))
        pdf.rect(left, top, width, height, "F")
        pdf.bar(left, top, 1.4, height, role="mood")
    pdf.set_y(top)
    fill(pdf)
    pdf.set_left_margin(margins[0])
    pdf.set_right_margin(margins[1])
    pdf.set_xy(margins[0], max(pdf.get_y(), top + height if pdf.get_y() >= top else pdf.get_y()) + 4)


# divides container content into two groups using headings or top-level blocks
def column_groups(inner):
    starts = [position for position, token in enumerate(inner) if token.type == "heading_open"]
    if len(starts) < 2:
        blocks = [position for position, token in enumerate(inner) if token.level == 0 and token.type.endswith("_open")]
        middle = blocks[len(blocks) // 2] if len(blocks) > 1 else len(inner)
        return [inner[:middle], inner[middle:]]
    half = starts[len(starts) // 2]
    return [inner[:half], inner[half:]]


# adds columns to the PDF
def add_columns(pdf: FlowPages, inner, gutter=8):
    margins, full = (pdf.l_margin, pdf.r_margin), pdf.area
    width = (full - gutter) / 2
    groups = column_groups(inner)

    def draw(target, group, column, top):
        target.narrow = True
        target.set_left_margin(margins[0] + column * (width + gutter))
        target.set_right_margin(target.w - target.l_margin - width)
        target.set_xy(target.l_margin, top)
        render_tokens(target, group)
        target.narrow = False
        return target.get_y()

    heights = [measured(pdf, lambda probe, group=group, column=column: draw(probe, group, column, probe.get_y()))
               for column, group in enumerate(groups)]
    height, overflowed = max(height for height, _ in heights), any(broke for _, broke in heights)
    pdf.set_left_margin(margins[0])
    pdf.set_right_margin(margins[1])
    if overflowed and height > pdf.eph * 0.9:
        logger.info("Columns taller than a page: shown as one column")
        render_tokens(pdf, inner)
        return
    if overflowed:
        pdf.add_page()
    top = pdf.get_y()
    bottom = max(draw(pdf, group, column, top) for column, group in enumerate(groups))
    pdf.set_left_margin(margins[0])
    pdf.set_right_margin(margins[1])
    pdf.set_xy(margins[0], bottom + 2)


# measures the height needed for opening
def opening_height(pdf: FlowPages, tokens, position):
    if pdf.measuring or position >= len(tokens):
        return 0
    token = tokens[position]
    if token.type == "paragraph_open" and tokens[position + 1].content.startswith("Table:"):
        return 8 * pdf.scale + opening_height(pdf, tokens, position + 3)
    if token.type == "fence" and token.info.strip() in ("mermaid", "chart", "infographic"):
        return pdf.eph * 0.25
    if token.type == "table_open":
        rows = table_rows(tokens[position:closing_index(tokens, position, "table_open", "table_close")], pdf.targets, [])
        return top_height(pdf, lambda probe: add_table(probe, rows[:4]))
    if token.type.startswith("container_") and token.type.endswith("_open"):
        end = closing_index(tokens, position, token.type, token.type[:-5] + "_close")
        return top_height(pdf, lambda probe: render_tokens(probe, tokens[position:end + 1]))
    return 0


# draws the table of contents from the PDF outline
def render_toc(pdf: FlowPages, outline):
    pdf.set_xy(pdf.l_margin, 24)
    pdf.set_font("Head", "B", 18)
    pdf.set_text_color(*pdf.theme.rgb("ink"))
    pdf.cell(0, 12, "Contents", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    for section in outline:
        if section.level > 1:
            continue
        pdf.set_font("Brand", "B" if section.level == 0 else "", 10 if section.level == 0 else 9.5)
        pdf.set_text_color(*pdf.theme.rgb("ink" if section.level == 0 else "body"))
        indent = 6 * section.level
        pdf.set_x(pdf.l_margin + indent)
        name = section.name[:90]
        leader = " ." * max(0, int((pdf.area - indent - 16 - pdf.get_string_width(name)) / pdf.get_string_width(" .")))
        pdf.cell(pdf.area - indent - 14, 6.5, name + leader, link=pdf.add_link(page=section.page_number))
        pdf.cell(14, 6.5, str(section.page_number), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
