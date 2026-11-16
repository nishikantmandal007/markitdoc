from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

page_width, page_height, side_margin, top_margin = 21.0, 29.7, 2.2, 2.4
text_width = page_width - 2 * side_margin
body_size, small_size = 11, 9
heading_sizes = {1: 22, 2: 16, 3: 13, 4: 11.5}


# sets the Word page size, margins, and orientation
def setup_page(writer):
    section = writer.document.sections[0]
    section.page_width, section.page_height = Cm(page_width), Cm(page_height)
    section.left_margin = section.right_margin = Cm(side_margin)
    section.top_margin, section.bottom_margin = Cm(top_margin), Cm(2.2)
    section.header_distance = section.footer_distance = Cm(1.1)


# sets a Word style font from the document theme
def style_font(style, writer, size, role="body", bold=False, italic=False, heading=False):
    font = style.font
    font.name, font.size, font.bold, font.italic = writer.heading_font if heading else writer.body_font, Pt(size), bold, italic
    font.color.rgb = writer.rgb(role)
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for key in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(key), font.name)


# sets paragraph spacing and line height for a Word style
def style_spacing(style, before, after, line=1.15, keep=False):
    form = style.paragraph_format
    form.space_before, form.space_after, form.line_spacing = Pt(before), Pt(after), line
    form.keep_with_next = keep
    form.widow_control = True


# creates or updates a named Word paragraph style
def paragraph_style(writer, name, base="Normal"):
    styles = writer.document.styles
    if name in [style.name for style in styles]:
        return styles[name]
    style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = styles[base]
    style.quick_style = True
    return style


# configures the document paragraph, heading, and table styles
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


# removes all visible borders from a Word table
def remove_borders(style):
    properties = style.element.find(qn("w:pPr"))
    if properties is not None:
        for border in properties.findall(qn("w:pBdr")):
            properties.remove(border)


# adds a colored left border to a Word paragraph
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


# adds a colored bottom border to a Word paragraph
def border_bottom(paragraph, color, size=6, space=4):
    properties = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    edge = OxmlElement("w:bottom")
    for key, value in (("w:val", "single"), ("w:sz", str(size)), ("w:space", str(space)), ("w:color", color)):
        edge.set(qn(key), value)
    borders.append(edge)
    properties.append(borders)


# sets the background shading for a Word table style
def shade_style(element, color):
    shading = OxmlElement("w:shd")
    for key, value in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", color)):
        shading.set(qn(key), value)
    element.get_or_add_pPr().append(shading)


# sets the background color of a Word table cell
def cell_fill(cell, color):
    properties = cell._tc.get_or_add_tcPr()
    for old in properties.findall(qn("w:shd")):
        properties.remove(old)
    shading = OxmlElement("w:shd")
    for key, value in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", color)):
        shading.set(qn(key), value)
    properties.append(shading)


# sets the requested border edges on a Word table cell
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


# sets the inside margins of a Word table cell
def cell_margins(cell, top=0.12, side=0.2, bottom=0.12):
    properties = cell._tc.get_or_add_tcPr()
    margins = OxmlElement("w:tcMar")
    for name, value in (("top", top), ("left", side), ("bottom", bottom), ("right", side)):
        edge = OxmlElement(f"w:{name}")
        edge.set(qn("w:w"), str(int(value * 567)))
        edge.set(qn("w:type"), "dxa")
        margins.append(edge)
    properties.append(margins)


# creates and formats a Word table with the requested column widths
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


# keeps a paragraph with the following paragraph
def keep_together(table):
    for row in table.rows[:-1]:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.keep_with_next = True


# prevents a Word table row from splitting across pages
def never_split(row):
    properties = row._tr.get_or_add_trPr()
    keep = OxmlElement("w:cantSplit")
    properties.append(keep)


# marks a Word table row as a repeating page header
def repeat_header(row):
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    properties.append(header)
