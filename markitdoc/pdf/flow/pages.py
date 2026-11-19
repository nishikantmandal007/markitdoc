import re
from contextlib import contextmanager
from functools import lru_cache

import pyphen
from fpdf.enums import MethodReturnValue, XPos, YPos

from markitdoc.markup.fields import replace_fields
from markitdoc.markup.inline import SUPERSCRIPT_DIGITS
from markitdoc.pdf.pages import PdfPages
from markitdoc.utils.helpers import lifted
from markitdoc.visuals.logos import logo_box

BODY_SIZE, TABLE_SIZE = 10, 9
LINE_RATIO = 1.4
LINE_MM = LINE_RATIO * 0.3528
MARGIN = 25
HIGHLIGHT_LINK = "§highlight"
HYPHENATION_LANGUAGES = {"en": "en_GB", "de": "de_DE", "fr": "fr", "es": "es"}
LONG_WORD = re.compile(r"[^\W\d_]{7,}")
ROMAN_DIGITS = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
                (5, "v"), (4, "iv"), (1, "i"))
LABEL_STYLES = {"arabic": "D", "roman": "r", "Roman": "R", "alpha": "a"}
DESIGNED_PAPER_MM = (210, 297)

HEADER_LOGO_WIDTH, HEADER_LOGO_HEIGHT = 30, 6


# a page number as text in a numbering style: arabic, roman, Roman, alpha, or none for no number
def number_label(number, style):
    if style == "none":
        return ""
    if style in ("roman", "Roman"):
        text = ""
        for value, letters in ROMAN_DIGITS:
            text, number = text + letters * (number // value), number % value
        return text.upper() if style == "Roman" else text
    if style == "alpha":
        text = ""
        while number > 0:
            number, rest = divmod(number - 1, 26)
            text = chr(97 + rest) + text
        return text
    return str(number)


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
    def __init__(self, theme, title, plain, text=None, donor=None):
        super().__init__(theme, text, donor)
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
        self.page_ends, self.page_starts, self.floating = [], [], None
        self.edge, self.page_edges, self.page_masters, self.page_labels, self.page_section = (MARGIN, 20, MARGIN, 22), {}, {}, {}, {}
        self.masters, self.master_name, self.next_master, self.restart = {}, None, None, False
        self.counter, self.number_style, self.master_landscape, self.field_values = 0, None, False, {}
        self.numbers, self.target_pages, self.pending_target = {}, {}, ""
        self.run, self.page_runs, self.page_numbers = 0, {}, {}
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

    # the left, top, right and bottom margins in mm of a page, the current page by default
    def page_edge(self, page=None):
        return self.page_edges.get(page or self.page_no(), self.edge)

    # the page master of a page
    def master_of(self, page=None):
        return self.page_masters.get(page or self.page_no())

    # the number shown for a page: its label under the page master, the page index otherwise
    def shown_page(self, page=None):
        return self.page_labels.get(page or self.page_no(), str(page or self.page_no()))

    # records where a labelled target sits, so references can link to it and name its page
    def mark_target(self, ident):
        if ident:
            self.set_link(name=ident, page=self.page_no(), y=self.get_y())
            self.target_pages[ident] = self.shown_page()

    # the pages of the numbering run each footer's {pages} stands for, patched in once the run is complete
    def _render_footer(self):
        super()._render_footer()
        if self.page in self.pages:
            page = self.pages[self.page]
            for fragment in page.get_text_substitutions():
                fragment.render_text_substitution = lambda _, original=fragment.render_text_substitution, run=self.page_runs[id(page)]: original(
                    str(sum(1 for item in self.pages.values() if self.page_runs.get(id(item)) == run)))

    # the bottom margin in mm of the current page
    @property
    def bottom(self):
        return self.page_edge()[3]

    # chooses the page master of the next page and returns the add_page arguments with its paper, orientation and number label
    def enter_master(self, kwargs):
        switching = self.next_master is not None
        name = self.next_master or self.master_name or "default"
        master = self.masters.setdefault(name, self.styles.master(name))
        landscape = kwargs.get("orientation", "").upper().startswith("L") or master.width > master.height
        top, right, bottom, left = master.margins
        page, edge = self.page + 1, (left, top, right, bottom)
        if name != self.master_name:
            self.set_margins(left, top, right)
        if self.auto_page_break:
            self.set_auto_page_break(True, margin=bottom)
        if page not in self.page_numbers:
            number = 1 if self.restart else self.counter + 1
            self.run += 1 if self.restart or not self.run else 0
            self.page_numbers[page] = (number, self.run, {"label_style": LABEL_STYLES[master.numbers], "label_start": number}
                                       if master.numbers in LABEL_STYLES and (self.restart or master.numbers != self.number_style) else {})
        number, self.run, labelled = self.page_numbers[page]
        self.edge, self.page_edges[page], self.page_masters[page] = edge, edge, master
        self.page_labels[page] = number_label(number, master.numbers)
        self.counter, self.restart, self.number_style = number, False, master.numbers
        self.master_name, self.next_master, self.master_landscape = name, None, master.width > master.height
        if kwargs.get("same") and not switching:
            return kwargs
        return {**{key: item for key, item in kwargs.items() if key != "same"}, **labelled,
                "format": tuple(sorted((master.width, master.height))), "orientation": "L" if landscape else "P"}

    # runs designed page drawing centred, and shrunk on smaller paper, when the paper is not the A4 the designs are made for
    @contextmanager
    def centred(self):
        scale = min(1, self.w / DESIGNED_PAPER_MM[0], self.h / DESIGNED_PAPER_MM[1])
        shift = ((self.w - DESIGNED_PAPER_MM[0] * scale) / 2, (self.h - DESIGNED_PAPER_MM[1] * scale) / 2)
        if scale == 1 and abs(shift[0]) + abs(shift[1]) < 0.5:
            yield
            return
        self.fit = (*shift, scale)
        self._out(f"q {scale:.4f} 0 0 {scale:.4f} {shift[0] * self.k:.2f} {(self.h * (1 - scale) - shift[1]) * self.k:.2f} cm")
        try:
            yield
        finally:
            self._out("Q")
            self.fit = (0, 0, 1)

    # adds a page and resets portrait tracking when needed
    def add_page(self, *args, **kwargs):
        for hook in self.page_ends:
            hook(self.get_y())
        kwargs = self.enter_master(kwargs)
        super().add_page(*args, **kwargs)
        self.page_runs[id(self.pages[self.page])] = self.run
        if self.auto_page_break and self.decorate:
            self.set_auto_page_break(True, margin=self.bottom)
        if self.w < self.h:
            self.back_to_portrait = False
        for hook in self.page_starts:
            hook()

    # returns the usable horizontal width inside the page margins
    @property
    def area(self):
        return self.w - self.l_margin - self.r_margin

    # draws the running header and records decorated flow pages
    def header(self):
        if self.decorate:
            self.flow_pages.add(self.page_no())
            self.fill_page("paper")
        left, top, right, _ = self.page_edge()
        if self.plain or not self.decorate or self.page_no() == 1 or (self.master_of() and self.master_of().header is not None):
            return
        self.set_font("Brand", "I" if self.theme.header_note else "B", 7.5)
        self.set_text_color(*self.theme.rgb("muted"))
        self.set_xy(left, top - 11)
        self.cell(110, 5, self.fields(self.header_text) or self.theme.header_note or self.document_title.upper()[:80])
        self.set_font("Brand", "B", 7.5)
        brand_width = self.get_string_width(self.theme.brand) + 2 if self.theme.brand else 0
        if self.theme.logo:
            width, height = logo_box(self.theme.logo, HEADER_LOGO_WIDTH, HEADER_LOGO_HEIGHT)
            self.image(str(self.theme.logo), self.w - right - brand_width - width, top - 12 + (HEADER_LOGO_HEIGHT - height) / 2, w=width, h=height)
        if self.theme.brand:
            self.set_font("Brand", "B", 7.5)
            self.set_text_color(*self.theme.rgb("ink"))
            self.set_xy(self.w - right - 38, top - 11)
            self.cell(38, 5, self.theme.brand, align="R")
        self.set_draw_color(*self.theme.rgb("primary" if self.theme.header_note else "rule"))
        self.set_line_width(0.3 if self.theme.header_note else 0.2)
        self.line(left, top - 5, self.w - right, top - 5)
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
        left, top, right, bottom = self.page_edge()
        self.set_font("Brand", "", 7.5)
        self.set_text_color(*self.theme.rgb("muted"))
        if self.master_of() and (self.master_of().header is not None or self.master_of().footer is not None):
            self.draw_slots()
            return
        if "{page}" not in self.footer_text:
            self.set_xy(left, -(bottom - 9))
            self.cell(self.w - left - right, 5, f"{self.shown_page()} / {{nb}}" if self.shown_page() else "", align="R")
        footer = self.fields(self.footer_text) or (self.theme.footer_text if not self.plain else "")
        if footer:
            self.set_font("Brand", "", 7.5)
            self.set_xy(left, -(bottom - 9))
            self.cell(self.w - left - right - 20, 5, footer)

    # draws the header and footer of the page master as left, centre and right slots
    def draw_slots(self):
        left, top, right, bottom = self.page_edge()
        master = self.master_of()
        for text, y in ((master.header, top - 11), (master.footer, self.h - bottom + 9)):
            if text is None or text.strip().lower() == "none":
                continue
            slots = [self.fields(slot.strip()) for slot in (text.split("|", 2) + ["", ""])[:3]]
            for slot, align in zip(slots, "LCR"):
                self.set_xy(left, y)
                self.cell(self.w - left - right, 5, slot, align=align)
            if y < top and any(slots):
                self.set_draw_color(*self.theme.rgb("rule"))
                self.set_line_width(0.2)
                self.line(left, top - 5, self.w - right, top - 5)


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
    lines = pdf.multi_cell(pdf.w - pdf.page_edge()[0] - pdf.page_edge()[2], BODY_SIZE * pdf.scale * 0.42, f"{number} {text}", markdown=True,
                           dry_run=True, output=MethodReturnValue.LINES)
    return len(lines) * BODY_SIZE * pdf.scale * 0.42 + 1


# draws the footnotes assigned to the current PDF page
def draw_page_notes(pdf):
    notes = pdf.page_notes.get(pdf.page_no())
    if not notes:
        return
    height = sum(note_height(pdf, number, text) for number, text in notes) + 4
    left, _, right, bottom = pdf.page_edge()
    top = pdf.h - (bottom - 2) - height
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.set_line_width(0.2)
    pdf.line(left, top, left + 40, top)
    pdf.set_xy(left, top + 2.5)
    pdf.set_text_color(*pdf.theme.rgb("muted"))
    for number, text in notes:
        hanging_note(pdf, number, text, pdf.w - left - right, 0.8)
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
    pdf.set_auto_page_break(True, margin=pdf.bottom + reserved)
    return fresh


FlowPages.draw_page_notes = draw_page_notes


# fills page, title, date, and section placeholders in footer text
def page_fields(pdf, text):
    text = replace_fields(text, pdf.field_values)
    return (text.replace("{page}", pdf.shown_page()).replace("{pages}", "{nb}").replace("{title}", pdf.document_title)
            .replace("{date}", pdf.meta_date).replace("{section}", pdf.page_section.get(pdf.page_no()) or pdf.current_section))[:110]


FlowPages.fields = page_fields


# copies PDF layout settings into a temporary measuring document
def probe_of(pdf: FlowPages, y=None):
    donor = pdf.donor or pdf.lender
    if donor is None:
        donor = pdf.lender = FlowPages(pdf.theme, pdf.document_title, pdf.plain, pdf.document_text)
        donor.use_styles(pdf.styles)
    probe = FlowPages(pdf.theme, pdf.document_title, pdf.plain, pdf.document_text, donor)
    for name in ("scale", "table_style", "lang", "targets", "flow_images", "numbering", "notes_at_page_bottom", "header_text",
                 "footer_text", "meta_date", "spacing", "field_values", "numbers"):
        setattr(probe, name, getattr(pdf, name))
    probe.headings, probe.measuring = list(pdf.headings), True
    probe.use_styles(pdf.styles)
    probe.next_master = pdf.master_name
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
