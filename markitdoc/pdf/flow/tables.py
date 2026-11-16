import logging

from fpdf.enums import TableCellFillMode
from fpdf.fonts import FontFace

from markitdoc.markup.elements import NUMERIC_CELL, TABLE_STYLES, TOTALS_ROW
from markitdoc.markup.inline import inline_runs
from markitdoc.pdf.flow.pages import TABLE_SIZE, FlowPages, top_height
from markitdoc.pdf.flow.text import CODE_SCALE, add_paragraph
from markitdoc.pdf.pages import runs_markup
from markitdoc.utils.helpers import lifted

logger = logging.getLogger(__name__)

TABLE_LINE = 0.3528 * 1.2
HEAVY_RULE, LIGHT_RULE = 0.282, 0.141
MINIMUM_COLUMN, READABLE_COLUMN, COLUMN_PADDING = 16, 26, 7


# converts markdown table tokens into styled cell rows
def table_rows(tokens, targets=frozenset(), roles=None, monos=None):
    rows, row = [], None
    for token in tokens:
        if token.type == "tr_open":
            row = []
            roles.append([]) if roles is not None else None
            monos.append([]) if monos is not None else None
        elif token.type == "inline" and row is not None:
            runs = inline_runs(token, targets)
            row.append(runs_markup(runs))
            if roles is not None:
                visible = {run.role for run in runs if run.text.strip()}
                roles[-1].append(visible.pop() if len(visible) == 1 else "")
            if monos is not None:
                monos[-1].append(all(run.code for run in runs if run.text.strip()) and any(run.code for run in runs))
        elif token.type == "tr_close":
            rows.append(row)
            row = None
    return rows


# chooses readable table column widths within the available space
def column_widths(pdf: FlowPages, rows, available, size=TABLE_SIZE):
    pdf.set_font("Brand", "B", size)
    natural, longest_word = [], []
    for column in range(len(rows[0])):
        cells = [row[column].replace("**", "").replace("__", "") if column < len(row) else "" for row in rows]
        natural.append(max(pdf.get_string_width(cell) for cell in cells) + COLUMN_PADDING)
        longest_word.append(max((pdf.get_string_width(word) for cell in cells for word in cell.split()), default=0) + COLUMN_PADDING)
    minimums = [max(MINIMUM_COLUMN, word) for word in longest_word]
    readable = sum(min(width, max(READABLE_COLUMN * size / TABLE_SIZE, low)) for width, low in zip(natural, minimums))
    if sum(natural) <= available:
        return [width * available / sum(natural) for width in natural], readable
    flexible = [max(width - low, 0) for width, low in zip(natural, minimums)]
    spare = max(available - sum(minimums), 0)
    total = sum(flexible) or 1
    return [low + spare * extra / total for low, extra in zip(minimums, flexible)], readable


# draws a styled PowerPoint table with a repeated header
def add_table(pdf: FlowPages, rows, style=None, alignments=(), roles=(), monos=()):
    if not rows or not rows[0]:
        return
    width = pdf.area
    for size in (TABLE_SIZE * pdf.scale, TABLE_SIZE * pdf.scale - 1, TABLE_SIZE * pdf.scale - 1.5):
        widths, needed = column_widths(pdf, rows, width, size)
        if needed <= width:
            break
    if needed > width and pdf.w < pdf.h:
        pdf.add_page(orientation="L")
        width, size = pdf.area, TABLE_SIZE * pdf.scale
        widths, needed = column_widths(pdf, rows, width, size)
    caption_room = 8 * pdf.scale if pdf.pending_caption else 0
    if pdf.will_page_break(size * TABLE_LINE * 1.6 * min(len(rows), 3) + 6 + caption_room):
        pdf.add_page()
    elif not pdf.measuring and pdf.w < pdf.h and len(rows) > 1:
        if pdf.will_page_break(top_height(pdf, lambda probe: add_table(probe, rows[:3], style, alignments, roles, monos)) + caption_room):
            pdf.add_page()
    if pdf.pending_caption:
        caption, pdf.pending_caption = pdf.pending_caption, ""
        add_paragraph(pdf, caption, after=1.5)
    numeric = [all(NUMERIC_CELL.match(row[column].strip()) for row in rows[1:] if column < len(row) and row[column].strip())
               for column in range(len(rows[0]))]
    labels = [len(rows) > 2 and all(len(row[column].strip()) <= 14 and len(row[column].split()) <= 2 and not NUMERIC_CELL.match(row[column].strip())
                                    for row in rows[1:] if column < len(row) and row[column].strip())
              for column in range(len(rows[0]))]
    align = [(alignments[column] if column < len(alignments) and alignments[column] else None)
             or ("RIGHT" if is_number and len(rows) > 1 else "CENTER" if labels[column] and column > 0 else "LEFT")
             for column, is_number in enumerate(numeric)]
    style = style if style in TABLE_STYLES else pdf.table_style if pdf.table_style in TABLE_STYLES else "lined"
    boxed = style == "boxed"
    heading_style = FontFace(emphasis="BOLD", color=pdf.theme.rgb("ink"), fill_color=pdf.theme.rgb("surface") if boxed else None)
    pdf.set_font("Brand", "", size)
    pdf.set_text_color(*pdf.theme.rgb("body"))
    pdf.set_draw_color(*pdf.theme.rgb("rule" if boxed else "ink"))
    pdf.set_fill_color(*pdf.theme.rgb("paper"))
    pdf.ln(1)
    try:
        top, start_page = pdf.get_y(), pdf.page_no()
        pdf.set_line_width(0.2 if boxed else LIGHT_RULE)
        with pdf.table(col_widths=[w / width for w in widths], width=width, text_align=align, headings_style=heading_style,
                       cell_fill_mode=TableCellFillMode.EVEN_ROWS if style == "striped" else TableCellFillMode.NONE,
                       cell_fill_color=lifted(pdf.theme.rgb("surface"), 0.35),
                       line_height=size * TABLE_LINE, padding=(1, 2.5), markdown=True, repeat_headings=1,
                       borders_layout="ALL" if boxed else "SINGLE_TOP_LINE") as table:
            for row_index, row in enumerate(rows):
                cells = table.row()
                total = row_index == len(rows) - 1 and row_index > 1 and TOTALS_ROW.match(row[0] if row else "")
                for column in range(len(rows[0])):
                    role = roles[row_index][column] if row_index < len(roles) and column < len(roles[row_index]) else ""
                    mono = row_index < len(monos) and column < len(monos[row_index]) and monos[row_index][column]
                    face = (FontFace(color=pdf.theme.rgb(role) if role else None, emphasis="BOLD" if total else None,
                                     family="Mono" if mono else None, size_pt=size * CODE_SCALE if mono else None)
                            if role or total or mono else None)
                    cells.cell(row[column] if column < len(row) else "", style=face if row_index else None)
        if not boxed:
            pdf.set_line_width(HEAVY_RULE)
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
    pdf.back_to_portrait = pdf.w > pdf.h and not pdf.master_landscape
