import tempfile
import time
from pathlib import Path

from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

import logging
from markitdoc.models.document import Document
from markitdoc.docx.document import (Writer, add_field, add_picture, border_bottom, caption, cell_borders, cell_fill,
                                     cell_margins, first_paragraph, keep_together, new_table, page_break, photo, plain,
                                     repeat_header, save_document, setup_chrome, stamp_properties, start_on_new_page,
                                     white, write_runs)
from markitdoc.docx.flow import add_callout, add_notes, render_markdown, step_table
from markitdoc.markup.inline import inline_runs, parser
from markitdoc.markup.blocks import paragraphs, prepared
from markitdoc.utils.helpers import creation_date, long_date
from markitdoc.pptx.deck import plain_text
from markitdoc.themes.brands import brand_hooks
from markitdoc.pptx.layouts import gantt_plan, unit_name
from markitdoc.themes.themes import Theme

logger = logging.getLogger(__name__)
section_level = {"divider": 1, "chapter": 1, "summary": 1, "closing": 1}
document_photo_ratios = {"cover": 16 / 9, "chapter": 16 / 9, "feature": 16 / 9}


def runs_of(writer, source):
    tokens = parser.parseInline(source or "")
    return inline_runs(tokens[0], writer.targets) if tokens else []


def text_paragraph(writer, source, style=None, role=None, size=None, bold=False, italic=False):
    paragraph = writer.body.add_paragraph(style=style)
    write_runs(writer, paragraph, runs_of(writer, source), size=size, role=role, bold=bold, italic=italic)
    return paragraph


def heading(writer, block, default="", kicker=""):
    title = block.slots.get("title") or default
    if not title:
        return
    if kicker:
        text_paragraph(writer, kicker.upper(), "Kicker")
    paragraph = writer.body.add_paragraph(style=f"Heading {section_level.get(block.layout, 2)}")
    start_on_new_page(writer, paragraph)
    write_runs(writer, paragraph, runs_of(writer, title))


def lead(writer, block):
    if block.slots.get("lead"):
        text_paragraph(writer, block.slots["lead"], "Lead")


def body(writer, block):
    for text in paragraphs(block.slots.get("body", "")):
        text_paragraph(writer, text)


def block_photo(writer, image, alt):
    if image:
        photo(writer, image[0], writer.width, writer.width / (16 / 9), alt)
        caption(writer, image[1] or alt, image[2], image[3])


def draw_cover(writer, block, image):
    slots = block.slots
    if brand_hooks(writer.theme.name).docx_cover:
        draw_brand_cover(writer, slots)
        return
    if writer.theme.logo:
        add_picture(writer, str(writer.theme.logo), 3.2, writer.theme.brand or "Logo").alignment = WD_ALIGN_PARAGRAPH.LEFT
    if image:
        photo(writer, image[0], writer.width, writer.width / (16 / 9), slots.get("image", "Photograph"))
    else:
        spacer = writer.body.add_paragraph()
        spacer.paragraph_format.space_before = Pt(150)
    if slots.get("kicker"):
        text_paragraph(writer, slots["kicker"].upper(), "Kicker")
    paragraph = writer.body.add_paragraph(style="Title")
    write_runs(writer, paragraph, runs_of(writer, slots.get("title", writer.title)))
    writer.titled = True
    if slots.get("subtitle"):
        text_paragraph(writer, slots["subtitle"], "Subtitle")
    rule = writer.body.add_paragraph()
    border_bottom(rule, writer.hex("mood"), 18, 1)
    rule.paragraph_format.right_indent = Cm(writer.width - 2.4)
    meta = writer.body.add_paragraph()
    meta.paragraph_format.space_before = Pt(10)
    date = long_date(writer.meta.get("date", ""))
    plain(writer, meta, "  ·  ".join(part for part in (date, writer.theme.brand or "") if part), 10, "muted")
    page_break(writer)


def draw_brand_cover(writer, slots):
    brand_hooks(writer.theme.name).docx_cover(writer.document, plain_text(slots.get("title", writer.title)),
                                              lambda paragraph, color, sz="6", space="1": border_bottom(paragraph, color, int(sz), int(space)))
    writer.titled = True
    if slots.get("kicker"):
        text_paragraph(writer, slots["kicker"].upper(), "Kicker")
    if slots.get("subtitle"):
        text_paragraph(writer, slots["subtitle"], "Lead")


def figure_cells(writer, items, dark_first=True):
    items = [item for item in items if item and item[0]]
    if not items:
        return
    columns = len(items) if len(items) <= 4 else 3
    rows = (len(items) + columns - 1) // columns
    gap = 0.3
    table = new_table(writer, rows, columns * 2 - 1, [value for _ in range(columns) for value in ((writer.width - gap * (columns - 1)) / columns, gap)][:-1])
    for index, item in enumerate(items):
        cell = table.cell(index // columns, (index % columns) * 2)
        dark = dark_first and index == 0 and len(items) >= 3
        cell_fill(cell, writer.hex("night" if dark else "surface"))
        cell_borders(cell, top=(writer.hex("mood"), 24))
        cell_margins(cell, 0.3, 0.3, 0.3)
        value = first_paragraph(cell)
        plain(writer, value, item[0], 26 if len(item[0]) <= 8 else 20, white if dark else "mood", bold=True, font=writer.heading_font)
        label = cell.add_paragraph()
        label.paragraph_format.space_after = Pt(2)
        write_runs(writer, label, runs_of(writer, item[1] if len(item) > 1 else ""), 10.5, white if dark else "ink", bold=True)
        if len(item) > 2 and item[2]:
            note = cell.add_paragraph()
            note.paragraph_format.space_after = Pt(0)
            write_runs(writer, note, runs_of(writer, item[2]), 9, (226, 230, 240) if dark else "body")
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


def draw_summary(writer, block, image):
    heading(writer, block, "Executive summary")
    lead(writer, block)
    figure_cells(writer, block.items)
    body(writer, block)


def draw_figures(writer, block, image):
    heading(writer, block)
    lead(writer, block)
    figure_cells(writer, block.items)
    body(writer, block)


def draw_divider(writer, block, image):
    if writer.started:
        page_break(writer)
    heading(writer, block, kicker=block.slots.get("number", ""))
    lead(writer, block)
    for item in block.items:
        if item and item[0]:
            text_paragraph(writer, "→  " + item[0], role="body")


def draw_chapter(writer, block, image):
    heading(writer, block, kicker=block.slots.get("number", ""))
    lead(writer, block)
    block_photo(writer, image, block.slots.get("image", "Photograph"))
    body(writer, block)
    if block.slots.get("quote"):
        text_paragraph(writer, block.slots["quote"], "Quote")


def draw_keypoints(writer, block, image):
    heading(writer, block, "Key findings")
    lead(writer, block)
    table = new_table(writer, len(block.items), 2, [1.6, writer.width - 1.6])
    for row, item in enumerate(block.items):
        number_cell, text_cell = table.cell(row, 0), table.cell(row, 1)
        for cell in (number_cell, text_cell):
            cell_borders(cell, bottom=(writer.hex("rule"), 4))
            cell_margins(cell, 0.22, 0.15, 0.22)
        plain(writer, first_paragraph(number_cell), f"{row + 1:02d}", 20, "mood", bold=True, font=writer.heading_font)
        title = first_paragraph(text_cell)
        write_runs(writer, title, runs_of(writer, item[0]), 12, "ink", bold=True)
        if len(item) > 1 and item[1]:
            detail = text_cell.add_paragraph()
            detail.paragraph_format.space_after = Pt(0)
            write_runs(writer, detail, runs_of(writer, item[1]))
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


def draw_process(writer, block, image):
    heading(writer, block)
    lead(writer, block)
    step_table(writer, [(item[0], item[-1] if len(item) > 1 else "") for item in block.items if item and item[0]])


def draw_timeline(writer, block, image):
    heading(writer, block, "Timeline")
    lead(writer, block)
    items = [item for item in block.items if item and item[0]]
    plan = gantt_plan(items) if len(items) <= 12 else None
    if plan:
        draw_gantt(writer, items, plan)
        return
    table = new_table(writer, len(items), 2, [3.4, writer.width - 3.4])
    for row, item in enumerate(items):
        when, what = table.cell(row, 0), table.cell(row, 1)
        for cell in (when, what):
            cell_borders(cell, bottom=(writer.hex("rule"), 4))
            cell_margins(cell, 0.18, 0.15, 0.18)
        plain(writer, first_paragraph(when), item[0], 11, "mood", bold=True)
        event = first_paragraph(what)
        write_runs(writer, event, runs_of(writer, item[1] if len(item) > 1 else ""), 11, "ink", bold=True)
        if len(item) > 2 and item[2]:
            detail = what.add_paragraph()
            detail.paragraph_format.space_after = Pt(0)
            write_runs(writer, detail, runs_of(writer, item[2]), 10)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


def draw_gantt(writer, items, plan):
    unit, first, last, periods = plan
    columns = last - first + 1
    label = min(5.0, writer.width * 0.32)
    table = new_table(writer, len(items) + 1, columns + 1, [label] + [(writer.width - label) / columns] * columns)
    repeat_header(table.rows[0])
    for index in range(columns):
        cell = table.cell(0, index + 1)
        paragraph = first_paragraph(cell)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        plain(writer, paragraph, unit_name(unit, first + index), 8, "muted", bold=True)
        cell_borders(cell, bottom=(writer.hex("rule"), 6))
    for row, (item, found) in enumerate(zip(items, periods), 1):
        name = table.cell(row, 0)
        cell_margins(name, 0.12, 0.1, 0.12)
        write_runs(writer, first_paragraph(name), runs_of(writer, item[1] if len(item) > 1 else item[0]), 10, "ink", bold=True)
        if row % 2 == 1:
            cell_fill(name, writer.hex("surface"))
        for index in range(columns):
            cell = table.cell(row, index + 1)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            active = found[1] <= first + index <= found[2]
            cell_fill(cell, writer.hex("mood") if active else writer.hex("surface") if row % 2 == 1 else "FFFFFF")
            cell_borders(cell, left=(writer.hex("rule"), 2) if not active else None, top=("FFFFFF", 12) if active else None,
                         bottom=("FFFFFF", 12) if active else None)
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)
    for item in items:
        if len(item) > 2 and item[2]:
            paragraph = writer.body.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(2)
            write_runs(writer, paragraph, runs_of(writer, f"**{item[1]}** — {item[2]}"), 10)


def draw_comparison(writer, block, image):
    heading(writer, block)
    lead(writer, block)
    slots = block.slots
    table = new_table(writer, len(block.items) + 1, 2)
    repeat_header(table.rows[0])
    for column, (title, role) in enumerate(((slots.get("left", ""), "night"), (slots.get("right", ""), "mood"))):
        cell = table.cell(0, column)
        cell_fill(cell, writer.hex(role))
        cell_margins(cell, 0.18, 0.25, 0.18)
        write_runs(writer, first_paragraph(cell), runs_of(writer, title), 12, white, bold=True)
    for row, item in enumerate(block.items, 1):
        for column in range(2):
            cell = table.cell(row, column)
            cell_fill(cell, writer.hex("surface"))
            cell_borders(cell, bottom=("FFFFFF", 12))
            cell_margins(cell, 0.15, 0.25, 0.15)
            write_runs(writer, first_paragraph(cell), runs_of(writer, item[column] if column < len(item) else ""))
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)
    if slots.get("takeaway"):
        add_callout(writer, "", [runs_of(writer, f"**{slots['takeaway']}**")])


def draw_matrix(writer, block, image):
    heading(writer, block)
    lead(writer, block)
    table = new_table(writer, 2, 2)
    for index, item in enumerate(block.items[:4]):
        cell = table.cell(index // 2, index % 2)
        cell_fill(cell, writer.hex(writer.tint("mood", (0.82, 0.9, 0.9, 0.95)[index])))
        cell_borders(cell, top=("FFFFFF", 24), bottom=("FFFFFF", 24), left=("FFFFFF", 24), right=("FFFFFF", 24))
        cell_margins(cell, 0.3, 0.35, 0.3)
        write_runs(writer, first_paragraph(cell), runs_of(writer, item[0]), 12, "ink", bold=True)
        if len(item) > 1 and item[1]:
            detail = cell.add_paragraph()
            detail.paragraph_format.space_after = Pt(0)
            write_runs(writer, detail, runs_of(writer, item[1]), 10)
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


def draw_quote(writer, block, image):
    slots = block.slots
    paragraph = text_paragraph(writer, f"“{slots.get('quote', '')}”", "Quote", size=17)
    paragraph.paragraph_format.space_before = Pt(14)
    if slots.get("quote_by"):
        text_paragraph(writer, f"— {slots['quote_by']}", role="mood", bold=True)
    if slots.get("context"):
        text_paragraph(writer, slots["context"], role="muted", size=10)


def draw_feature(writer, block, image):
    heading(writer, block)
    block_photo(writer, image, block.slots.get("image", "Photograph"))
    body(writer, block)
    figure_cells(writer, block.items, dark_first=False)


def draw_closing(writer, block, image):
    if block.slots.get("quote"):
        draw_quote(writer, block, image)
    heading(writer, block, "Next steps")
    body(writer, block)


drawers = {"cover": draw_cover, "summary": draw_summary, "figures": draw_figures, "divider": draw_divider, "chapter": draw_chapter,
           "keypoints": draw_keypoints, "process": draw_process, "timeline": draw_timeline, "comparison": draw_comparison,
           "matrix": draw_matrix, "quote": draw_quote, "feature": draw_feature, "closing": draw_closing}


def insert_contents(writer):
    title = writer.body.add_paragraph(style="Heading 1")
    plain(writer, title, "Contents")
    marker = writer.body.add_paragraph()
    page_break(writer)
    return title, marker


def fill_contents(writer, title, marker):
    entries = [(paragraph.style.name, paragraph.text) for paragraph in writer.document.paragraphs
               if paragraph.style.name in ("Heading 1", "Heading 2") and paragraph._p is not title._p and paragraph.text.strip()]
    add_field(marker, 'TOC \\o "1-2" \\h \\z \\u', "")
    field = marker._p
    end = [element for element in field.iter(qn("w:fldChar")) if element.get(qn("w:fldCharType")) == "end"][0].getparent()
    separate = [element for element in field.iter(qn("w:fldChar")) if element.get(qn("w:fldCharType")) == "separate"][0].getparent()
    for element in list(field):
        if element is end or (element.tag == qn("w:r") and list(field).index(element) > list(field).index(separate)):
            field.remove(element)
    previous = marker
    for style, text in entries:
        entry = writer.document.add_paragraph()
        entry.paragraph_format.left_indent = Cm(0 if style == "Heading 1" else 0.6)
        entry.paragraph_format.space_after = Pt(4)
        plain(writer, entry, text, 11 if style == "Heading 1" else 10, "ink" if style == "Heading 1" else "body", bold=style == "Heading 1")
        previous._p.addnext(entry._p)
        previous = entry
    previous._p.append(end)


def render_docx(document: Document, theme: Theme, output_path: Path, images=None, user_email=""):
    started = time.perf_counter()
    images = images or {}
    blocks = [prepared(block) for block in document.blocks]
    first = blocks[0] if blocks else None
    title = (first.slots.get("title") if first is not None else "") or next(
        (line.lstrip("# ").strip() for block in blocks for line in block.body.splitlines() if line.startswith("# ")), "Document")
    with tempfile.TemporaryDirectory() as work_folder:
        writer = Writer(theme, document.meta, Path(work_folder), images, title)
        cover = first is not None and first.layout == "cover"
        setup_chrome(writer, cover)
        if brand_hooks(theme.name).docx_cover and not cover:
            draw_brand_cover(writer, {"title": title})
            writer.skip_title = plain_text(title)
        contents = None
        for index, block in enumerate(blocks):
            if index == 1 and str(document.meta.get("toc", "")).lower() in ("true", "yes", "on"):
                contents = insert_contents(writer)
            try:
                if block.layout == "flow":
                    render_markdown(writer, block.body)
                elif block.layout in drawers:
                    drawers[block.layout](writer, block, writer.photos_by_block.get(index))
                    if block.body.strip():
                        render_markdown(writer, block.body)
            except Exception:
                logger.exception("Block %d (%s) failed to draw; shown as text", index + 1, block.layout)
                text_paragraph(writer, " ".join(str(value) for value in block.slots.values()))
            writer.started = writer.started or block.layout != "cover"
        add_notes(writer)
        if contents:
            fill_contents(writer, *contents)
        stamp_properties(writer, creation_date(document.meta.get("date")), user_email)
        save_document(writer, output_path)
    logger.info("DOCX rendered: %d blocks, theme %s, %d images, %.1f s", len(blocks), theme.name, len(images), time.perf_counter() - started)
    return output_path

