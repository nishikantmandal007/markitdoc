import math
from lxml import etree
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from markitdoc.markup.elements import numeric_cell, rating_level, signed_number, table_marks
from markitdoc.markup.inline import plain_text
from markitdoc.pdf.flow_tables import column_widths
from markitdoc.pptx.deck import (add_rect, add_runs, content_width, key_sentences, no_grid_table_style, set_spacing,
                                 side_margin, tint, white)

max_bullets, max_table_rows, max_lead_above = 6, 8, 1.15
table_sizes = (18, 16, 14)
cell_side, cell_vertical = 0.12, 0.08


def table_cells(source):
    return source.replace("**", "").replace("__", "")


def row_height(deck, row, widths, size, header):
    lines = max(deck.lines(source, width - 2 * cell_side, size, "B" if header else "") for source, width in zip(row, widths))
    return lines * size * 1.2 / 72 + 2 * cell_vertical


def shortened_row(deck, row, widths, size, limit):
    row = list(row)
    while row_height(deck, row, widths, size, False) > limit:
        position = max(range(len(row)), key=lambda column: deck.lines(row[column], widths[column] - 2 * cell_side, size))
        row[position] = key_sentences(deck, row[position], widths[position] - 2 * cell_side, limit - 2 * cell_vertical, size)
    return tuple(row)


def table_pages(deck, table, available):
    plans = []
    for size in table_sizes:
        plain = [[table_cells(source) for source in row] for row in table.rows]
        millimetres, _ = column_widths(deck.measurer, plain, content_width * 25.4, size)
        widths = [width / 25.4 for width in millimetres]
        header = row_height(deck, table.rows[0], widths, size, True)
        body = [shortened_row(deck, row, widths, size, available - header) for row in table.rows[1:]]
        heights = [row_height(deck, row, widths, size, False) for row in body]
        pages = pack_rows(body, heights, available - header)
        plans.append((len(pages), -size, size, widths, header, pages, heights))
    return min(plans, key=lambda plan: plan[:2])


def pack_rows(rows, heights, room):
    pages, current, used = [], [], 0.0
    for row, height in zip(rows, heights):
        if current and (used + height > room or len(current) >= max_table_rows):
            pages.append(current)
            current, used = [], 0.0
        current.append(row)
        used += height
    pages.append(current)
    even = math.ceil(len(rows) / len(pages)) if rows else 0
    balanced = [rows[start:start + even] for start in range(0, len(rows), even)] if even else pages
    fits = all(sum(heights[start:start + even]) <= room for start in range(0, len(rows), even)) if even else True
    return balanced if fits and len(balanced) == len(pages) else pages


def cell_align(table, column):
    declared = table.aligns[column] if column < len(table.aligns) else None
    numbers = all(numeric_cell.match(table_cells(row[column]).strip()) for row in table.rows[1:] if column < len(row) and row[column].strip())
    pick = declared or ("RIGHT" if numbers and len(table.rows) > 1 else "LEFT")
    return {"RIGHT": PP_ALIGN.RIGHT, "CENTER": PP_ALIGN.CENTER}.get(pick, PP_ALIGN.LEFT)


def add_border(deck, cell, side, role, points):
    properties = cell._tc.get_or_add_tcPr()
    line = etree.SubElement(properties, qn(f"a:ln{side}"), w=str(int(points * 12700)), cap="flat", cmpd="sng", algn="ctr")
    if role is None:
        etree.SubElement(line, qn("a:noFill"))
        return
    etree.SubElement(etree.SubElement(line, qn("a:solidFill")), qn("a:srgbClr"), val=str(deck.color(role)))
    etree.SubElement(line, qn("a:prstDash"), val="solid")


def rating_ball(source):
    return rating_level(source) is not None


def draw_harvey_ball(deck, slide, left, top, size, level):
    outline = add_rect(deck, slide, left, top, size, size, "paper", "Harvey ball", MSO_SHAPE.OVAL)
    outline.line.color.rgb, outline.line.width = deck.color("mood"), Pt(1.25)
    if level == 4:
        outline.fill.solid()
        outline.fill.fore_color.rgb = deck.color("mood")
    elif level:
        wedge = slide.shapes.build_freeform(Inches(left + size / 2), Inches(top + size / 2), scale=1.0)
        steps = 12 * level
        points = [(left + size / 2 + size / 2 * math.cos(-math.pi / 2 + math.pi / 2 * level * step / steps),
                   top + size / 2 + size / 2 * math.sin(-math.pi / 2 + math.pi / 2 * level * step / steps)) for step in range(steps + 1)]
        wedge.add_line_segments([(Inches(x), Inches(y)) for x, y in points], close=True)
        shape = wedge.convert_to_shape()
        shape.name = "Harvey fill"
        shape.fill.solid()
        shape.fill.fore_color.rgb = deck.color("mood")
        shape.line.fill.background()


def style_cell(deck, cell, source, align, size, header, style, last, odd, first=False, highlight=False, rating=False):
    cell.margin_left = cell.margin_right = Inches(cell_side)
    cell.margin_top = cell.margin_bottom = Inches(cell_vertical)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    hairline = tint(deck, "mood", 0.75)
    for side in ("L", "R"):
        add_border(deck, cell, side, hairline if style == "boxed" else None, 0.5)
    add_border(deck, cell, "T", None if header else hairline, 0.5)
    add_border(deck, cell, "B", "mood" if last else hairline, 1.25 if last else 0.5)
    fill = "night" if header else tint(deck, "mood", 0.9) if highlight else "surface" if odd and style == "striped" else None
    if fill:
        cell.fill.solid()
        cell.fill.fore_color.rgb = deck.color(fill)
    else:
        cell.fill.background()
    if rating:
        cell.fill.background() if not highlight else None
        return
    mark = table_marks.get(plain_text(source).strip().lower()) if not header else None
    paragraph = cell.text_frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER if mark else align
    set_spacing(paragraph, size, 1.2, 0)
    if mark:
        add_runs(deck, paragraph, mark[0], size + 2, mark[1], bold=True)
        return
    signed = signed_number.match(plain_text(source)) if not header else None
    role = (white if header else "mood" if highlight else ("success" if signed.group(1) == "+" else "danger") if signed
            else "ink" if first else "body")
    add_runs(deck, paragraph, source, size, role, bold=header or highlight or first)


def add_table(deck, slide, table, rows, widths, header_height, heights, size, top):
    shape = slide.shapes.add_table(len(rows) + 1, len(widths), Inches(side_margin), Inches(top), Inches(sum(widths)),
                                   Inches(header_height + sum(heights)))
    shape.name = "Table"
    shape._element.graphic.graphicData.tbl.tblPr.find(qn("a:tableStyleId")).text = no_grid_table_style
    grid = shape.table
    grid.horz_banding = False
    for column, width in enumerate(widths):
        grid.columns[column].width = Inches(width)
    for position, height in enumerate([header_height] + heights):
        grid.rows[position].height = Inches(height)
    aligns = [cell_align(table, column) for column in range(len(widths))]
    brand = (deck.theme.brand or "").split()[:1]
    highlighted = {column for column, heading in enumerate(table.rows[0]) if column and brand and brand[0].lower() in plain_text(heading).lower()}
    rated = {column for column in range(1, len(widths)) if rows and all(rating_ball(row[column] if column < len(row) else "") for row in rows)}
    for position, row in enumerate([table.rows[0]] + list(rows)):
        for column in range(len(widths)):
            style_cell(deck, grid.cell(position, column), row[column] if column < len(row) else "", aligns[column], size,
                       position == 0, table.style, position == len(rows), position % 2 == 0 and position > 0, column == 0 and len(widths) > 2,
                       column in highlighted, column in rated and position > 0)
    for position, row in enumerate(rows, 1):
        y = top + header_height + sum(heights[:position - 1])
        for column in rated:
            ball = rating_level(row[column] if column < len(row) else "")
            x = side_margin + sum(widths[:column])
            diameter = min(0.3, heights[position - 1] * 0.6)
            draw_harvey_ball(deck, slide, x + widths[column] / 2 - diameter / 2, y + heights[position - 1] / 2 - diameter / 2, diameter, ball)
