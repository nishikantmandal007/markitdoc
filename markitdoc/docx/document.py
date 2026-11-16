import io
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path

import docx
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

import logging
from markitdoc.utils.constants import PLATFORM_CREATOR, PLATFORM_KEYWORDS
from markitdoc.markup.inline import Run
from markitdoc.pdf.layouts import fitted_image, lifted, long_date
from markitdoc.pptx.deck import office_font
from markitdoc.themes.brands import brand_hooks
from markitdoc.themes.themes import Theme

logger = logging.getLogger(__name__)
page_width, page_height, side_margin, top_margin = 21.0, 29.7, 2.2, 2.4
text_width = page_width - 2 * side_margin
body_size, small_size = 11, 9
heading_sizes = {1: 22, 2: 16, 3: 13, 4: 11.5}
white = (255, 255, 255)
bullet_marks = ("•", "–", "◦")
list_formats = {"decimal": "decimal", "alpha": "lowerLetter", "upper-alpha": "upperLetter", "roman": "lowerRoman", "upper-roman": "upperRoman",
                "legal": "decimal"}


class Writer:
    def __init__(self, theme: Theme, meta: dict, work_folder: Path, images: dict, title: str):
        self.document = docx.Document()
        self.theme, self.meta, self.work_folder, self.title = theme, meta, work_folder, title
        self.heading_font, self.body_font = office_font(theme.fonts["heading"]), office_font(theme.fonts["body"])
        self.figures = {key[1]: value for key, value in images.items() if isinstance(key, tuple)}
        self.photos_by_block = {key: value for key, value in images.items() if not isinstance(key, tuple)}
        self.photos = str(meta.get("photos", "natural")).lower()
        self.table_style = str(meta.get("tables", "lined")).lower()
        self.numbered = str(meta.get("numbering", "")).lower() == "decimal"
        self.headings = [0, 0, 0, 0]
        self.figure_count = self.table_count = 0
        self.notes, self.targets, self.lists = [], set(), {}
        self.bookmark_id = 0
        self.titled = self.started = self.break_next = False
        self.pending_caption = self.skip_title = ""
        self.body, self.width = self.document, text_width
        setup_page(self)
        setup_styles(self)

    @contextmanager
    def inside(self, container, width):
        previous = self.body, self.width
        self.body, self.width = container, width
        try:
            yield
        finally:
            self.body, self.width = previous

    def rgb(self, role):
        return RGBColor(*(role if isinstance(role, tuple) else self.theme.rgb(role)))

    def hex(self, role):
        values = role if isinstance(role, tuple) else self.theme.rgb(role)
        return "%02X%02X%02X" % tuple(values)

    def tint(self, role, share):
        return lifted(self.theme.rgb(role), share)


def setup_page(writer):
    section = writer.document.sections[0]
    section.page_width, section.page_height = Cm(page_width), Cm(page_height)
    section.left_margin = section.right_margin = Cm(side_margin)
    section.top_margin, section.bottom_margin = Cm(top_margin), Cm(2.2)
    section.header_distance = section.footer_distance = Cm(1.1)


def style_font(style, writer, size, role="body", bold=False, italic=False, heading=False):
    font = style.font
    font.name, font.size, font.bold, font.italic = writer.heading_font if heading else writer.body_font, Pt(size), bold, italic
    font.color.rgb = writer.rgb(role)
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for key in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(key), font.name)


def style_spacing(style, before, after, line=1.15, keep=False):
    form = style.paragraph_format
    form.space_before, form.space_after, form.line_spacing = Pt(before), Pt(after), line
    form.keep_with_next = keep
    form.widow_control = True


def paragraph_style(writer, name, base="Normal"):
    styles = writer.document.styles
    if name in [style.name for style in styles]:
        return styles[name]
    style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = styles[base]
    style.quick_style = True
    return style


def setup_styles(writer):
    styles = writer.document.styles
    normal = styles["Normal"]
    style_font(normal, writer, body_size)
    style_spacing(normal, 0, 7, 1.18)
    language = str(writer.meta.get("lang", "en")) or "en"
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), {"en": "en-GB", "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "hi": "hi-IN"}.get(language, language))
    normal.element.get_or_add_rPr().append(lang)
    style_font(styles["Title"], writer, 32, "ink", bold=True, heading=True)
    style_spacing(styles["Title"], 0, 10, 1.0)
    remove_borders(styles["Title"])
    style_font(styles["Subtitle"], writer, 14, "body")
    style_spacing(styles["Subtitle"], 0, 14, 1.2)
    for level, size in heading_sizes.items():
        style = styles[f"Heading {level}"]
        style_font(style, writer, size, "mood" if level == 2 else "ink", bold=True, heading=level <= 3)
        style_spacing(style, {1: 20, 2: 16, 3: 12, 4: 10}[level], {1: 8, 2: 6, 3: 4, 4: 2}[level], 1.05, keep=True)
    style_font(styles["Caption"], writer, small_size, "muted", italic=True)
    style_spacing(styles["Caption"], 3, 12, 1.1)
    style_font(styles["Quote"], writer, 13, "ink", italic=True)
    style_spacing(styles["Quote"], 8, 10, 1.25)
    border_left(styles["Quote"].element, writer.hex("mood"), 24, 10)
    styles["Quote"].paragraph_format.left_indent = Cm(0.6)
    lead = paragraph_style(writer, "Lead")
    style_font(lead, writer, 13.5, "ink")
    style_spacing(lead, 0, 10, 1.25)
    kicker = paragraph_style(writer, "Kicker")
    style_font(kicker, writer, 9.5, "mood", bold=True)
    style_spacing(kicker, 0, 4, 1.0, keep=True)
    code = paragraph_style(writer, "Code")
    style_font(code, writer, 9.5, "ink")
    code.font.name = "Consolas"
    code.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:ascii"), "Consolas")
    code.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:hAnsi"), "Consolas")
    style_spacing(code, 0, 0, 1.0)
    shade_style(code.element, writer.hex("surface"))
    for name in ("Header", "Footer"):
        style_font(styles[name], writer, 8.5, "muted")
    note = paragraph_style(writer, "Note text")
    style_font(note, writer, 9, "body")
    style_spacing(note, 0, 3, 1.1)


def remove_borders(style):
    properties = style.element.find(qn("w:pPr"))
    if properties is not None:
        for border in properties.findall(qn("w:pBdr")):
            properties.remove(border)


def border_left(element, color, size, space):
    properties = element.get_or_add_pPr()
    borders = properties.find(qn("w:pBdr"))
    if borders is None:
        borders = OxmlElement("w:pBdr")
        properties.append(borders)
    edge = OxmlElement("w:left")
    for key, value in (("w:val", "single"), ("w:sz", str(size)), ("w:space", str(space)), ("w:color", color)):
        edge.set(qn(key), value)
    borders.append(edge)


def border_bottom(paragraph, color, size=6, space=4):
    properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    edge = OxmlElement("w:bottom")
    for key, value in (("w:val", "single"), ("w:sz", str(size)), ("w:space", str(space)), ("w:color", color)):
        edge.set(qn(key), value)
    borders.append(edge)
    properties.append(borders)


def shade_style(element, color):
    shading = OxmlElement("w:shd")
    for key, value in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", color)):
        shading.set(qn(key), value)
    element.get_or_add_pPr().append(shading)


def write_runs(writer, paragraph, runs, size=None, role=None, bold=None, italic=None, font=None):
    for piece in runs:
        if not piece.text:
            continue
        if piece.link:
            add_link(writer, paragraph, piece, size, role)
            continue
        run = paragraph.add_run(piece.text)
        format_run(writer, run, piece, size, role, bold, italic, font)


def format_run(writer, run, piece, size, role, bold, italic, font):
    run.bold = True if bold else piece.bold or None
    run.italic = True if italic else piece.italic or None
    run.underline = piece.underline or None
    run.font.strike = piece.strike or None
    if size:
        run.font.size = Pt(size)
    if font:
        run.font.name = font
    if piece.role or role:
        run.font.color.rgb = writer.rgb(piece.role or role)
    if piece.script:
        run.font.subscript, run.font.superscript = piece.script == "SUB", piece.script == "SUP"
    if piece.highlight:
        shading = OxmlElement("w:shd")
        for key, value in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", writer.hex(writer.tint("mood", 0.78)))):
            shading.set(qn(key), value)
        run._r.get_or_add_rPr().append(shading)


def add_link(writer, paragraph, piece, size, role):
    link = OxmlElement("w:hyperlink")
    if piece.link.startswith("#"):
        link.set(qn("w:anchor"), piece.link[1:])
    else:
        relation = paragraph.part.relate_to(piece.link, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                                            is_external=True)
        link.set(qn("r:id"), relation)
    run = paragraph.add_run(piece.text)
    format_run(writer, run, piece, size, "mood", None, None, None)
    run.underline = True
    link.append(run._r)
    paragraph._p.append(link)


def plain(writer, paragraph, text, size=None, role=None, bold=False, italic=False, font=None):
    run = paragraph.add_run(text)
    run.bold, run.italic = bold or None, italic or None
    if size:
        run.font.size = Pt(size)
    if role:
        run.font.color.rgb = writer.rgb(role)
    if font:
        run.font.name = font
    return run


def bookmark(writer, paragraph, name):
    writer.bookmark_id += 1
    start, end = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
    start.set(qn("w:id"), str(writer.bookmark_id))
    start.set(qn("w:name"), name)
    end.set(qn("w:id"), str(writer.bookmark_id))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def add_field(paragraph, instruction, shown=""):
    for kind, text in (("begin", None), (None, instruction), ("separate", None), ("text", shown), ("end", None)):
        run = paragraph.add_run()
        if kind in ("begin", "separate", "end"):
            character = OxmlElement("w:fldChar")
            character.set(qn("w:fldCharType"), kind)
            run._r.append(character)
        elif kind == "text":
            run.text = text
        else:
            code = OxmlElement("w:instrText")
            code.set(qn("xml:space"), "preserve")
            code.text = f" {text} "
            run._r.append(code)


def cell_fill(cell, color):
    properties = cell._tc.get_or_add_tcPr()
    for old in properties.findall(qn("w:shd")):
        properties.remove(old)
    shading = OxmlElement("w:shd")
    for key, value in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", color)):
        shading.set(qn(key), value)
    properties.append(shading)


def cell_borders(cell, **edges):
    properties = cell._tc.get_or_add_tcPr()
    borders = properties.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        properties.append(borders)
    for side in ("top", "left", "bottom", "right"):
        value = edges.get(side)
        edge = OxmlElement(f"w:{side}")
        if value is None:
            edge.set(qn("w:val"), "nil")
        else:
            color, size = value
            for key, item in (("w:val", "single"), ("w:sz", str(size)), ("w:space", "0"), ("w:color", color)):
                edge.set(qn(key), item)
        borders.append(edge)


def cell_margins(cell, top=0.12, side=0.2, bottom=0.12):
    properties = cell._tc.get_or_add_tcPr()
    margins = OxmlElement("w:tcMar")
    for name, value in (("top", top), ("left", side), ("bottom", bottom), ("right", side)):
        edge = OxmlElement(f"w:{name}")
        edge.set(qn("w:w"), str(int(value * 567)))
        edge.set(qn("w:type"), "dxa")
        margins.append(edge)
    properties.append(margins)


def new_table(writer, rows, columns, widths=None):
    table = writer.body.add_table(rows=rows, cols=columns)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths = widths or [writer.width / columns] * columns
    for index, width in enumerate(widths):
        for cell in table.columns[index].cells:
            cell.width = Cm(width)
    properties = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    properties.append(layout)
    total = properties.find(qn("w:tblW"))
    if total is None:
        total = OxmlElement("w:tblW")
        properties.append(total)
    total.set(qn("w:w"), str(int(sum(widths) * 567)))
    total.set(qn("w:type"), "dxa")
    for column, width in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        column.set(qn("w:w"), str(int(width * 567)))
    for row in table.rows:
        never_split(row)
        for cell in row.cells:
            cell_borders(cell)
    return table


def keep_together(table):
    for row in table.rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True


def never_split(row):
    properties = row._tr.get_or_add_trPr()
    keep = OxmlElement("w:cantSplit")
    properties.append(keep)


def repeat_header(row):
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    properties.append(header)


def first_paragraph(cell):
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    return paragraph


def add_picture(writer, source, width_cm, alt="", height_cm=None):
    paragraph = writer.body.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.space_after = Pt(4)
    run = paragraph.add_run()
    shape = run.add_picture(source, width=Cm(width_cm), height=Cm(height_cm) if height_cm else None)
    properties = shape._inline.docPr
    properties.set("descr", alt or "Picture")
    properties.set("name", (alt or "Picture")[:60])
    return paragraph


def photo(writer, path, width_cm, height_cm, alt):
    fitted = fitted_image(Path(path), width_cm * 40, height_cm * 40, writer.work_folder, (), writer.photos, writer.theme)
    return add_picture(writer, str(fitted), width_cm, alt, height_cm)


def caption(writer, text, credit="", source=""):
    writer.figure_count += 1
    paragraph = writer.body.add_paragraph(style="Caption")
    plain(writer, paragraph, f"Figure {writer.figure_count}. ", bold=True)
    plain(writer, paragraph, text)
    if credit:
        plain(writer, paragraph, "  ·  ")
        if source:
            add_link(writer, paragraph, Run(credit, link=source), None, None)
        else:
            plain(writer, paragraph, credit)
    return paragraph


def trim_blank_tail(writer):
    body = writer.document.element.body
    while len(body) > 1:
        last = body[-2] if body[-1].tag == qn("w:sectPr") else body[-1]
        if last.tag != qn("w:p") or last.xpath(".//w:t[normalize-space()]") or last.xpath(".//w:drawing") or last.xpath(".//w:sectPr") \
                or last.xpath(".//w:br[@w:type='page']"):
            return
        body.remove(last)


def start_on_new_page(writer, paragraph):
    if writer.break_next:
        if writer.body is writer.document:
            trim_blank_tail(writer)
            body = writer.document.element.body
            anchor = body[-2] if body[-1].tag == qn("w:sectPr") else body[-1]
            if anchor is not paragraph._p:
                anchor.addnext(paragraph._p)
        paragraph.paragraph_format.page_break_before = True
        writer.break_next = False


def page_break(writer):
    paragraph = writer.body.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.add_run().add_break(WD_BREAK.PAGE)


def landscape_section(writer, wide):
    section = writer.document.add_section(WD_SECTION.NEW_PAGE)
    section.orientation = WD_ORIENT.LANDSCAPE if wide else WD_ORIENT.PORTRAIT
    width, height = (page_height, page_width) if wide else (page_width, page_height)
    section.page_width, section.page_height = Cm(width), Cm(height)
    section.left_margin = section.right_margin = Cm(side_margin)
    return (width - 2 * side_margin) if wide else text_width


def setup_chrome(writer, cover):
    chrome = brand_hooks(writer.theme.name).docx_chrome
    if chrome:
        chrome(writer.document, lambda paragraph, color, sz="6", space="1": border_bottom(paragraph, color, int(sz), int(space)))
        writer.width = inches_to_cm(writer.document.sections[0])
        writer.document.sections[0].different_first_page_header_footer = False
        return
    section = writer.document.sections[0]
    section.different_first_page_header_footer = cover
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    page_fields(writer, header, str(writer.meta.get("header", "")).strip().strip("'\"") or writer.title)
    border_bottom(header, writer.hex("rule"), 4, 4)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    note = str(writer.meta.get("footer", "")).strip().strip("'\"")
    page_fields(writer, footer, note if "{page}" in note else (note + "    " if note else "") + "Page {page} of {pages}")


def page_fields(writer, paragraph, template):
    fields = {"{page}": ("PAGE", "1"), "{pages}": ("NUMPAGES", "1"), "{section}": ('STYLEREF "Heading 2"', "")}
    text = template.replace("{title}", writer.title).replace("{date}", long_date(writer.meta.get("date", "")))
    for piece in re.split(r"(\{page\}|\{pages\}|\{section\})", text):
        if piece in fields:
            add_field(paragraph, *fields[piece])
            for run in paragraph.runs[-5:]:
                run.font.size, run.font.color.rgb = Pt(8.5), writer.rgb("muted")
        elif piece:
            plain(writer, paragraph, piece, 8.5, "muted")


def inches_to_cm(section):
    return (section.page_width - section.left_margin - section.right_margin) / 360000


def stamp_properties(writer, created, user_email):
    properties = writer.document.core_properties
    properties.title, properties.subject = writer.title, str(writer.meta.get("subject", "")) or writer.title
    properties.author = str(writer.meta.get("author", "")).strip("'\" ") or writer.theme.brand or PLATFORM_CREATOR
    properties.keywords = PLATFORM_KEYWORDS
    properties.last_modified_by = PLATFORM_CREATOR
    properties.comments = f"Generated for {user_email}" if user_email else ""
    properties.created = properties.modified = created
    properties.revision = 1
    settings = writer.document.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)


def save_document(writer, output_path: Path):
    buffer = io.BytesIO()
    writer.document.save(buffer)
    output = io.BytesIO()
    with zipfile.ZipFile(buffer) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            entry = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type, entry.external_attr = zipfile.ZIP_DEFLATED, info.external_attr
            target.writestr(entry, data)
    output_path.write_bytes(output.getvalue())

