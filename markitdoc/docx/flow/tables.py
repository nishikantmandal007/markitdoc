import io
import re
from functools import lru_cache

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt
from PIL import Image, ImageDraw

from markitdoc.docx.styles import cell_borders, cell_fill, cell_margins, keep_together, new_table, repeat_header
from markitdoc.docx.writer import first_paragraph, landscape_section, plain, white, write_runs
from markitdoc.markup.elements import column_alignments, rating_level, settings_from, SIGNED_NUMBER, TABLE_MARKS, TOTALS_ROW
from markitdoc.markup.inline import inline_runs, parser

numeric_cell = re.compile(r"^[\s$€£¥+\-−~≈<>]*\d[\d.,\s]*(%|[kKmMbB]|bn|x|pts?|bps)?\s*$")


# removes inline emphasis markers from table cell text
def table_cells(tokens):
    rows, row = [], None
    for token in tokens:
        if token.type == "tr_open":
            row = []
        elif token.type == "inline" and row is not None:
            row.append(token)
        elif token.type == "tr_close":
            rows.append(row)
            row = None
    return rows


# draws a styled PowerPoint table with a repeated header
def add_table(writer, tokens, style):
    rows = table_cells(tokens)
    if not rows:
        return
    header_text = ["".join(run.text for run in inline_runs(cell)) for cell in rows[0]]
    if len(rows) > 2 and re.fullmatch(r"\{[^{}]*\}", rows[-1][0].content.strip() if rows[-1] else "") and not any(
            cell.content.strip() for cell in rows[-1][1:]):
        style = settings_from(rows[-1][0].content.strip()[1:-1]).get("class", "") or style
        rows = rows[:-1]
    columns = len(rows[0])
    wide = columns > 8 and writer.body is writer.document
    width = landscape_section(writer, True) if wide else writer.width
    if writer.pending_caption:
        writer.table_count += 1
        paragraph = writer.body.add_paragraph(style="Caption")
        paragraph.paragraph_format.keep_with_next = True
        plain(writer, paragraph, f"Table {writer.table_count}. ", bold=True)
        plain(writer, paragraph, writer.pending_caption)
        writer.pending_caption = ""
    body_rows = [[cell.content for cell in row] for row in rows[1:]]
    numeric = [all(numeric_cell.match(row[column]) for row in body_rows if column < len(row) and row[column].strip()) and any(
        column < len(row) and row[column].strip() for row in body_rows) for column in range(columns)]
    rated = {column for column in range(1, columns) if body_rows and all(rating_level(row[column] if column < len(row) else "") is not None
                                                                          for row in body_rows)}
    brand = (writer.theme.brand or "").split()[:1]
    highlighted = {column for column, heading in enumerate(header_text) if column and brand and brand[0].lower() in heading.lower()}
    alignment = column_alignments(tokens)
    weights = [max(9, max(len(inline_runs_text(row[column])) if column < len(row) else 0 for row in rows)) for column in range(columns)]
    weights = [min(weight, 40) for weight in weights]
    widths = [width * weight / sum(weights) for weight in weights]
    table = new_table(writer, len(rows), columns, widths)
    repeat_header(table.rows[0])
    hairline = writer.hex(writer.tint("mood", 0.75))
    for row_index, row in enumerate(rows):
        header = row_index == 0
        last = row_index == len(rows) - 1
        total = last and row_index > 1 and TOTALS_ROW.match(row[0].content if row else "")
        for column in range(columns):
            cell = table.cell(row_index, column)
            cell_margins(cell, 0.09, 0.18, 0.09)
            source = row[column] if column < len(row) else None
            fill = writer.hex("night") if header else writer.hex(writer.tint("mood", 0.9)) if column in highlighted else (
                writer.hex("surface") if style == "striped" and row_index % 2 == 0 else None)
            if fill:
                cell_fill(cell, fill)
            edge = (writer.hex("mood"), 10) if last or total else (hairline, 4)
            cell_borders(cell, top=(writer.hex("ink"), 8) if total else None, bottom=None if header else edge,
                         left=(hairline, 4) if style == "boxed" else None, right=(hairline, 4) if style == "boxed" else None)
            paragraph = first_paragraph(cell)
            align = alignment[column] if column < len(alignment) and alignment[column] else ("right" if numeric[column] and not header else "")
            paragraph.alignment = {"right": WD_ALIGN_PARAGRAPH.RIGHT, "center": WD_ALIGN_PARAGRAPH.CENTER}.get(str(align).lower(),
                                                                                                                WD_ALIGN_PARAGRAPH.LEFT)
            runs = inline_runs(source, writer.targets) if source is not None else []
            text = "".join(run.text for run in runs).strip()
            if not header and column in rated:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.add_run().add_picture(harvey_png(rating_level(text), writer.hex("mood")), width=Cm(0.42))
                continue
            mark = TABLE_MARKS.get(text.lower()) if not header else None
            if mark:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                plain(writer, paragraph, mark[0], 11, mark[1], bold=True)
                continue
            signed = SIGNED_NUMBER.match(text) if not header else None
            role = white if header else "mood" if column in highlighted else (
                "success" if signed.group(1) == "+" else "danger") if signed else "ink" if column == 0 and columns > 2 else None
            write_runs(writer, paragraph, runs, size=8.5 if columns > 6 else 9.5 if columns > 4 else 10, role=role,
                       bold=header or total or column in highlighted or (column == 0 and columns > 2))
    if len(rows) <= 7:
        keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)
    if wide:
        landscape_section(writer, False)


# returns the plain text from inline runs in a table cell
def inline_runs_text(token):
    return "".join(run.text for run in inline_runs(token))


# draws a circular rating symbol as a PNG image
@lru_cache(maxsize=None)
def harvey_png(level, color):
    size = 96
    picture = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(picture)
    rgb = tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))
    box = (6, 6, size - 6, size - 6)
    if level:
        draw.pieslice(box, -90, -90 + 90 * level, fill=rgb)
    draw.ellipse(box, outline=rgb, width=7)
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    return io.BytesIO(buffer.getvalue())


# draws process steps as a numbered table in Word
def step_table(writer, steps):
    table = new_table(writer, len(steps), 2, [1.4, writer.width - 1.4])
    for row, (title, detail) in enumerate(steps):
        number, text = table.cell(row, 0), table.cell(row, 1)
        cell_fill(number, writer.hex("mood"))
        cell_fill(text, writer.hex("surface"))
        for cell in (number, text):
            cell_borders(cell, bottom=("FFFFFF", 18))
            cell_margins(cell, 0.18, 0.25, 0.18)
        marker = first_paragraph(number)
        marker.alignment = WD_ALIGN_PARAGRAPH.CENTER
        plain(writer, marker, f"{row + 1:02d}", 13, white, bold=True)
        heading = first_paragraph(text)
        write_runs(writer, heading, inline_runs(parser.parseInline(title)[0], writer.targets), 11.5, "ink", bold=True)
        if detail:
            paragraph = text.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(0)
            write_runs(writer, paragraph, inline_runs(parser.parseInline(detail)[0], writer.targets), 10)
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)
