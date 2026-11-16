import re
from functools import lru_cache

import pyphen
from fpdf.enums import MethodReturnValue, XPos, YPos

from markitdoc.markup.inline import SUPERSCRIPT_DIGITS
from markitdoc.pdf.pages import PdfPages
from markitdoc.utils.helpers import lifted

BODY_SIZE, TABLE_SIZE = 11, 9
MARGIN = 25
HIGHLIGHT_LINK = "§highlight"
HYPHENATION_LANGUAGES = {"en": "en_GB", "de": "de_DE", "fr": "fr", "es": "es"}
LONG_WORD = re.compile(r"[^\W\d_]{7,}")


# loads the hyphenation dictionary for a supported language
@lru_cache(maxsize=8)
def hyphenator(lang):
    return pyphen.Pyphen(lang=HYPHENATION_LANGUAGES.get(lang.split("-")[0].split("_")[0], "en_GB"))


# checks whether a language has a hyphenation dictionary
def can_hyphenate(lang):
    return (lang or "en").split("-")[0].split("_")[0] in HYPHENATION_LANGUAGES


# adds soft hyphens to long words outside markdown links
def hyphenated(text, lang):
    if not can_hyphenate(lang):
        return text
    dictionary = hyphenator(lang or "en")
    pieces = re.split(r"(\]\([^)]*\))", text)
    return "".join(piece if piece.startswith("](") else LONG_WORD.sub(lambda word: dictionary.inserted(word.group(0), hyphen="\u00ad"), piece)
                   for piece in pieces)


class FlowPages(PdfPages):
    # sets up the rendering context and its document settings
    def __init__(self, theme, title, plain):
        super().__init__(theme)
        self.document_title, self.plain, self.decorate = title, plain, True
        self.table_style = "lined"
        self.flow_images, self.figure_count, self.table_count = {}, 0, 0
        self.back_to_portrait = False
        self.highlights = []
        self.lang, self.narrow = "en", False
        self.spacing, self.measuring = 1.0, False
        self.page_notes, self.notes_at_page_bottom = {}, False
        self.targets, self.headings, self.numbering = frozenset(), [0, 0, 0, 0], False
        self.header_text, self.footer_text, self.meta_date = "", "", ""
        self.pending_caption, self.current_section, self.classification, self.watermark = "", "", "", ""
        self.scale = 1.0
        self.flow_pages = set()
        self.set_auto_page_break(True, margin=22)
        self.set_margins(MARGIN, 20, MARGIN)

    # saves highlight link positions or adds an ordinary PDF link
    def link(self, x, y, w, h, link, *args, **kwargs):
        if link == HIGHLIGHT_LINK:
            self.highlights.append((self.page, x, y, w, h))
            return None
        return super().link(x, y, w, h, link, *args, **kwargs)

    # paints saved highlight rectangles on their original PDF pages
    def paint_highlights(self):
        current = self.page
        for page, x, y, w, h in self.highlights:
            self.page = page
            with self.local_context(fill_opacity=0.55, blend_mode="Multiply"):
                self.set_fill_color(*lifted(self.theme.rgb("mood"), 0.72))
                self.rect(x - 0.4, y - 0.5, w + 0.8, h + 0.9, "F")
        self.page, self.highlights = current, []

    # adds a page and resets portrait tracking when needed
    def add_page(self, *args, **kwargs):
        super().add_page(*args, **kwargs)
        if self.auto_page_break and self.decorate:
            self.set_auto_page_break(True, margin=22)
        if self.w < self.h:
            self.back_to_portrait = False

    # returns the usable horizontal width inside the page margins
    @property
    def area(self):
        return self.w - self.l_margin - self.r_margin

    # draws the running header and records decorated flow pages
    def header(self):
        if self.decorate:
            self.flow_pages.add(self.page_no())
            self.fill_page("paper")
        if self.plain or not self.decorate or self.page_no() == 1:
            return
        self.set_font("Brand", "I" if self.theme.header_note else "B", 7.5)
        self.set_text_color(*self.theme.rgb("muted"))
        self.set_xy(MARGIN, 9)
        self.cell(110, 5, self.fields(self.header_text) or self.theme.header_note or self.document_title.upper()[:80])
        if self.theme.logo:
            self.image(str(self.theme.logo), self.w - MARGIN - 45, 8, h=6)
        if self.theme.brand:
            self.set_font("Brand", "B", 7.5)
            self.set_text_color(*self.theme.rgb("ink"))
            self.set_xy(self.w - MARGIN - 38, 9)
            self.cell(38, 5, self.theme.brand, align="R")
        self.set_draw_color(*self.theme.rgb("primary" if self.theme.header_note else "rule"))
        self.set_line_width(0.3 if self.theme.header_note else 0.2)
        self.line(MARGIN, 15, self.w - MARGIN, 15)
        self.set_xy(self.l_margin, self.t_margin)

    # draws the watermark and classification label on the page
    def draw_marks(self):
        if self.watermark:
            with self.local_context(fill_opacity=0.07, text_color=self.theme.rgb("ink")):
                self.set_font("Head", "B", 96)
                with self.rotation(35, self.w / 2, self.h / 2):
                    self.set_xy(0, self.h / 2 - 20)
                    self.cell(self.w, 40, self.watermark.upper(), align="C")
        if self.classification:
            self.set_font("Brand", "B", 7)
            self.set_text_color(*self.theme.rgb("danger"))
            self.set_xy(0, 3.5)
            self.cell(self.w, 4, self.classification.upper(), align="C")

    # draws page marks, footnotes, and footer text
    def footer(self):
        self.draw_marks()
        if self.page_no() not in self.flow_pages:
            return
        self.draw_page_notes()
        self.set_font("Brand", "", 7.5)
        self.set_text_color(*self.theme.rgb("muted"))
        if "{page}" not in self.footer_text:
            self.set_xy(MARGIN, -13)
            self.cell(self.w - 2 * MARGIN, 5, f"{self.page_no()} / {{nb}}", align="R")
        footer = self.fields(self.footer_text) or (self.theme.footer_text if not self.plain else "")
        if footer:
            self.set_font("Brand", "", 7.5)
            self.set_xy(MARGIN, -13)
            self.cell(self.w - 2 * MARGIN - 20, 5, footer)


# places new footnotes at the bottom of the current PDF page
def place_notes(pdf, inline, note_texts, placed):
    if not note_texts:
        return
    pending = [note_texts[child.meta["id"]] for child in inline.children or []
               if child.type == "footnote_ref" and child.meta["id"] in note_texts and child.meta["id"] not in placed]
    if pending and pdf.will_page_break(sum(note_height(pdf, "0", note) for note in pending) + 22):
        pdf.add_page()
    place_page_notes(pdf, inline, note_texts, placed)


# measures the height needed to draw one footnote
def note_height(pdf, number, text):
    pdf.set_font("Brand", "", BODY_SIZE * pdf.scale * 0.8)
    lines = pdf.multi_cell(pdf.w - 2 * MARGIN, BODY_SIZE * pdf.scale * 0.42, f"{number} {text}", markdown=True,
                           dry_run=True, output=MethodReturnValue.LINES)
    return len(lines) * BODY_SIZE * pdf.scale * 0.42 + 1


# draws the footnotes assigned to the current PDF page
def draw_page_notes(pdf):
    notes = pdf.page_notes.get(pdf.page_no())
    if not notes:
        return
    height = sum(note_height(pdf, number, text) for number, text in notes) + 4
    top = pdf.h - 20 - height
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.set_line_width(0.2)
    pdf.line(MARGIN, top, MARGIN + 40, top)
    pdf.set_xy(MARGIN, top + 2.5)
    pdf.set_text_color(*pdf.theme.rgb("muted"))
    for number, text in notes:
        hanging_note(pdf, number, text, pdf.w - 2 * MARGIN, 0.8)
        pdf.ln(1)


# draws a footnote with its number hanging beside the text
def hanging_note(pdf, number, text, width, scale):
    size = BODY_SIZE * pdf.scale * scale
    left = pdf.get_x()
    pdf.set_font("Brand", "", size)
    pdf.cell(4, size * 0.52, number)
    pdf.set_x(left + 4)
    pdf.multi_cell(width - 4, size * 0.52, text, markdown=True, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


# assigns unplaced footnotes referenced by a paragraph to its page
def place_page_notes(pdf, inline, note_texts, placed):
    references = [child.meta["id"] for child in inline.children or [] if child.type == "footnote_ref"]
    fresh = [(str(reference + 1).translate(SUPERSCRIPT_DIGITS), note_texts[reference]) for reference in references
             if reference in note_texts and reference not in placed]
    if not fresh:
        return []
    page_notes = pdf.page_notes.setdefault(pdf.page_no(), [])
    page_notes.extend(fresh)
    placed.update(reference for reference in references if reference in note_texts)
    reserved = sum(note_height(pdf, number, text) for number, text in page_notes) + 6
    pdf.set_auto_page_break(True, margin=22 + reserved)
    return fresh


FlowPages.draw_page_notes = draw_page_notes


# fills page, title, date, and section placeholders in footer text
def page_fields(pdf, text):
    return (text.replace("{page}", str(pdf.page_no())).replace("{pages}", "{nb}")
            .replace("{title}", pdf.document_title).replace("{date}", pdf.meta_date).replace("{section}", pdf.current_section))[:110]


FlowPages.fields = page_fields


# copies PDF layout settings into a temporary measuring document
def probe_of(pdf: FlowPages, y=None):
    probe = FlowPages(pdf.theme, pdf.document_title, pdf.plain)
    for name in ("scale", "table_style", "lang", "targets", "flow_images", "numbering", "notes_at_page_bottom", "header_text",
                 "footer_text", "meta_date", "spacing"):
        setattr(probe, name, getattr(pdf, name))
    probe.headings, probe.measuring = list(pdf.headings), True
    probe.set_auto_page_break(True, margin=pdf.b_margin)
    probe.add_page()
    probe.set_margins(pdf.l_margin, pdf.t_margin, pdf.r_margin)
    probe.set_y(pdf.get_y() if y is None else y)
    return probe


# measures the height and page count of rendered content
def measured(pdf: FlowPages, draw):
    probe = probe_of(pdf)
    start = probe.get_y()
    draw(probe)
    pages = probe.page_no() - 1
    return probe.get_y() - start + pages * (probe.page_break_trigger - probe.t_margin), pages > 0


# measures how much space content uses from the top of a page
def top_height(pdf: FlowPages, draw):
    probe = probe_of(pdf, pdf.t_margin)
    draw(probe)
    return 0 if probe.page_no() > 1 else probe.get_y() - pdf.t_margin
