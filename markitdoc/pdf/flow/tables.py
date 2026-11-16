import logging

from fpdf.enums import TableCellFillMode
from fpdf.fonts import FontFace

from markitdoc.markup.elements import numeric_cell, table_styles, totals_row
from markitdoc.markup.inline import inline_runs
from markitdoc.pdf.flow.pages import FlowPages, table_size, top_height
from markitdoc.pdf.flow.text import add_paragraph
from markitdoc.pdf.pages import runs_markup
from markitdoc.utils.helpers import lifted

logger = logging.getLogger(__name__)

minimum_column, readable_column, column_padding = 16, 26, 7


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
