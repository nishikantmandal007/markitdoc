import io
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path

import docx
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from markitdoc.docx.fonts import embed_fonts, word_font
from markitdoc.docx.styles import (
    LANGUAGE_TAGS,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    SIDE_MARGIN,
    TEXT_WIDTH,
    border_bottom,
    setup_page,
    setup_styles,
)
from markitdoc.markup.fields import field_values, replace_fields
from markitdoc.markup.inline import Run
from markitdoc.themes.brands import brand_hooks
from markitdoc.themes.themes import Theme
from markitdoc.utils.constants import PLATFORM_CREATOR, PLATFORM_KEYWORDS
from markitdoc.utils.helpers import MONO_FONT, lifted, long_date
from markitdoc.visuals.logos import logo_box
from markitdoc.visuals.photo_fit import fitted_image

WHITE = (255, 255, 255)
NUMBER_FORMATS = {"arabic": "decimal", "roman": "lowerRoman", "Roman": "upperRoman", "alpha": "lowerLetter", "none": "none"}
BULLET_MARKS = ("•", "–", "◦")
HEADER_LOGO_WIDTH, HEADER_LOGO_HEIGHT = 3.0, 0.6
WORD_ALIGNS = {"L": WD_ALIGN_PARAGRAPH.LEFT, "C": WD_ALIGN_PARAGRAPH.CENTER, "R": WD_ALIGN_PARAGRAPH.RIGHT, "J": WD_ALIGN_PARAGRAPH.JUSTIFY}
LIST_FORMATS = {"decimal": "decimal", "alpha": "lowerLetter", "upper-alpha": "upperLetter", "roman": "lowerRoman", "upper-roman": "upperRoman",
                "legal": "decimal"}


class Writer:
    # sets up the rendering context and its document settings
    def __init__(self, theme: Theme, meta: dict, work_folder: Path, images: dict, title: str, styles=None, numbering=None):
        self.document = docx.Document()
        self.styles, self.context = styles, None
        self.theme, self.meta, self.work_folder, self.title = theme, meta, work_folder, title
        self.heading_font, self.body_font = word_font(theme.fonts["heading"]), word_font(theme.fonts["body"])
        self.used_fonts = {theme.fonts["heading"], theme.fonts["body"]}
        self.figures = {key[1]: value for key, value in images.items() if isinstance(key, tuple)}
        self.photos_by_block = {key: value for key, value in images.items() if not isinstance(key, tuple)}
        self.photos = str(meta.get("photos", "natural")).lower()
        self.table_style = str(meta.get("tables", "lined")).lower()
        self.numbers = numbering.targets
        self.numbered = str(meta.get("numbering", "")).lower() == "decimal" or bool(numbering.section_numbers)
        self.headings = [0, 0, 0, 0]
        self.figure_count = self.table_count = 0
        self.notes, self.targets, self.lists = [], set(self.numbers), {}
        self.bookmark_id, self.master_name = 0, "default"
        self.titled = self.started = self.break_next = self.section_start = False
        self.pending_caption = self.skip_title = self.pending_target = ""
        self.restarts, self.section_no = [True], 0
        self.body, self.width = self.document, TEXT_WIDTH
        setup_page(self)
        setup_styles(self)

    # temporarily switches the writer to a cell and its available width
    @contextmanager
    def inside(self, container, width):
        previous = self.body, self.width
        self.body, self.width = container, width
        try:
            yield
        finally:
            self.body, self.width = previous

    # the look of an element under the stylesheet
    def look(self, selector, classes=(), inline=None):
        return self.styles.look(selector, classes, inline, context=self.context)

    # the Word font name for a look's font: a theme role or a declared font
    def font_named(self, name):
        if name == "heading":
            return self.heading_font
        if name == "mono":
            return MONO_FONT
        if face := self.styles.faces.get(name):
            family = word_font(face.files[0])
            self.used_fonts.add(face.files[0])
            return family
        return self.body_font

    # returns a theme color as a Word RGB value
    def rgb(self, role):
        return RGBColor(*(role if isinstance(role, tuple) else self.theme.rgb(role)))

    # returns a theme color as a six-digit hexadecimal value
    def hex(self, role):
        values = role if isinstance(role, tuple) else self.theme.rgb(role)
        return "%02X%02X%02X" % tuple(values)

    # lightens a theme color by the requested share
    def tint(self, role, share):
        return lifted(self.theme.rgb(role), share)


# writes styled inline text runs into a Word paragraph
def write_runs(writer, paragraph, runs, size=None, role=None, bold=None, italic=None, font=None, look=None):
    for piece in runs:
        if not piece.text:
            continue
        mine = writer.styles.span_look(piece.style, look) if look and piece.style else look
        if piece.link.startswith("#page:"):
            add_field(paragraph, f"PAGEREF {anchor_name(piece.link[6:])} \\h", piece.text, dirty=True)
            continue
        if piece.link:
            add_link(writer, paragraph, piece, size, role, mine)
            continue
        run = paragraph.add_run(piece.text)
        format_run(writer, run, piece, size, role, bold, italic, font, mine)


# sets font, emphasis, color, and script on a Word text run
def format_run(writer, run, piece, size, role, bold, italic, font, look=None):
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
    if look:
        style_run(writer, run, look, piece.role or role)
    if lang := dict(piece.style).get("lang"):
        mark = OxmlElement("w:lang")
        mark.set(qn("w:val"), LANGUAGE_TAGS.get(lang, lang))
        run._r.get_or_add_rPr().insert_element_before(mark, "w:eastAsianLayout", "w:specVanish", "w:oMath")
    if piece.highlight:
        shading = OxmlElement("w:shd")
        for key, value in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", writer.hex(writer.tint("mood", 0.78)))):
            shading.set(qn(key), value)
        run._r.get_or_add_rPr().append(shading)


# applies a stylesheet look to a Word run: font, size, colour, emphasis, small caps and character spacing
def style_run(writer, run, look, role=""):
    if look.font:
        run.font.name = writer.font_named(look.font)
        fonts = run._r.get_or_add_rPr().get_or_add_rFonts()
        for key in ("w:cs", "w:eastAsia"):
            fonts.set(qn(key), run.font.name)
    if look.size:
        run.font.size = Pt(look.size)
    if look.rgb and not role:
        run.font.color.rgb = RGBColor(*look.rgb)
    if look.bold is not None and run.bold is None:
        run.bold = look.bold
    if look.italic is not None and run.italic is None:
        run.italic = look.italic
    run.font.small_caps, run.font.all_caps = (True if look.caps == "small" else None), (True if look.caps == "all" else None)
    if look.tracking:
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:val"), str(round(look.tracking * 20)))
        run._r.get_or_add_rPr().insert_element_before(spacing, "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u",
                                                      "w:effect", "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em",
                                                      "w:lang", "w:eastAsianLayout", "w:specVanish", "w:oMath")


# sets a Word paragraph's alignment from a stylesheet look
def align_paragraph(paragraph, look):
    if look and look.align:
        paragraph.alignment = WORD_ALIGNS[look.align]


# adds a hyperlink run to a Word paragraph
def add_link(writer, paragraph, piece, size, role, look=None):
    link = OxmlElement("w:hyperlink")
    if piece.link.startswith("#"):
        link.set(qn("w:anchor"), anchor_name(piece.link[1:]))
    else:
        relation = paragraph.part.relate_to(piece.link, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                                            is_external=True)
        link.set(qn("r:id"), relation)
    run = paragraph.add_run(piece.text)
    format_run(writer, run, piece, size, "mood", None, None, None, look)
    run.underline = True
    link.append(run._r)
    paragraph._p.append(link)


# adds plain text to a Word paragraph with the requested style
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


# a Word bookmark name from an id: Word bookmark names cannot hold hyphens
def anchor_name(name):
    return name.replace("-", "_")


# adds a named Word bookmark around a paragraph
def bookmark(writer, paragraph, name):
    name = anchor_name(name)
    writer.bookmark_id += 1
    start, end = OxmlElement("w:bookmarkStart"), OxmlElement("w:bookmarkEnd")
    start.set(qn("w:id"), str(writer.bookmark_id))
    start.set(qn("w:name"), name)
    end.set(qn("w:id"), str(writer.bookmark_id))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


# adds a Word field with its result text
def add_field(paragraph, instruction, shown="", dirty=False):
    for kind, text in (("begin", None), (None, instruction), ("separate", None), ("text", shown), ("end", None)):
        run = paragraph.add_run()
        if kind in ("begin", "separate", "end"):
            character = OxmlElement("w:fldChar")
            character.set(qn("w:fldCharType"), kind)
            if dirty and kind == "begin":
                character.set(qn("w:dirty"), "true")
            run._r.append(character)
        elif kind == "text":
            run.text = text
        else:
            code = OxmlElement("w:instrText")
            code.set(qn("xml:space"), "preserve")
            code.text = f" {text} "
            run._r.append(code)


# returns the first table cell paragraph with no trailing space
def first_paragraph(cell):
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    return paragraph


# adds a centered picture with alternative text to Word
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


# crops and adds a fitted photo to the Word document
def photo(writer, path, width_cm, height_cm, alt, focus=""):
    fitted = fitted_image(Path(path), width_cm * 40, height_cm * 40, writer.work_folder, (), writer.photos, writer.theme, focus)
    return add_picture(writer, str(fitted), width_cm, alt, height_cm)


# adds a numbered figure caption with its optional credit and source
def caption(writer, text, credit="", source="", target=None, anchor=None):
    paragraph = writer.body.add_paragraph(style="Caption")
    if target:
        bookmark(writer, anchor if anchor is not None else paragraph, target.id)
        plain(writer, paragraph, f"{target.mark}. ", bold=True)
    else:
        writer.figure_count += 1
        plain(writer, paragraph, f"Figure {writer.figure_count}. ", bold=True)
    plain(writer, paragraph, text)
    if credit:
        plain(writer, paragraph, "  ·  ")
        if source:
            add_link(writer, paragraph, Run(credit, link=source), None, None)
        else:
            plain(writer, paragraph, credit)
    return paragraph


# removes empty trailing Word paragraphs before the section settings
def trim_blank_tail(writer):
    body = writer.document.element.body
    while len(body) > 1:
        last = body[-2] if body[-1].tag == qn("w:sectPr") else body[-1]
        if last.tag != qn("w:p") or last.xpath(".//w:t[normalize-space()]") or last.xpath(".//w:drawing") or last.xpath(".//w:sectPr") \
                or last.xpath(".//w:br[@w:type='page']"):
            return
        body.remove(last)


# applies a pending page break before a Word paragraph
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


# adds a page break to the current Word body
def page_break(writer):
    paragraph = writer.body.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.add_run().add_break(WD_BREAK.PAGE)


# starts a page section and returns its usable text width
def landscape_section(writer, wide):
    section = writer.document.add_section(WD_SECTION.NEW_PAGE)
    section.orientation = WD_ORIENT.LANDSCAPE if wide else WD_ORIENT.PORTRAIT
    width, height = (PAGE_HEIGHT, PAGE_WIDTH) if wide else (PAGE_WIDTH, PAGE_HEIGHT)
    section.page_width, section.page_height = Cm(width), Cm(height)
    section.left_margin = section.right_margin = Cm(SIDE_MARGIN)
    return (width - 2 * SIDE_MARGIN) if wide else TEXT_WIDTH


# sets up the themed header and footer for Word pages
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
    if writer.theme.logo:
        width, height = logo_box(writer.theme.logo, HEADER_LOGO_WIDTH, HEADER_LOGO_HEIGHT)
        header.add_run().add_picture(str(writer.theme.logo), width=Cm(width), height=Cm(height))
        header.add_run("   ")
    page_fields(writer, header, str(writer.meta.get("header", "")).strip().strip("'\"") or writer.title)
    border_bottom(header, writer.hex("rule"), 4, 4)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    note = str(writer.meta.get("footer", "")).strip().strip("'\"")
    page_fields(writer, footer, note if "{page}" in note else (note + "    " if note else "") + "Page {page} of {pages}")


# fills page, title, date, and section placeholders in footer text
def page_fields(writer, paragraph, template):
    here = writer.restarts[writer.section_no:writer.section_no + 2]
    sections = bool(any(writer.restarts[1:]) and here and here[0] and (len(here) < 2 or here[1]))
    fields = {"{page}": ("PAGE", "1"), "{pages}": ("SECTIONPAGES" if sections else "NUMPAGES", "1"), "{section}": ('STYLEREF "Heading 2"', "")}
    text = template.replace("{title}", writer.title).replace("{date}", long_date(writer.meta.get("date", "")))
    for piece in re.split(r"(\{page\}|\{pages\}|\{section\})", text):
        if piece in fields:
            add_field(paragraph, *fields[piece])
            for run in paragraph.runs[-5:]:
                run.font.size, run.font.color.rgb = Pt(8.5), writer.rgb("muted")
        elif piece:
            plain(writer, paragraph, piece, 8.5, "muted")


# gives a Word section the paper, orientation, margins, page number format and header and footer slots of a page master
def apply_master(writer, section, master, restart=False):
    top, right, bottom, left = master.margins
    section.orientation = WD_ORIENT.LANDSCAPE if master.width > master.height else WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(master.width / 10), Cm(master.height / 10)
    section.left_margin, section.right_margin, section.top_margin, section.bottom_margin = (Cm(size / 10) for size in (left, right, top, bottom))
    writer.width = (master.width - left - right) / 10
    for old in section._sectPr.findall(qn("w:pgNumType")):
        section._sectPr.remove(old)
    numbering = OxmlElement("w:pgNumType")
    numbering.set(qn("w:fmt"), NUMBER_FORMATS.get(master.numbers, "decimal"))
    if restart:
        numbering.set(qn("w:start"), "1")
    section._sectPr.find(qn("w:pgMar")).addnext(numbering)
    values = field_values(writer.styles, writer.meta)
    for part, template in ((section.header, master.header), (section.footer, master.footer)):
        if template is None:
            continue
        part.is_linked_to_previous = False
        paragraph = part.paragraphs[0]
        for child in list(paragraph._p):
            paragraph._p.remove(child)
        if template.strip().lower() == "none":
            continue
        slots = [slot.strip() for slot in (replace_fields(template, values).split("|", 2) + ["", ""])[:3]]
        paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(writer.width / 2), WD_TAB_ALIGNMENT.CENTER)
        paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(writer.width), WD_TAB_ALIGNMENT.RIGHT)
        page_fields(writer, paragraph, "\t".join(slots))


# starts a new Word section on a new page under the named page master
def master_section(writer, name, restart):
    writer.master_name = name
    writer.section_no += 1
    section = writer.document.add_section(WD_SECTION.NEW_PAGE)
    section.different_first_page_header_footer = False
    apply_master(writer, section, writer.styles.master(name), restart)


# returns the usable Word page width in centimetres
def inches_to_cm(section):
    return (section.page_width - section.left_margin - section.right_margin) / 360000


# sets document metadata, creator, and creation timestamps
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


# saves a Word document with stable ZIP metadata
def save_document(writer, output_path: Path):
    embed_fonts(writer.document, writer.used_fonts)
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

