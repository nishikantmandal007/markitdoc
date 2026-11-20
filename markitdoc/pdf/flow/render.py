import logging
import re
from dataclasses import replace

from fpdf.enums import XPos, YPos

from markitdoc.markup.editorial import dropcap_lines, interrupts_opening, trimmed_runs
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
    written_image,
)
from markitdoc.markup.inline import ANCHOR, UNNUMBERED, inline_runs, parser
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.model_constants import PAGE_SWITCH
from markitdoc.pdf.flow.boxes import add_picture, draw_frame, end_float, float_check, page_extents
from markitdoc.pdf.flow.pages import BODY_SIZE, FlowPages, measured, place_notes, probe_of, top_height
from markitdoc.pdf.flow.tables import add_table, table_rows
from markitdoc.pdf.flow.text import (
    TEXT_WIDTH,
    add_callout,
    add_dropcap,
    add_equation,
    add_figure,
    add_heading,
    add_leader_row,
    add_list_item,
    add_notes,
    add_paragraph,
    draw_runs,
    dropcap_plan,
    needs_runs,
)
from markitdoc.pdf.flow.visuals import SHORT_CODE_LINES, add_fence
from markitdoc.pdf.pages import escaped, inline_markup
from markitdoc.themes.theme_constants import BORDER_SIDES, STYLE_PROPERTIES
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
    note_texts, placed, section_start = {}, set(), False
    if pdf.notes_at_page_bottom:
        for position, token in enumerate(tokens):
            if token.type == "footnote_open":
                end = closing_index(tokens, position, "footnote_open", "footnote_close")
                note_texts[token.meta["id"]] = " ".join(inline_markup(t, pdf.targets) for t in tokens[position:end] if t.type == "inline")
    while index < len(tokens):
        token = tokens[index]
        float_check(pdf, token)
        if token.type == "paragraph_open" and token.level == 0 and (switch := PAGE_SWITCH.match(tokens[index + 1].content.strip())):
            queue_switch(pdf, switch.group(1))
            pdf.back_to_portrait = False
            pdf.add_page()
            index += 3
            continue
        if pdf.back_to_portrait and token.level == 0 and token.type.endswith("_open"):
            pdf.back_to_portrait = False
            pdf.add_page(orientation="P")
        if interrupts_opening(token):
            section_start = False
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
            written = UNNUMBERED.sub("", tokens[index + 1].content)
            target = ANCHOR.search(written)
            text = ANCHOR.sub("", UNNUMBERED.sub("", inline_markup(tokens[index + 1], pdf.targets)))
            add_heading(pdf, text, level, target.group(1) if target else None, opening_height(pdf, tokens, index + 3),
                        pdf.look(f"h{min(level, 4)}"), written == tokens[index + 1].content)
            section_start = level <= 2
            index += 3
            continue
        if token.type == "paragraph_open":
            inline, equations = without_display_maths(tokens[index + 1])
            picture = next((child for child in inline.children or [] if child.type == "image"), None)
            text = inline_markup(inline, pdf.targets)
            settings_line = re.search(r"\n?\{([^{}]*)\}\s*$", inline.content)
            style = settings_from(settings_line.group(1)).get("class", "") if settings_line else ""
            block_line = re.search(r"(?<![\]*_`])\{([^{}]*)\}\s*$", inline.content)
            attributes = parse_attributes(block_line.group(1) if block_line else "")
            look = pdf.look("list" if list_stack else "paragraph.first" if section_start else "paragraph", attributes.classes, attributes.values)
            section_start = False
            lines = dropcap_lines(look)
            align = PARAGRAPH_ALIGNMENTS.get(style) or (look.align if look and look.align else "L")
            labelled = parse_attributes(settings_line.group(1)).id if settings_line else ""
            if "\t" in inline.content and not list_stack:
                add_leader_row(pdf, inline_runs(inline, pdf.targets), index + 4 >= len(tokens) or "\t" not in tokens[index + 4].content, look)
                index += 3
                continue
            if settings_line:
                text = re.sub(r"\s*\{[^{}]*\}\s*$", "", text)
            if not text and picture is None:
                for number, equation in enumerate(equations):
                    add_equation(pdf, equation, labelled if number == 0 else "")
                pending = style if not equations else pending
                index += 3
                continue
            if text.startswith("Table:") and not list_stack:
                if target := pdf.numbers.get(labelled):
                    caption = f"__{target.mark}. {text[6:].strip()}__"
                else:
                    pdf.table_count += 1
                    caption = f"__Table {pdf.table_count}. {text[6:].strip()}__"
                if index + 3 < len(tokens) and tokens[index + 3].type == "table_open":
                    pdf.pending_caption, pdf.pending_target = caption, labelled
                    index += 3
                    continue
                if pdf.will_page_break(8 * pdf.scale + opening_height(pdf, tokens, index + 3)):
                    pdf.add_page()
                pdf.mark_target(labelled)
                add_paragraph(pdf, caption, after=1.5)
                index += 3
                continue
            written = written_image(inline.content) if picture is not None else None
            framed = look is not None and picture is None and look.borders
            if labelled in pdf.numbers and pdf.numbers[labelled].kind == "reference":
                pdf.mark_target(labelled)
            if framed:
                pdf.ln(1.5)
                frame_top, frame_page = pdf.get_y(), pdf.page_no()
            if written:
                add_picture(pdf, written)
            elif picture is not None:
                add_figure(pdf, picture.content or str(picture.attrs.get("alt", "")))
            elif only_display_maths(inline):
                add_equation(pdf, next(child.content for child in inline.children if child.type == "math_inline_double"))
            elif lines and not list_stack and (plan := dropcap_plan(pdf, trimmed_runs(inline, pdf.targets, block_line), lines, look, indent)):
                place_notes(pdf, inline, note_texts, placed)
                add_dropcap(pdf, plan, align, indent, look)
            elif needs_runs(inline_runs(inline, pdf.targets), look) and not list_stack:
                place_notes(pdf, inline, note_texts, placed)
                runs = inline_runs(inline, pdf.targets)
                if look and block_line and runs:
                    runs[-1] = replace(runs[-1], text=re.sub(r"\s*\{[^{}]*\}\s*$", "", runs[-1].text))
                draw_runs(pdf, [run for run in runs if run.text], align, indent + (INDENT_STEP if "indent" in style else 0), look=look)
            elif text == PAGE_BREAK_MARKER:
                if pdf.page_break_trigger - pdf.get_y() < pdf.eph * SOFT_BREAK_SHARE:
                    pdf.add_page()
                else:
                    logger.info("Page break marker ignored: %.0f%% of the page is still free", 100 * (pdf.page_break_trigger - pdf.get_y()) / pdf.eph)
            elif list_stack and not list_stack[-1].get("fresh"):
                add_paragraph(pdf, text, "L", 5 * len(list_stack) + 2, after=1, look=look)
            elif list_stack:
                list_stack[-1]["fresh"] = False
                place_notes(pdf, inline, note_texts, placed)
                add_list_item(pdf, text, list_stack, inline_runs(inline, pdf.targets), look)
            else:
                place_notes(pdf, inline, note_texts, placed)
                add_paragraph(pdf, text, align, indent + (INDENT_STEP if "indent" in style else 0), lead="lead" in style,
                              following=opening_height(pdf, tokens, index + 3) if text.endswith(":") else 0, look=look)
            if framed and pdf.page_no() == frame_page:
                draw_frame(pdf, pdf.l_margin, min(TEXT_WIDTH, pdf.area), frame_top - 1.5, pdf.get_y() - 1.5, replace(look, fill=None))
            for number, equation in enumerate(equations):
                add_equation(pdf, equation, labelled if number == 0 else "")
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
            add_callout(pdf, " ".join(inline_markup(t, pdf.targets) for t in tokens[index:end] if t.type == "inline"), pdf.look("quote"))
            index = end + 1
            continue
        elif token.type == "table_open":
            end = closing_index(tokens, index, "table_open", "table_close")
            cell_roles, cell_monos = [], []
            rows, settings = table_rows(tokens[index:end], pdf.targets, cell_roles, cell_monos), element_settings(tokens, end + 1)
            if not (settings.get("class") in TABLE_STYLES or settings.keys() & {"columns", "precision"}):
                settings = {}
            skip = 3 if settings else 0
            last = rows[-1] if len(rows) > 1 else []
            if last and last[0].startswith("{") and last[0].endswith("}") and not any(last[1:]):
                settings, rows = settings_from(last[0][1:-1]), rows[:-1]
            after = end + 1 + skip
            if not pdf.pending_caption and after + 1 < len(tokens) and tokens[after].type == "paragraph_open":
                caption, _, attrs = tokens[after + 1].content.partition("{")
                if caption.startswith("Table:"):
                    ident = parse_attributes(attrs).id
                    target = pdf.numbers.get(ident)
                    if not target:
                        pdf.table_count += 1
                    mark = target.mark if target else f"Table {pdf.table_count}"
                    pdf.pending_caption, pdf.pending_target = f"__{mark}. {caption[6:].strip()}__", ident
                    skip += 3
            add_table(pdf, rows, settings.get("class"), column_alignments(tokens[index:end]), cell_roles, cell_monos, settings)
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
    if pdf.floating:
        end_float(pdf, True)
    remaining = [(number, note) for number, note in enumerate(notes, 1) if number - 1 not in placed]
    if remaining:
        add_notes(pdf, remaining)


# names the page master and number restart for the next page from the attributes of a +++ line
def queue_switch(pdf: FlowPages, attributes):
    values = parse_attributes(attributes).values
    pdf.next_master, pdf.restart = str(values.get("page") or pdf.master_name), values.get("numbers") == "restart"


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
    attributes = parse_attributes(info)
    if kind == "columns":
        weights, gap = pdf.styles.columns(attributes.values)
        add_columns(pdf, inner, gap, weights)
        return
    title = (re.search(r'title="([^"]*)"', info) or re.search(r"title=(\S+)", info) or [None, ""])[1].rstrip("}")
    look = pdf.look("box", attributes.classes, attributes.values) if kind == "box" else None
    if look and look.boxed():
        add_styled_box(pdf, look, title, inner)
        return
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


# renders a box with its own border, padding, fill and radius, drawing one frame for each page the box covers
def add_styled_box(pdf: FlowPages, look, title, inner):
    margins, left, pad = (pdf.l_margin, pdf.r_margin), pdf.l_margin, look.padding or 0
    width = min(pdf.area, pdf.styles.length(look.width, pdf.area) or pdf.area) if look.width else pdf.area
    inset = {side: pad + (look.borders[side][0] if side in look.borders else 0) for side in BORDER_SIDES}
    context = {key: found for key, found in look.props.items() if key in STYLE_PROPERTIES}

    def fill(target):
        before = target.narrow, target.context
        target.narrow, target.context = True, context
        target.set_left_margin(left + inset["left"])
        target.set_right_margin(target.w - left - width + inset["right"])
        target.set_xy(target.l_margin, target.get_y() + inset["top"])
        if title:
            target.set_font("Head", "B", BODY_SIZE * target.scale)
            target.set_text_color(*target.theme.rgb("ink"))
            target.multi_cell(target.area, BODY_SIZE * target.scale * 0.55, escaped(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            target.ln(1.5)
        render_tokens(target, inner)
        target.set_y(target.get_y() + inset["bottom"])
        target.narrow, target.context = before

    extents, height, overflowed = page_extents(pdf, fill)
    if overflowed and height < pdf.eph * 0.8:
        pdf.add_page()
        extents = page_extents(pdf, fill)[0]
    pending = iter(range(1, len(extents)))

    def next_frame():
        if (index := next(pending, None)) is not None:
            draw_frame(pdf, left, width, *extents[index], look, False, index == len(extents) - 1)

    draw_frame(pdf, left, width, *extents[0], look, True, len(extents) == 1)
    pdf.page_starts.append(next_frame)
    fill(pdf)
    pdf.page_starts.remove(next_frame)
    pdf.set_left_margin(margins[0])
    pdf.set_right_margin(margins[1])
    pdf.set_xy(margins[0], pdf.get_y() + 3)


# divides container content into two groups using headings or top-level blocks
def column_groups(inner):
    starts = [position for position, token in enumerate(inner) if token.type == "heading_open"]
    if len(starts) < 2:
        top = min((token.level for token in inner), default=0)
        blocks = [position for position, token in enumerate(inner) if token.level == top and token.type.endswith("_open")]
        middle = blocks[len(blocks) // 2] if len(blocks) > 1 else len(inner)
        return [inner[:middle], inner[middle:]]
    half = starts[len(starts) // 2]
    return [inner[:half], inner[half:]]


# adds columns to the PDF
def add_columns(pdf: FlowPages, inner, gutter=8, weights=(1, 1)):
    margins, full = (pdf.l_margin, pdf.r_margin), pdf.area
    widths = [(full - gutter) * weight / sum(weights) for weight in weights]
    groups = column_groups(inner)

    def draw(target, group, column, top):
        target.narrow = True
        target.set_left_margin(margins[0] + sum(widths[:column]) + column * gutter)
        target.set_right_margin(target.w - target.l_margin - widths[column])
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
    if token.type == "fence":
        lines = token.content.rstrip().count("\n") + 1
        return (lines if lines <= SHORT_CODE_LINES else 3) * 4.2 + 6
    if token.type in ("bullet_list_open", "ordered_list_open"):
        return 12
    if token.type == "paragraph_open" and any(child.type == "image" for child in tokens[position + 1].children or []):
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
    title = outline[0] if outline and outline[0].level == 0 and sum(item.level == 0 for item in outline) == 1 else None
    for section in outline:
        if section.level > 1 or section is title:
            continue
        pdf.set_font("Brand", "B" if section.level == 0 else "", 10 if section.level == 0 else 9.5)
        pdf.set_text_color(*pdf.theme.rgb("ink" if section.level == 0 else "body"))
        indent = 6 * section.level
        pdf.set_x(pdf.l_margin + indent)
        name = section.name[:90]
        leader = " ." * max(0, int((pdf.area - indent - 16 - pdf.get_string_width(name)) / pdf.get_string_width(" .")))
        pdf.cell(pdf.area - indent - 14, 6.5, name + leader, link=pdf.add_link(page=section.page_number))
        pdf.cell(14, 6.5, str(section.page_number), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
