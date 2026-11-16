import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from markitdoc.markup.inline import literal, runs_of
from markitdoc.models.catalogue import Box
from markitdoc.pdf.pages import PdfPages
from markitdoc.themes.themes import Theme
from markitdoc.utils.helpers import MONO_FONT, lifted, office_font

SLIDE_WIDTH, SLIDE_HEIGHT = 13.333, 7.5
SIDE_MARGIN = 0.6
CONTENT_WIDTH = round(SLIDE_WIDTH - 2 * SIDE_MARGIN, 3)
TITLE_TOP, TITLE_HEIGHT, RULE_TOP = 0.4, 1.1, 1.62
BODY_TOP, BODY_BOTTOM = 1.95, 6.75
BODY_HEIGHT = BODY_BOTTOM - BODY_TOP
FOOTER_TOP, FOOTER_SIZE = 7.0, 10
TEXT_WIDTH = 10.6
SIDE_TEXT_WIDTH, VISUAL_LEFT = 4.3, 5.4
VISUAL_WIDTH = round(SLIDE_WIDTH - SIDE_MARGIN - VISUAL_LEFT, 3)
TITLE_SIZES = (30, 28, 26, 24)
BODY_SIZES = (24, 22, 20, 19, 18, 17, 16, 15, 14)
STANDARD_SIZE, COMFORTABLE_SIZE, SMALLEST_SIZE = 20, 18, 14
LINE_FACTOR, TITLE_LEADING, GAP_FACTOR = 1.2, 1.12, 0.4
WIDTH_FACTORS = {"Calibri": 1.07, "Georgia": 0.9}
BULLET_INDENT, NUMBER_INDENT, LEVEL_INDENT = 0.34, 0.5, 0.34
BULLET_MARKS = ("•", "–", "◦")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
WHITE = (255, 255, 255)
SOFT_WHITE = (226, 230, 240)
LAYOUT_TITLE_ONLY = 5
NO_GRID_TABLE_STYLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"
BRAND_TITLE_WIDTH = 11.5
ENGINE_SOURCE = "engine default"
SLIDE_ALIGNS = {"L": PP_ALIGN.LEFT, "C": PP_ALIGN.CENTER, "R": PP_ALIGN.RIGHT, "J": PP_ALIGN.JUSTIFY}


@dataclass(frozen=True)
class Item:
    source: str
    kind: str = "paragraph"
    level: int = 0
    number: int = 0
    look: object = field(default=None, compare=False)

    # checks whether a slide item is a bullet or number
    @property
    def listed(self):
        return self.kind in ("bullet", "number")


# returns the left indent for a bullet, number, or paragraph
def item_indent(item):
    if item.kind == "bullet":
        return BULLET_INDENT * (item.level + 1)
    if item.kind == "number":
        return NUMBER_INDENT + LEVEL_INDENT * item.level
    return LEVEL_INDENT * item.level


# splits items into groups that satisfy a layout constraint
def split_to_fit(items, fits):
    if len(items) < 2 or fits(items):
        return [items]
    middle = len(items) // 2
    if getattr(items[middle - 1], "kind", "") == "subheading":
        middle = middle - 1 if middle > 1 else middle + 1
    return split_to_fit(items[:middle], fits) + split_to_fit(items[middle:], fits)


class Deck:
    # sets up the rendering context and its document settings
    def __init__(self, theme: Theme, meta: dict, work_folder: Path, images: dict, styles=None, numbering=None):
        self.presentation = Presentation(str(theme.master)) if theme.master else Presentation()
        self.presentation.slide_width = Inches(SLIDE_WIDTH)
        self.presentation.slide_height = Inches(SLIDE_HEIGHT)
        self.theme, self.meta, self.work_folder = theme, meta, work_folder
        self.styles, self.numbers = styles, numbering.targets
        self.title_look = self.look("h2")
        self.measurer = PdfPages(theme)
        self.measurer.add_page()
        self.heading_font, self.body_font = office_font(theme.fonts["heading"]), office_font(theme.fonts["body"])
        self.width_factor = min(WIDTH_FACTORS[self.body_font], WIDTH_FACTORS[self.heading_font])
        self.figures = {key[1]: value for key, value in images.items() if isinstance(key, tuple)}
        self.photos_by_block = {key: value for key, value in images.items() if not isinstance(key, tuple)}
        self.photos = str(meta.get("photos", "natural")).lower()
        self.table_style = str(meta.get("tables", "lined")).lower()
        self.title, self.section_title, self.slide, self.notes, self.footnotes = "", "", None, [], []
        self.measured = {}
        self.photo_side, self.card_turn, self.last_cards = "right", 0, ""
        self.branded = theme.master is not None
        if self.branded:
            self.drop_slides_after(1)

    # the look of an element under the stylesheet limited to what a slide obeys
    def look(self, selector=None, classes=(), inline=None, context=None):
        found = self.styles.resolve(selector, classes, inline, None, "", context)
        return self.scaled(self.styles.style_of({key: item for key, item in found.items()
                                                 if item[1] != ENGINE_SOURCE and not (key == "size" and item[1].endswith(":text"))}))

    # a look with its size scaled from the print body size to the slide body size, so print sizes keep their relative size on slides
    def scaled(self, look):
        return replace(look, size=look.size * STANDARD_SIZE / self.styles.base) if look.size else look

    # a span's look from its own class and raw key pairs, inheriting from the paragraph look
    def span_look(self, pairs, parent):
        return self.scaled(self.styles.span_look(pairs, parent))

    # the PowerPoint font name for a look's font: a theme role or a declared font
    def font_named(self, name):
        if name == "heading":
            return self.heading_font
        return MONO_FONT if name == "mono" else self.styles.faces[name].family if name in self.styles.faces else self.body_font

    # returns a theme color as a PowerPoint color value
    def color(self, role):
        return RGBColor(*(role if isinstance(role, tuple) else self.theme.rgb(role)))

    # measures and caches how many lines text needs at a given width
    def lines(self, source, width, size, style=""):
        key = (source, round(width, 3), size, style)
        if key not in self.measured:
            box = Box(max(width, 0.3) * 25.4 * self.width_factor, size, 0, style)
            self.measured[key] = self.measurer.line_count(source, box) if source.strip() else 0
        return self.measured[key]

    # measures the height needed for text on a slide
    def text_height(self, source, width, size, style="", leading=LINE_FACTOR):
        return self.lines(source, width, size, style) * size * leading / 72

    # queues text to be added to the current slide notes
    def note(self, text):
        self.notes.append(text)

    # writes queued notes to the current slide before it changes
    def flush_notes(self):
        if self.slide is not None and self.notes:
            self.slide.notes_slide.notes_text_frame.text = "\n\n".join(self.notes)
        self.notes = []

    # creates and styles a slide with its title and footer
    def new_slide(self, title=None, background="paper", footer=True, dark=False, standard=True):
        self.flush_notes()
        layout = self.presentation.slide_layouts.get_by_name(self.theme.content_layout) if self.branded else self.presentation.slide_layouts[LAYOUT_TITLE_ONLY]
        slide = self.presentation.slides.add_slide(layout)
        fill = slide.background.fill
        if background == "night":
            fill.gradient()
            fill.gradient_angle = 35
            fill.gradient_stops[0].color.rgb = self.color("night")
            fill.gradient_stops[1].color.rgb = self.color(tuple(int(dark + (bright - dark) * 0.45) for dark, bright in
                                                                 zip(self.theme.rgb("night"), self.theme.rgb("mood"))))
        else:
            fill.solid()
            fill.fore_color.rgb = self.color(background)
        self.slide = slide
        night = background != "paper"
        if self.branded and night:
            slide._element.set("showMasterSp", "0")
        if title is not None and standard:
            place_title(self, slide, title, WHITE if dark else "mood" if self.branded else "ink", width=BRAND_TITLE_WIDTH if self.branded else CONTENT_WIDTH,
                        look=self.title_look)
            add_rect(self, slide, SIDE_MARGIN, RULE_TOP, 1.2, 0.04, "mood", "Title rule")
        if footer or self.branded:
            draw_footer(self, slide, night)
        return slide

    # removes slides after the requested slide count
    def drop_slides_after(self, count):
        ids = self.presentation.slides._sldIdLst
        for slide_id in list(ids)[count:]:
            self.presentation.part.drop_rel(slide_id.rId)
            ids.remove(slide_id)
        self.slide, self.notes = None, []

    # returns the number of slides in the presentation
    @property
    def slide_count(self):
        return len(self.presentation.slides)


# creates a named slide text box with the requested frame settings
def add_textbox(slide, left, top, width, height, name, anchor=MSO_ANCHOR.TOP, inset=0):
    shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    shape.name = name
    configure_frame(shape.text_frame, anchor, inset)
    return shape


# sets wrapping, margins, and vertical alignment for a text frame
def configure_frame(frame, anchor=MSO_ANCHOR.TOP, inset=0):
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = Inches(inset)
    frame.vertical_anchor = anchor


# adds a filled and named shape to a slide
def add_rect(deck, slide, left, top, width, height, role, name="Shape", shape=MSO_SHAPE.RECTANGLE):
    drawn = slide.shapes.add_shape(shape, Inches(left), Inches(top), Inches(width), Inches(height))
    drawn.name = name
    drawn.fill.solid()
    drawn.fill.fore_color.rgb = deck.color(role)
    drawn.line.fill.background()
    drawn._element.remove(drawn._element.find(qn("p:style")))
    return drawn


# lightens a theme color by the requested share
def tint(deck, role, share):
    return lifted(deck.theme.rgb(role), share)


# draws a centered circular label on a slide
def add_badge(deck, slide, left, top, size, text, role="mood"):
    circle = add_rect(deck, slide, left, top, size, size, role, "Badge", MSO_SHAPE.OVAL)
    configure_frame(circle.text_frame, MSO_ANCHOR.MIDDLE, 0)
    paragraph = circle.text_frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = text
    run.font.size, run.font.bold, run.font.name = Pt(round(size * 30)), True, deck.heading_font
    run.font.color.rgb = deck.color(WHITE)
    return circle


# sets paragraph line spacing and space after
def set_spacing(paragraph, size, leading=LINE_FACTOR, after=GAP_FACTOR):
    paragraph.line_spacing = Pt(round(size * leading, 1))
    paragraph.space_after = Pt(round(size * after, 1))


# sets the left and hanging indents for a paragraph
def hanging(paragraph, indent, hang):
    properties = paragraph._p.get_or_add_pPr()
    properties.set("marL", str(int(Inches(indent))))
    properties.set("indent", str(-int(Inches(hang))))
    return properties


# sets the color, font, and character for a bullet list item
def add_bullet(deck, properties, level):
    color = etree.SubElement(properties, qn("a:buClr"))
    etree.SubElement(color, qn("a:srgbClr"), val=str(deck.color("mood")))
    etree.SubElement(properties, qn("a:buFont"), typeface="Arial")
    etree.SubElement(properties, qn("a:buChar"), char=BULLET_MARKS[min(level, len(BULLET_MARKS) - 1)])


# adds one styled text run to a PowerPoint paragraph
def draw_run(deck, paragraph, run, text, size, role, bold, italic, font, look=None):
    mine = deck.span_look(run.style, look) if look and run.style else look
    drawn = paragraph.add_run()
    drawn.text = text
    face = drawn.font
    face.name = deck.font_named(mine.font) if mine and mine.font else font or deck.body_font
    face.size = Pt(mine.size if mine and mine.size else size)
    face.bold = run.bold or bold
    face.italic = run.italic or italic
    face.underline = bool(run.underline or run.link)
    face.color.rgb = RGBColor(*mine.rgb) if mine and mine.rgb and not run.role else deck.color(run.role or role)
    if mine and mine.bold is not None and not run.bold:
        face.bold = mine.bold
    if mine and mine.italic is not None and not run.italic:
        face.italic = mine.italic
    properties = drawn._r.get_or_add_rPr()
    if mine and mine.caps:
        properties.set("cap", mine.caps)
    if mine and mine.tracking:
        properties.set("spc", str(round(mine.tracking * 100)))
    if run.strike:
        properties.set("strike", "sngStrike")
    if run.script:
        properties.set("baseline", "30000" if run.script == "SUP" else "-25000")
    if run.highlight:
        mark = etree.Element(qn("a:highlight"))
        etree.SubElement(mark, qn("a:srgbClr"), val="FDE68A")
        later = next((child for child in properties if child.tag in (qn("a:latin"), qn("a:ea"), qn("a:cs"), qn("a:hlinkClick"))), None)
        properties.insert(list(properties).index(later), mark) if later is not None else properties.append(mark)
    if run.link:
        drawn.hyperlink.address = run.link


# adds formatted inline text to a PowerPoint paragraph
def add_runs(deck, paragraph, source, size, role="body", bold=False, italic=False, font=None, look=None):
    for run in runs_of(source):
        for position, piece in enumerate(run.text.split("\n")):
            if position:
                paragraph.add_line_break()
            if piece:
                draw_run(deck, paragraph, run, piece, size, role, bold, italic, font, look)


# formats a paragraph as a heading, bullet, number, or text item
def draw_item(deck, paragraph, item, size, role="body"):
    size = item.look.size if item.look and item.look.size else size
    set_spacing(paragraph, size)
    if item.look and item.look.align:
        paragraph.alignment = SLIDE_ALIGNS[item.look.align]
    heading = item.kind == "subheading"
    if item.kind == "bullet":
        add_bullet(deck, hanging(paragraph, item_indent(item), BULLET_INDENT), item.level)
    elif item.kind == "number":
        hanging(paragraph, item_indent(item), NUMBER_INDENT)
        numeral = paragraph.add_run()
        numeral.text = f"{item.number}.\t"
        numeral.font.name, numeral.font.size, numeral.font.bold = deck.body_font, Pt(size), True
        numeral.font.color.rgb = deck.color("mood")
        etree.SubElement(paragraph._p.get_or_add_pPr(), qn("a:buNone"))
    else:
        etree.SubElement(hanging(paragraph, item_indent(item), 0), qn("a:buNone"))
    add_runs(deck, paragraph, item.source, size, "ink" if heading else role, bold=heading, italic=item.kind == "quote",
             font=deck.heading_font if heading else None, look=item.look)


# measures the height needed for one slide text item
def item_height(deck, item, width, size):
    size = item.look.size if item.look and item.look.size else size
    lines = deck.lines(item.source, width - item_indent(item), size, "B" if item.kind == "subheading" else "")
    return lines * size * LINE_FACTOR / 72 + size * GAP_FACTOR / 72


# measures the combined height of slide text items
def stack_height(deck, items, width, size):
    return sum(item_height(deck, item, width, size) for item in items)


# draws a sequence of formatted items in a slide text box
def write_items(deck, slide, items, left, top, width, size, role="body", name="Body"):
    height = stack_height(deck, items, width, size)
    fill_items(deck, add_textbox(slide, left, top, width, height, name).text_frame, items, size, role)
    return height


# writes formatted items into the paragraphs of a text frame
def fill_items(deck, frame, items, size, role="body"):
    for position, item in enumerate(items):
        draw_item(deck, frame.paragraphs[0] if position == 0 else frame.add_paragraph(), item, size, role)


# draws fitted text in a named slide text box
def write_text(deck, slide, source, left, top, width, size, role="body", bold=False, italic=False, heading=False,
               align=PP_ALIGN.LEFT, name="Text", leading=LINE_FACTOR, height=None, anchor=MSO_ANCHOR.TOP):
    bold = bold or heading
    used = deck.text_height(source, width, size, "B" if bold else "", leading)
    shape = add_textbox(slide, left, top, width, height or used, name, anchor)
    paragraph = shape.text_frame.paragraphs[0]
    paragraph.alignment = align
    set_spacing(paragraph, size, leading, 0)
    add_runs(deck, paragraph, source, size, role, bold, italic, deck.heading_font if heading else None)
    return used


# fits a title to its line limit and records the full text if shortened
def title_fit(deck, source, width, sizes, lines, style):
    for size in sizes:
        if deck.lines(source, width, size, style) <= lines:
            return size, source
    words = source.split()
    while len(words) > 1 and deck.lines(" ".join(words) + "…", width, sizes[-1], style) > lines:
        words.pop()
    deck.note(f"Full title: {source}")
    return sizes[-1], " ".join(words) + "…"


# sets and draws the title placeholder on a slide
def place_title(deck, slide, source, role, left=SIDE_MARGIN, top=TITLE_TOP, width=CONTENT_WIDTH, height=TITLE_HEIGHT,
                sizes=TITLE_SIZES, lines=2, anchor=MSO_ANCHOR.BOTTOM, bold=True, italic=False, align=PP_ALIGN.LEFT, look=None):
    bold = look.bold if look and look.bold is not None else bold
    look = replace(look, size=min(max(look.size, min(TITLE_SIZES)), max(TITLE_SIZES))) if look and look.size else look
    sizes = (look.size,) if look and look.size else sizes
    align = SLIDE_ALIGNS[look.align] if look and look.align else align
    style = "B" if bold else ""
    size, shown = title_fit(deck, source, width, sizes, lines, style)
    shape = slide.shapes.title
    shape.name = "Title"
    shape.left, shape.top, shape.width, shape.height = Inches(left), Inches(top), Inches(width), Inches(height)
    configure_frame(shape.text_frame, anchor)
    paragraph = shape.text_frame.paragraphs[0]
    paragraph.alignment = align
    set_spacing(paragraph, size, TITLE_LEADING, 0)
    add_runs(deck, paragraph, shown, size, role, bold=bold, italic=italic, font=deck.heading_font, look=look)
    return size, deck.text_height(shown, width, size, style, TITLE_LEADING)


# draws the branded footer and slide number
def draw_brand_footer(deck, slide, dark):
    role = SOFT_WHITE if dark else "muted"
    write_text(deck, slide, literal(deck.theme.footer_text), SIDE_MARGIN, FOOTER_TOP, 6.2, FOOTER_SIZE, role, name="Footer")
    write_text(deck, slide, literal(deck.theme.header_note), 6.9, FOOTER_TOP, 4.8, FOOTER_SIZE, role, align=PP_ALIGN.RIGHT, name="Footer note")
    if deck.slide_count > 1:
        write_text(deck, slide, str(deck.slide_count), SLIDE_WIDTH - SIDE_MARGIN - 1.0, FOOTER_TOP, 1.0, FOOTER_SIZE, role, align=PP_ALIGN.RIGHT,
                   name="Slide number")


# draws the branded or plain footer and slide number
def draw_footer(deck, slide, dark=False):
    if deck.branded:
        return draw_brand_footer(deck, slide, dark)
    label = deck.title
    while len(label) > 1 and deck.lines(literal(label), 9.4, FOOTER_SIZE) > 1:
        label = label[:-2].rstrip() + "…"
    write_text(deck, slide, literal(label), SIDE_MARGIN, FOOTER_TOP, 9.4, FOOTER_SIZE, "muted", name="Footer")
    write_text(deck, slide, str(deck.slide_count), SLIDE_WIDTH - SIDE_MARGIN - 1.0, FOOTER_TOP, 1.0, FOOTER_SIZE, "muted",
               align=PP_ALIGN.RIGHT, name="Slide number")


# keeps as much source text as fits within the available height
def key_sentences(deck, source, width, height, size):
    kept = []
    for sentence in SENTENCE_END.split(source.strip()):
        if deck.text_height(" ".join(kept + [sentence]), width, size) > height:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    words = source.split()
    low, high = 1, len(words)
    while low < high:
        middle = (low + high + 1) // 2
        if deck.text_height(" ".join(words[:middle]) + "…", width, size) > height:
            high = middle - 1
        else:
            low = middle
    return " ".join(words[:low]) + "…"


# chooses the largest text size that fits the available height
def fitting_size(deck, items, width, height, sizes=BODY_SIZES, cap=STANDARD_SIZE):
    return next((size for size in sizes if size <= cap and stack_height(deck, items, width, size) <= height), None)


# raises the text size limit when a short list has ample space
def roomy_cap(deck, items, width, height):
    return 24 if stack_height(deck, items, width, 24) <= height * 0.6 and len(items) <= 5 else STANDARD_SIZE


# fits list text to a slide and records any shortened content
def fitted_items(deck, items, width, height, label):
    cap = roomy_cap(deck, items, width, height)
    size = fitting_size(deck, items, width, height, cap=cap)
    if size:
        return items, size
    size = COMFORTABLE_SIZE - 2
    shown = [replace(item, source=key_sentences(deck, item.source, width - item_indent(item), height / len(items), size)) for item in items]
    deck.note(f"{label}: " + " ".join(item.source for item in items))
    return shown, size


# fits and draws slide items inside a text column
def write_column(deck, slide, items, left, top, width, bottom, label="Full text"):
    if not items:
        return top
    shown, size = fitted_items(deck, list(items), width, max(0.8, bottom - top), label)
    return top + write_items(deck, slide, shown, left, top, width, size)


