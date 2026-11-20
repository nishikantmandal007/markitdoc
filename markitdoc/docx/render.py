import logging
import tempfile
import time
from pathlib import Path

from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from markitdoc.docx.flow.render import add_callout, add_notes, render_markdown
from markitdoc.docx.flow.tables import step_table
from markitdoc.docx.styles import border_bottom, cell_borders, cell_fill, cell_margins, keep_together, new_table, repeat_header
from markitdoc.docx.writer import (
    WHITE,
    Writer,
    add_field,
    add_picture,
    apply_master,
    caption,
    first_paragraph,
    page_break,
    photo,
    plain,
    save_document,
    setup_chrome,
    stamp_properties,
    start_on_new_page,
    write_runs,
)
from markitdoc.markup.blocks import paragraphs, prepared
from markitdoc.markup.inline import Run, inline_runs, parser, plain_text
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.document import Document
from markitdoc.models.model_constants import PAGE_SWITCH
from markitdoc.themes.brands import brand_hooks
from markitdoc.themes.themes import Theme
from markitdoc.utils.helpers import creation_date, long_date
from markitdoc.visuals.gantt import gantt_plan, unit_name
from markitdoc.visuals.logos import logo_box, logo_ratio, logo_row

logger = logging.getLogger(__name__)
SECTION_LEVEL = {"divider": 1, "chapter": 1, "summary": 1, "closing": 1}
DOCUMENT_PHOTO_RATIOS = {"cover": 16 / 9, "chapter": 16 / 9, "feature": 16 / 9}

COVER_LOGO_WIDTH, COVER_LOGO_HEIGHT = 5.0, 1.8
PARTNER_ROW_HEIGHT, PARTNER_GAP, PARTNER_ROW_SHARE = 1.2, 0.6, 0.7
COMPANY_COVER_PHOTO_RATIO, COMPANY_COVER_SPACE = 3.0, 60


# converts inline source text into styled runs
def runs_of(writer, source):
    tokens = parser.parseInline(source or "")
    return inline_runs(tokens[0], writer.targets) if tokens else []


# adds a styled paragraph from inline markdown text
def text_paragraph(writer, source, style=None, role=None, size=None, bold=False, italic=False):
    paragraph = writer.body.add_paragraph(style=style)
    write_runs(writer, paragraph, runs_of(writer, source), size=size, role=role, bold=bold, italic=italic)
    return paragraph


# adds a block title and optional kicker to the Word document
def heading(writer, block, default="", kicker=""):
    title = block.slots.get("title") or default
    if not title:
        return
    if kicker:
        text_paragraph(writer, kicker.upper(), "Kicker")
    paragraph = writer.body.add_paragraph(style=f"Heading {SECTION_LEVEL.get(block.layout, 2)}")
    start_on_new_page(writer, paragraph)
    write_runs(writer, paragraph, runs_of(writer, title))


# adds the block lead as a styled Word paragraph
def lead(writer, block):
    if block.slots.get("lead"):
        text_paragraph(writer, block.slots["lead"], "Lead")


# adds each body paragraph to the Word document
def body(writer, block):
    for text in paragraphs(block.slots.get("body", "")):
        text_paragraph(writer, text)


# adds a block photo and its caption when an image is available
def block_photo(writer, image, alt):
    if image:
        photo(writer, image[0], writer.width, writer.width / (16 / 9), alt, image[4])
        caption(writer, image[1] or alt, image[2], image[3])


# draws the cover block with its title, image, logo, and subtitle
def draw_cover(writer, block, image):
    slots = block.slots
    company = slots.get("variant") == "company"
    if brand_hooks(writer.theme.name).docx_cover:
        draw_brand_cover(writer, slots)
        return
    if writer.theme.logo:
        width, height = logo_box(writer.theme.logo, COVER_LOGO_WIDTH, COVER_LOGO_HEIGHT)
        add_picture(writer, str(writer.theme.logo), width, writer.theme.brand or "Logo", height).alignment = WD_ALIGN_PARAGRAPH.LEFT
    if image:
        photo(writer, image[0], writer.width, writer.width / (COMPANY_COVER_PHOTO_RATIO if company else 16 / 9),
              slots.get("image", "Photograph"), image[4])
        credit = writer.body.add_paragraph(style="Caption")
        write_runs(writer, credit, [Run(image[2], link=image[3])])
    else:
        spacer = writer.body.add_paragraph()
        spacer.paragraph_format.space_before = Pt(COMPANY_COVER_SPACE if company else 150)
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
    plain(writer, meta, "  ·  ".join(part for part in (date, "" if company else writer.theme.brand or "") if part), 10, "muted")
    if company:
        company_details(writer)
    page_break(writer)


# the brand's address lines and its partner logos in rows, for any number of either
def company_details(writer):
    for line in writer.theme.address:
        plain(writer, writer.body.add_paragraph(), line, 9, "muted")
    places = logo_row([logo_ratio(path) for path in writer.theme.partners], writer.width * PARTNER_ROW_SHARE, PARTNER_ROW_HEIGHT, PARTNER_GAP)
    paragraph = None
    for path, (x, _, width, height) in zip(writer.theme.partners, places):
        if paragraph is None or x == 0:
            paragraph = writer.body.add_paragraph()
            paragraph.paragraph_format.space_before = Pt(8)
        else:
            paragraph.add_run("    ")
        paragraph.add_run().add_picture(str(path), width=Cm(width), height=Cm(height))


# draws the Word cover with the configured brand hook
def draw_brand_cover(writer, slots):
    brand_hooks(writer.theme.name).docx_cover(writer.document, plain_text(slots.get("title", writer.title)),
                                              lambda paragraph, color, sz="6", space="1": border_bottom(paragraph, color, int(sz), int(space)))
    writer.titled = True
    if slots.get("kicker"):
        text_paragraph(writer, slots["kicker"].upper(), "Kicker")
    if slots.get("subtitle"):
        text_paragraph(writer, slots["subtitle"], "Lead")


# draws key figures as a grid of Word table cells
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
        plain(writer, value, item[0], 26 if len(item[0]) <= 8 else 20, WHITE if dark else "mood", bold=True, font=writer.heading_font)
        label = cell.add_paragraph()
        label.paragraph_format.space_after = Pt(2)
        write_runs(writer, label, runs_of(writer, item[1] if len(item) > 1 else ""), 10.5, WHITE if dark else "ink", bold=True)
        if len(item) > 2 and item[2]:
            note = cell.add_paragraph()
            note.paragraph_format.space_after = Pt(0)
            write_runs(writer, note, runs_of(writer, item[2]), 9, (226, 230, 240) if dark else "body")
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


# draws an executive summary page with key figures
def draw_summary(writer, block, image):
    heading(writer, block, "Executive summary")
    lead(writer, block)
    figure_cells(writer, block.items)
    body(writer, block)


# draws a figures block with its heading, lead, figure cards, and body text
def draw_figures(writer, block, image):
    heading(writer, block)
    lead(writer, block)
    figure_cells(writer, block.items)
    body(writer, block)


# starts a new Word page and adds a section divider
def draw_divider(writer, block, image):
    if writer.started:
        page_break(writer)
    heading(writer, block, kicker=block.slots.get("number", ""))
    lead(writer, block)
    for item in block.items:
        if item and item[0]:
            text_paragraph(writer, "→  " + item[0], role="body")


# adds a chapter heading, image, body, and optional quote
def draw_chapter(writer, block, image):
    heading(writer, block, kicker=block.slots.get("number", ""))
    lead(writer, block)
    block_photo(writer, image, block.slots.get("image", "Photograph"))
    body(writer, block)
    if block.slots.get("quote"):
        text_paragraph(writer, block.slots["quote"], "Quote")


# draws key findings as numbered Word table rows
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


# draws process steps in a Word table
def draw_process(writer, block, image):
    heading(writer, block)
    lead(writer, block)
    step_table(writer, [(item[0], item[-1] if len(item) > 1 else "") for item in block.items if item and item[0]])


# draws timeline entries as a Gantt chart or Word table
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


# draws timeline ranges as a Word Gantt chart
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


# draws two sets of comparison items in a Word table
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
        write_runs(writer, first_paragraph(cell), runs_of(writer, title), 12, WHITE, bold=True)
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


# draws up to four items in a two-by-two Word table
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


# adds a styled pull quote and its optional attribution to Word
def draw_quote(writer, block, image):
    slots = block.slots
    paragraph = text_paragraph(writer, f"“{slots.get('quote', '')}”", "Quote", size=17)
    paragraph.paragraph_format.space_before = Pt(14)
    if slots.get("quote_by"):
        text_paragraph(writer, f"— {slots['quote_by']}", role="mood", bold=True)
    if slots.get("context"):
        text_paragraph(writer, slots["context"], role="muted", size=10)


# adds a feature image, body, and figure cards to Word
def draw_feature(writer, block, image):
    heading(writer, block)
    block_photo(writer, image, block.slots.get("image", "Photograph"))
    body(writer, block)
    figure_cells(writer, block.items, dark_first=False)


# adds the closing content and any available contact details
def draw_closing(writer, block, image):
    if block.slots.get("quote"):
        draw_quote(writer, block, image)
    heading(writer, block, "Next steps")
    body(writer, block)


DRAWERS = {"cover": draw_cover, "summary": draw_summary, "figures": draw_figures, "divider": draw_divider, "chapter": draw_chapter,
           "keypoints": draw_keypoints, "process": draw_process, "timeline": draw_timeline, "comparison": draw_comparison,
           "matrix": draw_matrix, "quote": draw_quote, "feature": draw_feature, "closing": draw_closing}


# inserts an automatic contents section into the Word document
def insert_contents(writer):
    title = writer.body.add_paragraph(style="Heading 1")
    plain(writer, title, "Contents")
    marker = writer.body.add_paragraph()
    page_break(writer)
    return title, marker


# fills the Word contents field with its heading and page settings
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


# renders a document as an editable Word file
def render_docx(document: Document, theme: Theme, output_path: Path, images=None, user_email="", styles=None, numbering=None):
    started = time.perf_counter()
    images = images or {}
    blocks = [prepared(block) for block in document.blocks]
    first = blocks[0] if blocks else None
    title = (first.slots.get("title") if first is not None else "") or next(
        (line.lstrip("# ").strip() for block in blocks for line in block.body.splitlines() if line.startswith("# ")), "Document")
    with tempfile.TemporaryDirectory() as work_folder:
        writer = Writer(theme, document.meta, Path(work_folder), images, title, styles, numbering)
        writer.restarts = [True] + [parse_attributes(found.group(1)).values.get("numbers") == "restart"
                                    for block in blocks for line in block.body.splitlines() if (found := PAGE_SWITCH.match(line.strip()))]
        cover = first is not None and first.layout == "cover"
        setup_chrome(writer, cover)
        if styles.pages_defined:
            apply_master(writer, writer.document.sections[0], styles.master("default"))
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
                elif block.layout in DRAWERS:
                    DRAWERS[block.layout](writer, block, writer.photos_by_block.get(index))
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

