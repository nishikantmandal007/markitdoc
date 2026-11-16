import io
import re


from fpdf.enums import TableCellFillMode, XPos, YPos
from fpdf.fonts import FontFace
from PIL import Image

import logging
from markitdoc.visuals.charts import render_chart
from markitdoc.visuals.diagrams import canvas_width, diagram_as_text, diagram_title, render_diagram, zoom
from markitdoc.visuals.infographics import render_infographic
from markitdoc.markup.inline import anchor, inline_runs, parser
from markitdoc.pdf.pages import escaped, inline_markup, runs_markup
from markitdoc.utils.helpers import lifted
from markitdoc.markup.elements import (chart_data, chart_sizes, closing_index, column_alignments, element_settings,
                                       list_schemes, numeric_cell, only_display_maths, paragraph_alignments,
                                       settings_from, table_styles, totals_row, without_display_maths)
from markitdoc.pdf.flow_pages import FlowPages, body_size, measured, place_notes, probe_of, table_size, top_height
from markitdoc.pdf.flow_text import (add_callout, add_equation, add_figure, add_heading, add_list_item, add_notes,
                                     add_paragraph, draw_runs, needs_runs)

logger = logging.getLogger(__name__)
page_break_marker = "+++"
plain_style = "plain"
minimum_column, readable_column, column_padding = 16, 26, 7
box_drawing = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬"


indent_step = 8
soft_break_share = 0.35


def render_flow(pdf: FlowPages, markdown: str):
    render_tokens(pdf, parser.parse(markdown))


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
            target = anchor.search(tokens[index + 1].content)
            text = anchor.sub("", inline_markup(tokens[index + 1], pdf.targets))
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
                draw_runs(pdf, inline_runs(inline, pdf.targets), paragraph_alignments.get(style, "L"),
                          indent + (indent_step if "indent" in style else 0))
            elif text == page_break_marker:
                if pdf.page_break_trigger - pdf.get_y() < pdf.eph * soft_break_share:
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
                add_paragraph(pdf, text, paragraph_alignments.get(style, "L"), indent + (indent_step if "indent" in style else 0),
                              lead="lead" in style)
            for equation in equations:
                add_equation(pdf, equation)
            index += 3
            continue
        if token.type in ("bullet_list_open", "ordered_list_open"):
            scheme = pending if pending in list_schemes else (list_stack[-1]["scheme"] if list_stack and list_stack[-1]["scheme"] == "legal" else "")
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
            indent += indent_step
        elif token.type == "dd_close":
            indent -= indent_step
        elif token.type == "blockquote_open":
            end = closing_index(tokens, index, "blockquote_open", "blockquote_close")
            add_callout(pdf, " ".join(inline_markup(t, pdf.targets) for t in tokens[index:end] if t.type == "inline"))
            index = end + 1
            continue
        elif token.type == "table_open":
            end = closing_index(tokens, index, "table_open", "table_close")
            cell_roles = []
            rows, settings = table_rows(tokens[index:end], pdf.targets, cell_roles), element_settings(tokens, end + 1)
            if settings.get("class") not in table_styles:
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


def flow_tail(pdf: FlowPages, markdown: str, spacing: float):
    probe = probe_of(pdf, pdf.t_margin)
    probe.spacing = spacing
    render_flow(probe, markdown)
    return probe.page_no(), (probe.get_y() - probe.t_margin) / (probe.page_break_trigger - probe.t_margin)


def fitted_spacing(pdf: FlowPages, markdown: str):
    pages, tail = flow_tail(pdf, markdown, 1.0)
    if pages < 2 or tail > 0.2:
        return 1.0
    for spacing in (0.95, 0.9):
        if flow_tail(pdf, markdown, spacing)[0] < pages:
            logger.info("Tightened a text section to %.0f%% spacing to avoid a near-empty last page", spacing * 100)
            return spacing
    return 1.0


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
            target.set_font("Head", "B", body_size * target.scale)
            target.set_text_color(*target.theme.rgb("ink"))
            target.multi_cell(target.area, body_size * target.scale * 0.55, escaped(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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


def column_groups(inner):
    starts = [position for position, token in enumerate(inner) if token.type == "heading_open"]
    if len(starts) < 2:
        blocks = [position for position, token in enumerate(inner) if token.level == 0 and token.type.endswith("_open")]
        middle = blocks[len(blocks) // 2] if len(blocks) > 1 else len(inner)
        return [inner[:middle], inner[middle:]]
    half = starts[len(starts) // 2]
    return [inner[:half], inner[half:]]


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


def table_rows(tokens, targets=frozenset(), roles=None):
    rows, row = [], None
    for token in tokens:
        if token.type == "tr_open":
            row = []
            roles.append([]) if roles is not None else None
        elif token.type == "inline" and row is not None:
            runs = inline_runs(token, targets)
            row.append(runs_markup(runs))
            if roles is not None:
                visible = {run.role for run in runs if run.text.strip()}
                roles[-1].append(visible.pop() if len(visible) == 1 else "")
        elif token.type == "tr_close":
            rows.append(row)
            row = None
    return rows


def column_widths(pdf: FlowPages, rows, available, size=table_size):
    pdf.set_font("Brand", "B", size)
    natural, longest_word = [], []
    for column in range(len(rows[0])):
        cells = [row[column].replace("**", "").replace("__", "") if column < len(row) else "" for row in rows]
        natural.append(max(pdf.get_string_width(cell) for cell in cells) + column_padding)
        longest_word.append(max((pdf.get_string_width(word) for cell in cells for word in cell.split()), default=0) + column_padding)
    minimums = [max(minimum_column, word) for word in longest_word]
    readable = sum(min(width, max(readable_column * size / table_size, low)) for width, low in zip(natural, minimums))
    if sum(natural) <= available:
        return [width * available / sum(natural) for width in natural], readable
    flexible = [max(width - low, 0) for width, low in zip(natural, minimums)]
    spare = max(available - sum(minimums), 0)
    total = sum(flexible) or 1
    return [low + spare * extra / total for low, extra in zip(minimums, flexible)], readable


def add_table(pdf: FlowPages, rows, style=None, alignments=(), roles=()):
    if not rows or not rows[0]:
        return
    width = pdf.area
    for size in (table_size * pdf.scale, table_size * pdf.scale - 1, table_size * pdf.scale - 1.5):
        widths, needed = column_widths(pdf, rows, width, size)
        if needed <= width:
            break
    if needed > width and pdf.w < pdf.h:
        pdf.add_page(orientation="L")
        width, size = pdf.area, table_size * pdf.scale
        widths, needed = column_widths(pdf, rows, width, size)
    caption_room = 8 * pdf.scale if pdf.pending_caption else 0
    if pdf.will_page_break(size * 0.55 * 1.6 * min(len(rows), 3) + 6 + caption_room):
        pdf.add_page()
    elif not pdf.measuring and pdf.w < pdf.h and len(rows) > 1:
        if pdf.will_page_break(top_height(pdf, lambda probe: add_table(probe, rows[:3], style, alignments, roles)) + caption_room):
            pdf.add_page()
    if pdf.pending_caption:
        caption, pdf.pending_caption = pdf.pending_caption, ""
        add_paragraph(pdf, caption, after=1.5)
    numeric = [all(numeric_cell.match(row[column].strip()) for row in rows[1:] if column < len(row) and row[column].strip())
               for column in range(len(rows[0]))]
    labels = [len(rows) > 2 and all(len(row[column].strip()) <= 14 and len(row[column].split()) <= 2 and not numeric_cell.match(row[column].strip())
                                    for row in rows[1:] if column < len(row) and row[column].strip())
              for column in range(len(rows[0]))]
    align = [(alignments[column] if column < len(alignments) and alignments[column] else None)
             or ("RIGHT" if is_number and len(rows) > 1 else "CENTER" if labels[column] and column > 0 else "LEFT")
             for column, is_number in enumerate(numeric)]
    style = style if style in table_styles else pdf.table_style if pdf.table_style in table_styles else "lined"
    boxed = style == "boxed"
    heading_style = FontFace(emphasis="BOLD", color=pdf.theme.rgb("ink"), fill_color=pdf.theme.rgb("surface") if boxed else None)
    pdf.set_font("Brand", "", size)
    pdf.set_text_color(*pdf.theme.rgb("body"))
    pdf.set_draw_color(*pdf.theme.rgb("rule" if boxed else "ink"))
    pdf.set_fill_color(*lifted(pdf.theme.rgb("surface"), 0.35))
    pdf.ln(1)
    try:
        top, start_page = pdf.get_y(), pdf.page_no()
        pdf.set_line_width(0.2 if boxed else 0.25)
        with pdf.table(col_widths=[w / width for w in widths], width=width, text_align=align, headings_style=heading_style,
                       cell_fill_mode=TableCellFillMode.EVEN_ROWS if style == "striped" else TableCellFillMode.NONE,
                       line_height=size * 0.55, padding=(2.2, 2.4), markdown=True, repeat_headings=1,
                       borders_layout="ALL" if boxed else "SINGLE_TOP_LINE") as table:
            for row_index, row in enumerate(rows):
                cells = table.row()
                total = row_index == len(rows) - 1 and row_index > 1 and totals_row.match(row[0] if row else "")
                for column in range(len(rows[0])):
                    role = roles[row_index][column] if row_index < len(roles) and column < len(roles[row_index]) else ""
                    face = FontFace(color=pdf.theme.rgb(role) if role else None, emphasis="BOLD" if total else None) if role or total else None
                    cells.cell(row[column] if column < len(row) else "", style=face if row_index else None)
        if not boxed:
            pdf.set_line_width(0.6)
            pdf.set_draw_color(*pdf.theme.rgb("ink"))
            if pdf.page_no() == start_page:
                pdf.line(pdf.l_margin, top, pdf.l_margin + width, top)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
            pdf.set_line_width(0.2)
    except ValueError as error:
        logger.warning("Table shown as text: %s", error)
        for row in rows[1:]:
            add_paragraph(pdf, "  ·  ".join(f"**{heading}:** {cell}" for heading, cell in zip(rows[0], row)))
    pdf.ln(4)
    pdf.back_to_portrait = pdf.w > pdf.h


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
