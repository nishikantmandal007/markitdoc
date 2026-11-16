import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

import logging
from markitdoc.markup.inline import inline_runs, parser
from markitdoc.models.catalogue import Box
from markitdoc.pdf.pages import PdfPages
from markitdoc.visuals.photos import fitted_image
from markitdoc.utils.helpers import lifted
from markitdoc.themes.themes import Theme

logger = logging.getLogger(__name__)
slide_width, slide_height = 13.333, 7.5
side_margin = 0.6
content_width = round(slide_width - 2 * side_margin, 3)
title_top, title_height, rule_top = 0.4, 1.1, 1.62
body_top, body_bottom = 1.95, 6.75
body_height = body_bottom - body_top
footer_top, footer_size = 7.0, 10
text_width = 10.6
side_text_width, visual_left = 4.3, 5.4
visual_width = round(slide_width - side_margin - visual_left, 3)
title_sizes = (30, 28, 26, 24)
body_sizes = (24, 22, 20, 19, 18, 17, 16, 15, 14)
standard_size, comfortable_size, smallest_size = 20, 18, 14
line_factor, title_leading, gap_factor = 1.2, 1.12, 0.4
width_factors = {"Calibri": 1.07, "Georgia": 0.9}
bullet_indent, number_indent, level_indent = 0.34, 0.5, 0.34
bullet_marks = ("•", "–", "◦")
sentence_end = re.compile(r"(?<=[.!?])\s+")
white = (255, 255, 255)
soft_white = (226, 230, 240)
photo_width_limit = 2400
layout_title_only = 5
no_grid_table_style = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"
fonts_by_file = {"PTSerif": "Georgia"}
sans_font, mono_font = "Calibri", "Consolas"
steady_dates = re.compile(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)")
card_gap, card_presets, panel_width = 0.3, ((22, 18), (20, 16), (18, 15), (16, 14)), 4.3
brand_title_width = 11.5
leading_figure = re.compile(r"^\s*([~≈<>+\-−]?[$€£¥]?\d[\d.,]*\s?(?:%|[kKmMbBxX]\b|bn\b|tn\b|pts?\b|bps\b)?\+?)\s*(.*)$")
card_pattern = re.compile(r"^\*\*(.+?)\*\*\s*(?:—|–|:|-)\s*(.+)$")


@dataclass(frozen=True)
class Item:
    source: str
    kind: str = "paragraph"
    level: int = 0
    number: int = 0

    @property
    def listed(self):
        return self.kind in ("bullet", "number")


def office_font(path):
    return next((font for stem, font in fonts_by_file.items() if stem in Path(path).name), sans_font)


def literal(text):
    return re.sub(r"([\\`*_{}\[\]<>#~^$|])", r"\\\1", text)


def runs_of(source):
    tokens = parser.parseInline(source or "")
    return inline_runs(tokens[0]) if tokens else []


def plain_text(source):
    return "".join(run.text for run in runs_of(source)).strip()


def item_indent(item):
    if item.kind == "bullet":
        return bullet_indent * (item.level + 1)
    if item.kind == "number":
        return number_indent + level_indent * item.level
    return level_indent * item.level


def split_to_fit(items, fits):
    if len(items) < 2 or fits(items):
        return [items]
    middle = len(items) // 2
    if getattr(items[middle - 1], "kind", "") == "subheading":
        middle = middle - 1 if middle > 1 else middle + 1
    return split_to_fit(items[:middle], fits) + split_to_fit(items[middle:], fits)


class Deck:
    def __init__(self, theme: Theme, meta: dict, work_folder: Path, images: dict):
        self.presentation = Presentation(str(theme.master)) if theme.master else Presentation()
        self.presentation.slide_width = Inches(slide_width)
        self.presentation.slide_height = Inches(slide_height)
        self.theme, self.meta, self.work_folder = theme, meta, work_folder
        self.measurer = PdfPages(theme)
        self.measurer.add_page()
        self.heading_font, self.body_font = office_font(theme.fonts["heading"]), office_font(theme.fonts["body"])
        self.width_factor = min(width_factors[self.body_font], width_factors[self.heading_font])
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

    def color(self, role):
        return RGBColor(*(role if isinstance(role, tuple) else self.theme.rgb(role)))

    def lines(self, source, width, size, style=""):
        key = (source, round(width, 3), size, style)
        if key not in self.measured:
            box = Box(max(width, 0.3) * 25.4 * self.width_factor, size, 0, style)
            self.measured[key] = self.measurer.line_count(source, box) if source.strip() else 0
        return self.measured[key]

    def text_height(self, source, width, size, style="", leading=line_factor):
        return self.lines(source, width, size, style) * size * leading / 72

    def note(self, text):
        self.notes.append(text)

    def flush_notes(self):
        if self.slide is not None and self.notes:
            self.slide.notes_slide.notes_text_frame.text = "\n\n".join(self.notes)
        self.notes = []

    def new_slide(self, title=None, background="paper", footer=True, dark=False, standard=True):
        self.flush_notes()
        layout = self.presentation.slide_layouts.get_by_name(self.theme.content_layout) if self.branded else self.presentation.slide_layouts[layout_title_only]
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
            place_title(self, slide, title, white if dark else "mood" if self.branded else "ink", width=brand_title_width if self.branded else content_width)
            add_rect(self, slide, side_margin, rule_top, 1.2, 0.04, "mood", "Title rule")
        if footer or self.branded:
            draw_footer(self, slide, night)
        return slide

    def drop_slides_after(self, count):
        ids = self.presentation.slides._sldIdLst
        for slide_id in list(ids)[count:]:
            self.presentation.part.drop_rel(slide_id.rId)
            ids.remove(slide_id)
        self.slide, self.notes = None, []

    @property
    def slide_count(self):
        return len(self.presentation.slides)


def add_textbox(slide, left, top, width, height, name, anchor=MSO_ANCHOR.TOP, inset=0):
    shape = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    shape.name = name
    configure_frame(shape.text_frame, anchor, inset)
    return shape


def configure_frame(frame, anchor=MSO_ANCHOR.TOP, inset=0):
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = Inches(inset)
    frame.vertical_anchor = anchor


def add_rect(deck, slide, left, top, width, height, role, name="Shape", shape=MSO_SHAPE.RECTANGLE):
    drawn = slide.shapes.add_shape(shape, Inches(left), Inches(top), Inches(width), Inches(height))
    drawn.name = name
    drawn.fill.solid()
    drawn.fill.fore_color.rgb = deck.color(role)
    drawn.line.fill.background()
    drawn._element.remove(drawn._element.find(qn("p:style")))
    return drawn


def tint(deck, role, share):
    return lifted(deck.theme.rgb(role), share)


def add_badge(deck, slide, left, top, size, text, role="mood"):
    circle = add_rect(deck, slide, left, top, size, size, role, "Badge", MSO_SHAPE.OVAL)
    configure_frame(circle.text_frame, MSO_ANCHOR.MIDDLE, 0)
    paragraph = circle.text_frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = text
    run.font.size, run.font.bold, run.font.name = Pt(round(size * 30)), True, deck.heading_font
    run.font.color.rgb = deck.color(white)
    return circle


def card_pairs(items):
    pairs = [card_pattern.match(item.source.strip()) for item in items]
    if not 2 <= len(items) <= 6 or not all(item.listed and item.level == 0 for item in items) or not all(pairs):
        return None
    return [(match.group(1), match.group(2)) for match in pairs]


def card_columns(pairs):
    return 3 if len(pairs) in (5, 6) else len(pairs)


def card_preset(deck, pairs, height, columns=None):
    columns = columns or card_columns(pairs)
    rows = (len(pairs) + columns - 1) // columns
    width = (content_width - card_gap * (columns - 1)) / columns - 0.6
    for head, text in card_presets:
        needed = max(deck.text_height(head_text, width, head, "B") + 0.15 + deck.text_height(detail, width, text) for head_text, detail in pairs)
        if (needed + 0.8) * rows + card_gap * (rows - 1) <= height:
            return head, text, needed + 1.45
    return None


def figure_cards(pairs):
    found = [leading_figure.match(plain_text(head)) for head, _ in pairs]
    if not all(found):
        return None
    return tuple((match.group(1), match.group(2).strip(" -—:") or match.group(1), detail) for match, (_, detail) in zip(found, pairs))


def card_layouts(deck, pairs, height, preset):
    layouts = {"columns": preset} if preset else {}
    if stacked_fits(deck, pairs, height):
        layouts["rows"] = None
    grid = card_preset(deck, pairs, height, 2) if len(pairs) == 4 else None
    if grid:
        layouts["grid"] = grid
    return layouts


def draw_cards(deck, slide, pairs, top, height, preset):
    layouts = card_layouts(deck, pairs, height, preset)
    names = list(layouts)
    turn = deck.card_turn % len(names)
    pick = next((name for name in names[turn:] + names[:turn] if name != deck.last_cards), names[0])
    deck.card_turn += 1
    deck.last_cards = pick
    if pick == "rows":
        return draw_card_rows(deck, slide, pairs, top, height)
    head, text, card_height = layouts[pick]
    card_height -= 0.65
    columns = 2 if pick == "grid" else card_columns(pairs)
    rows = (len(pairs) + columns - 1) // columns
    width = (content_width - card_gap * (columns - 1)) / columns
    heading_room = max(deck.text_height(head_text, width - 0.6, head, "B") for head_text, _ in pairs)
    top += max(0.0, height - card_height * rows - card_gap * (rows - 1)) * 0.45
    for index, (head_text, detail) in enumerate(pairs):
        left = side_margin + (index % columns) * (width + card_gap)
        card_top = top + (index // columns) * (card_height + card_gap)
        add_rect(deck, slide, left, card_top, width, card_height, "surface", "Card")
        add_rect(deck, slide, left, card_top, width, 0.06, "mood", "Card accent")
        write_text(deck, slide, head_text, left + 0.3, card_top + 0.4, width - 0.6, head, "ink", bold=True, name="Card heading")
        write_text(deck, slide, detail, left + 0.3, card_top + 0.55 + heading_room, width - 0.6, text, "body", name="Card text")
    return top + card_height * rows + card_gap * (rows - 1)


def draw_takeaway(deck, slide, items, bottom):
    source = " ".join(item.source for item in items)
    height = deck.text_height(source, content_width - 0.6, 16, "B") + 0.4
    add_rect(deck, slide, side_margin, bottom - height, content_width, height, "surface", "Takeaway band")
    add_rect(deck, slide, side_margin, bottom - height, 0.07, height, "mood", "Takeaway accent")
    write_text(deck, slide, source, side_margin + 0.35, bottom - height + 0.2, content_width - 0.7, 16, "ink", bold=True, name="Takeaway")
    return height


def stacked_fits(deck, pairs, height, width=content_width):
    return sum(row_height_of(deck, head_text, detail, width) for head_text, detail in pairs) + card_gap * (len(pairs) - 1) <= height


def row_widths(width):
    head = min(3.4, width * 0.36)
    return head, width - head - 1.2


def row_height_of(deck, head_text, detail, width=content_width):
    head, text = row_widths(width)
    return max(deck.text_height(head_text, head, 18, "B"), deck.text_height(detail, text, 16)) + 0.44


def draw_card_rows(deck, slide, pairs, top, height, left=side_margin, width=content_width):
    head, text = row_widths(width)
    total = sum(row_height_of(deck, head_text, detail, width) for head_text, detail in pairs) + card_gap * (len(pairs) - 1)
    top += max(0.0, height - total) * 0.45
    for head_text, detail in pairs:
        row = row_height_of(deck, head_text, detail, width)
        add_rect(deck, slide, left, top, width, row, "surface", "Card")
        add_rect(deck, slide, left, top, 0.07, row, "mood", "Card accent")
        write_text(deck, slide, head_text, left + 0.4, top + 0.22, head, 18, "ink", bold=True, name="Card heading")
        write_text(deck, slide, detail, left + head + 0.8, top + 0.22, text, 16, "body", name="Card text")
        top += row + card_gap
    return top


def panel_fits(deck, lead_text, pairs, height):
    return deck.text_height(lead_text, panel_width - 0.8, 22) + 0.9 <= height and stacked_fits(deck, pairs, height, content_width - panel_width - card_gap)


def draw_panel(deck, slide, lead_text, pairs, top, height):
    deck.last_cards = "panel"
    add_rect(deck, slide, side_margin, top, panel_width, height, "night", "Statement panel")
    add_rect(deck, slide, side_margin, top, panel_width, 0.07, "mood", "Panel accent")
    used = deck.text_height(lead_text, panel_width - 0.8, 22)
    write_text(deck, slide, lead_text, side_margin + 0.4, top + (height - used) / 2, panel_width - 0.8, 22, white, name="Statement")
    left = side_margin + panel_width + card_gap
    draw_card_rows(deck, slide, pairs, top, height, left, content_width - panel_width - card_gap)


def set_spacing(paragraph, size, leading=line_factor, after=gap_factor):
    paragraph.line_spacing = Pt(round(size * leading, 1))
    paragraph.space_after = Pt(round(size * after, 1))


def hanging(paragraph, indent, hang):
    properties = paragraph._p.get_or_add_pPr()
    properties.set("marL", str(int(Inches(indent))))
    properties.set("indent", str(-int(Inches(hang))))
    return properties


def add_bullet(deck, properties, level):
    color = etree.SubElement(properties, qn("a:buClr"))
    etree.SubElement(color, qn("a:srgbClr"), val=str(deck.color("mood")))
    etree.SubElement(properties, qn("a:buFont"), typeface="Arial")
    etree.SubElement(properties, qn("a:buChar"), char=bullet_marks[min(level, len(bullet_marks) - 1)])


def draw_run(deck, paragraph, run, text, size, role, bold, italic, font):
    drawn = paragraph.add_run()
    drawn.text = text
    face = drawn.font
    face.name = font or deck.body_font
    face.size = Pt(size)
    face.bold = run.bold or bold
    face.italic = run.italic or italic
    face.underline = bool(run.underline or run.link)
    face.color.rgb = deck.color(run.role or role)
    properties = drawn._r.get_or_add_rPr()
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


def add_runs(deck, paragraph, source, size, role="body", bold=False, italic=False, font=None):
    for run in runs_of(source):
        for position, piece in enumerate(run.text.split("\n")):
            if position:
                paragraph.add_line_break()
            if piece:
                draw_run(deck, paragraph, run, piece, size, role, bold, italic, font)


def draw_item(deck, paragraph, item, size, role="body"):
    set_spacing(paragraph, size)
    heading = item.kind == "subheading"
    if item.kind == "bullet":
        add_bullet(deck, hanging(paragraph, item_indent(item), bullet_indent), item.level)
    elif item.kind == "number":
        hanging(paragraph, item_indent(item), number_indent)
        numeral = paragraph.add_run()
        numeral.text = f"{item.number}.\t"
        numeral.font.name, numeral.font.size, numeral.font.bold = deck.body_font, Pt(size), True
        numeral.font.color.rgb = deck.color("mood")
        etree.SubElement(paragraph._p.get_or_add_pPr(), qn("a:buNone"))
    else:
        etree.SubElement(hanging(paragraph, item_indent(item), 0), qn("a:buNone"))
    add_runs(deck, paragraph, item.source, size, "ink" if heading else role, bold=heading, italic=item.kind == "quote",
             font=deck.heading_font if heading else None)


def item_height(deck, item, width, size):
    lines = deck.lines(item.source, width - item_indent(item), size, "B" if item.kind == "subheading" else "")
    return lines * size * line_factor / 72 + size * gap_factor / 72


def stack_height(deck, items, width, size):
    return sum(item_height(deck, item, width, size) for item in items)


def write_items(deck, slide, items, left, top, width, size, role="body", name="Body"):
    height = stack_height(deck, items, width, size)
    frame = add_textbox(slide, left, top, width, height, name).text_frame
    for position, item in enumerate(items):
        draw_item(deck, frame.paragraphs[0] if position == 0 else frame.add_paragraph(), item, size, role)
    return height


def write_text(deck, slide, source, left, top, width, size, role="body", bold=False, italic=False, heading=False,
               align=PP_ALIGN.LEFT, name="Text", leading=line_factor, height=None, anchor=MSO_ANCHOR.TOP):
    bold = bold or heading
    used = deck.text_height(source, width, size, "B" if bold else "", leading)
    shape = add_textbox(slide, left, top, width, height or used, name, anchor)
    paragraph = shape.text_frame.paragraphs[0]
    paragraph.alignment = align
    set_spacing(paragraph, size, leading, 0)
    add_runs(deck, paragraph, source, size, role, bold, italic, deck.heading_font if heading else None)
    return used


def title_fit(deck, source, width, sizes, lines, style):
    for size in sizes:
        if deck.lines(source, width, size, style) <= lines:
            return size, source
    words = source.split()
    while len(words) > 1 and deck.lines(" ".join(words) + "…", width, sizes[-1], style) > lines:
        words.pop()
    deck.note(f"Full title: {source}")
    return sizes[-1], " ".join(words) + "…"


def place_title(deck, slide, source, role, left=side_margin, top=title_top, width=content_width, height=title_height,
                sizes=title_sizes, lines=2, anchor=MSO_ANCHOR.BOTTOM, bold=True, italic=False, align=PP_ALIGN.LEFT):
    style = "B" if bold else ""
    size, shown = title_fit(deck, source, width, sizes, lines, style)
    shape = slide.shapes.title
    shape.name = "Title"
    shape.left, shape.top, shape.width, shape.height = Inches(left), Inches(top), Inches(width), Inches(height)
    configure_frame(shape.text_frame, anchor)
    paragraph = shape.text_frame.paragraphs[0]
    paragraph.alignment = align
    set_spacing(paragraph, size, title_leading, 0)
    add_runs(deck, paragraph, shown, size, role, bold=bold, italic=italic, font=deck.heading_font)
    return size, deck.text_height(shown, width, size, style, title_leading)


def draw_brand_footer(deck, slide, dark):
    role = soft_white if dark else "muted"
    write_text(deck, slide, literal(deck.theme.footer_text), side_margin, footer_top, 6.2, footer_size, role, name="Footer")
    write_text(deck, slide, literal(deck.theme.header_note), 6.9, footer_top, 4.8, footer_size, role, align=PP_ALIGN.RIGHT, name="Footer note")
    if deck.slide_count > 1:
        write_text(deck, slide, str(deck.slide_count), slide_width - side_margin - 1.0, footer_top, 1.0, footer_size, role, align=PP_ALIGN.RIGHT,
                   name="Slide number")


def draw_footer(deck, slide, dark=False):
    if deck.branded:
        return draw_brand_footer(deck, slide, dark)
    label = deck.title
    while len(label) > 1 and deck.lines(literal(label), 9.4, footer_size) > 1:
        label = label[:-2].rstrip() + "…"
    write_text(deck, slide, literal(label), side_margin, footer_top, 9.4, footer_size, "muted", name="Footer")
    write_text(deck, slide, str(deck.slide_count), slide_width - side_margin - 1.0, footer_top, 1.0, footer_size, "muted",
               align=PP_ALIGN.RIGHT, name="Slide number")


def key_sentences(deck, source, width, height, size):
    kept = []
    for sentence in sentence_end.split(source.strip()):
        if deck.text_height(" ".join(kept + [sentence]), width, size) > height:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    words = source.split()
    while len(words) > 1 and deck.text_height(" ".join(words) + "…", width, size) > height:
        words.pop()
    return " ".join(words) + "…"


def fitting_size(deck, items, width, height, sizes=body_sizes, cap=standard_size):
    return next((size for size in sizes if size <= cap and stack_height(deck, items, width, size) <= height), None)


def roomy_cap(deck, items, width, height):
    return 24 if stack_height(deck, items, width, 24) <= height * 0.6 and len(items) <= 5 else standard_size


def fitted_items(deck, items, width, height, label):
    cap = roomy_cap(deck, items, width, height)
    size = fitting_size(deck, items, width, height, cap=cap)
    if size:
        return items, size
    size = comfortable_size - 2
    shown = [Item(key_sentences(deck, item.source, width - item_indent(item), height / len(items), size), item.kind, item.level,
                  item.number) for item in items]
    deck.note(f"{label}: " + " ".join(item.source for item in items))
    return shown, size


def send_to_back(slide, picture):
    slide.shapes._spTree.insert(2, picture._element)


def add_image(slide, source, left, top, width, height, alt, name="Picture"):
    picture = slide.shapes.add_picture(source, Inches(left), Inches(top), Inches(width), Inches(height))
    picture.name = name
    picture._element.nvPicPr.cNvPr.set("descr", alt)
    return picture


def image_ratio(source):
    with Image.open(source) as picture:
        return picture.width / picture.height


def contained(ratio, left, top, width, height):
    drawn_width, drawn_height = (width, width / ratio) if width / height < ratio else (height * ratio, height)
    return left + (width - drawn_width) / 2, top + (height - drawn_height) / 2, drawn_width, drawn_height


def overlay(deck, top, bottom, start=0.0):
    return ((start, 1.0, top, bottom, deck.theme.rgb("night")),)


def full_bleed(deck, slide, image, fades, alt):
    picture = add_image(slide, photo_for(deck, image[0], slide_width, slide_height, fades), 0, 0, slide_width, slide_height, alt,
                        "Background photo")
    send_to_back(slide, picture)
    write_text(deck, slide, literal(image[2]), slide_width - side_margin - 6, 7.05, 6, 10, soft_white, align=PP_ALIGN.RIGHT, name="Credit")


def half_bleed(deck, slide, image, alt):
    side = deck.photo_side
    deck.photo_side = "left" if side == "right" else "right"
    half = slide_width / 2
    left = half if side == "right" else 0
    add_image(slide, photo_for(deck, image[0], half, slide_height, overlay(deck, 0.0, 0.6, 0.82)), left, 0, half, slide_height, alt,
              "Side photo")
    write_text(deck, slide, literal(image[2]), left + 0.3, 7.05, half - 0.6, 10, soft_white, align=PP_ALIGN.RIGHT, name="Credit")
    return (side_margin if side == "right" else half + 0.6), half - 1.2


def side_title(deck, slide, title, left, width, role="ink"):
    size, height = place_title(deck, slide, title, role, left, 0.65, width, 2.2, title_sizes + (22, 20), 4, MSO_ANCHOR.TOP)
    add_rect(deck, slide, left, 0.65 + height + 0.18, 1.2, 0.04, "mood", "Title rule")
    return 0.65 + height + 0.55


def write_column(deck, slide, items, left, top, width, bottom, label="Full text"):
    if not items:
        return top
    shown, size = fitted_items(deck, list(items), width, max(0.8, bottom - top), label)
    return top + write_items(deck, slide, shown, left, top, width, size)


def photo_for(deck, path, width, height, fades=()):
    fitted = Path(fitted_image(Path(path), width * 100, height * 100, deck.work_folder, fades, deck.photos, deck.theme))
    with Image.open(fitted) as picture:
        if picture.width > photo_width_limit:
            picture.resize((photo_width_limit, round(picture.height * photo_width_limit / picture.width)), Image.LANCZOS).save(
                fitted, "JPEG", quality=88)
    return str(fitted)


def add_fade(slide):
    element = slide._element
    transition = etree.Element(qn("p:transition"), spd="fast")
    etree.SubElement(transition, qn("p:fade"))
    anchor = element.find(qn("p:clrMapOvr"))
    (anchor if anchor is not None else element.find(qn("p:cSld"))).addnext(transition)


def save_presentation(presentation, output_path: Path):
    buffer = io.BytesIO()
    presentation.save(buffer)
    output_path.write_bytes(steady_zip(buffer.getvalue()))


def steady_zip(content):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in sorted(source.infolist(), key=lambda item: item.filename) if content[:2] == b"PK" and is_workbook(source) else source.infolist():
            data = source.read(info.filename)
            if info.filename.endswith(".xlsx"):
                data = steady_zip(data)
            elif info.filename == "docProps/core.xml" and is_workbook(source):
                data = steady_dates.sub(rb"\g<1>2000-01-01T00:00:00Z\g<2>", data)
            entry = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type, entry.external_attr = zipfile.ZIP_DEFLATED, info.external_attr
            target.writestr(entry, data)
    return output.getvalue()


def is_workbook(archive):
    return "xl/workbook.xml" in archive.namelist()
