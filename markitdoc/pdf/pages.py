import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.enums import MethodReturnValue
from PIL import Image

from markitdoc.markup.blocks import slot_pieces
from markitdoc.markup.inline import SUBSCRIPTS, SUPERSCRIPTS, inline_runs, parser
from markitdoc.models.catalogue import LAYOUTS, MARGIN, PAGE_HEIGHT, PAGE_WIDTH, Box
from markitdoc.themes.theme_constants import FONT_WORDS
from markitdoc.themes.themes import Theme
from markitdoc.utils.helpers import lifted

WHITE, SOFT_WHITE, FAINT_WHITE = (255, 255, 255), (226, 230, 240), (190, 198, 216)
SHRINK_STEPS = (1, 0.95, 0.9, 0.85)
HEADING_POINT = 12
FALLBACK_FAMILIES = ("Devanagari", "Symbols", "Latin", "Noto")


# reads the code points a font file can draw, once per process
@lru_cache(maxsize=None)
def cmap_of(path):
    with TTFont(str(path), lazy=True) as font:
        return frozenset(font.getBestCmap())


# protects PDF text markers from being interpreted as formatting
def escaped(text):
    return re.sub(r"([*_~-])(?=\1)", "\\1\u200b", text)


# joins adjacent text runs with matching styles
def merged(runs):
    result = []
    for run in runs:
        if result and replace(result[-1], text="") == replace(run, text=""):
            result[-1] = replace(result[-1], text=result[-1].text + run.text)
        else:
            result.append(run)
    return result


# converts styled text runs into markdown formatting
def runs_markup(runs) -> str:
    parts = []
    for run in merged(runs):
        text = escaped(run.text)
        if run.script:
            text = text.translate(SUBSCRIPTS if run.script == "SUB" else SUPERSCRIPTS)
        markers = ("**" if run.bold else "") + ("__" if run.italic else "") + ("--" if run.underline else "") + ("~~" if run.strike else "")
        if markers and text.strip():
            core, lead, trail = text.strip(), text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
            text = f"{lead}{markers}{core}{markers[::-1]}{trail}"
        if run.link:
            text = f"[{text.replace('[', chr(0x200b) + '[')}]({run.link})"
        parts.append(text)
    return "".join(parts).strip()


# converts inline markdown tokens into styled text markup
def inline_markup(token, targets=frozenset()) -> str:
    return runs_markup(inline_runs(token, targets))


# converts inline markdown text into styled text markup
def rich_markup(text):
    tokens = parser.parseInline(text or "")
    return inline_markup(tokens[0]) if tokens else ""


# gathers every character a document can draw so only the fonts that cover them are loaded
def text_of(document, theme: Theme):
    return "\n".join([str(document.meta), theme.brand or "", theme.tagline or "", theme.header_note or "", theme.footer_text or "",
                      *(f"{block.body}\n{block.slots}" for block in document.blocks)])


class PdfPages(FPDF):
    # sets up the rendering context and its document settings
    def __init__(self, theme: Theme, text=None, donor=None):
        super().__init__(format="A4")
        self.theme = theme
        fonts_folder = Path(theme.fonts["body"]).parent
        bold = theme.fonts.get("bold", theme.fonts["heading"])
        faces = {
            "Brand": (theme.fonts["body"], bold, theme.fonts["italic"], bold),
            "Head": (theme.fonts["heading"], theme.fonts["heading"], theme.fonts["italic"], theme.fonts["heading"]),
            "Mono": (fonts_folder / "JetBrainsMono-Regular.ttf", fonts_folder / "JetBrainsMono-Bold.ttf",
                     fonts_folder / "JetBrainsMono-Regular.ttf", fonts_folder / "JetBrainsMono-Bold.ttf"),
            "Devanagari": (fonts_folder / "NotoSansDevanagari-Regular.ttf", fonts_folder / "NotoSansDevanagari-Bold.ttf",
                           fonts_folder / "NotoSansDevanagari-Regular.ttf", fonts_folder / "NotoSansDevanagari-Bold.ttf"),
            "Symbols": (fonts_folder / "NotoSansSymbols2-Regular.ttf",) * 4,
            "Latin": (fonts_folder / "Inter-Regular.ttf", fonts_folder / "Inter-Bold.ttf",
                      fonts_folder / "Inter-Italic.ttf", fonts_folder / "Inter-BoldItalic.ttf"),
            "Noto": (fonts_folder / "NotoSans-Regular.ttf", fonts_folder / "NotoSans-Bold.ttf",
                     fonts_folder / "NotoSans-Italic.ttf", fonts_folder / "NotoSans-BoldItalic.ttf"),
        }
        self.family_files, self.document_text, self.donor, self.lender = faces, text, donor, None
        self.primaries = [faces[family][0] for family in ("Brand", "Head", "Mono")]
        has_code = text is None or "`" in text or "~~~" in text or re.search(r"^(?: {4}|\t)", text, re.M)
        for family in faces if text is None else ("Brand", "Head", *(("Mono",) if has_code else ())):
            self.add_family(family, faces[family])
        self.use_fallbacks()
        self.photos, self.work_folder, self.photo_credit = "natural", None, None
        self.tightness = 1.0
        self.styles, self.context, self.fit = None, None, (0, 0, 1)
        self.set_text_shaping(True)
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)

    # registers the four styles of a font family, parsing each file once per document through the donor
    def add_family(self, family, files):
        owner = self.donor or self
        for style, path in zip(("", "B", "I", "BI"), files):
            key = f"{family.lower()}{style}"
            if key not in owner.fonts:
                owner.add_font(family, style, str(path))
            self.fonts[key] = owner.fonts[key]

    # loads a bundled font family the first time a document draws with it
    def set_font(self, family=None, style="", size=0):
        if family in self.family_files:
            self.add_family(family, self.family_files[family])
        super().set_font(family, style, size)

    # loads only the fallback families that draw characters the main fonts cannot
    def use_fallbacks(self):
        missing = None if self.document_text is None else {ord(char) for char in set(self.document_text) if char.isprintable()
                                                  if any(ord(char) not in cmap_of(path) for path in self.primaries)}
        chosen = [family for family in FALLBACK_FAMILIES if missing is None or missing & cmap_of(self.family_files[family][0])]
        for family in chosen:
            self.add_family(family, self.family_files[family])
        self.set_fallback_fonts(chosen, exact_match=False)

    # sets the stylesheet and registers the fonts it declares in all four styles
    def use_styles(self, styles):
        self.styles = styles
        for name, face in styles.faces.items():
            if face:
                self.add_family(f"Face-{name}", face.files)
                self.primaries.append(face.files[0])
        self.use_fallbacks()

    # the look of an element under the stylesheet
    def look(self, selector, classes=(), inline=None):
        return self.styles.look(selector, classes, inline, context=self.context)

    # the font family a look asks for, the default when it asks for none
    def family_of(self, look, default):
        if look is None or not look.font:
            return default
        return FONT_WORDS.get(look.font) or f"Face-{look.font}"

    # fills the PDF page with a theme color
    def fill_page(self, role):
        self.set_fill_color(*self.theme.rgb(role))
        self.rect(0 - self.fit[0] / self.fit[2], 0 - self.fit[1] / self.fit[2], self.w / self.fit[2], self.h / self.fit[2], "F")

    # draws text at a fixed PDF position and returns its ending height
    def write_at(self, x, y, width, text, size, style="", role="ink", line_height=1.35, align=None, rgb=None, rich=False):
        if align is None:
            align = "J" if role == "body" else "L"
        if align == "J":
            from markitdoc.pdf.flow.pages import hyphenated
            text = hyphenated(text, getattr(self, "lang", "en"))
        self.set_xy(x, y)
        self.set_font("Head" if style == "B" and size >= HEADING_POINT else "Brand", style, size)
        self.set_text_color(*(rgb or self.theme.rgb(role)))
        self.multi_cell(width, size * 0.3528 * line_height * self.tightness, rich_markup(text) if rich else escaped(text), align=align, markdown=True)
        return self.get_y()

    # measures how many lines a text box needs
    def line_count(self, text, box: Box):
        self.set_font("Head" if box.style == "B" and box.size >= HEADING_POINT else "Brand", box.style, box.size)
        return len(self.multi_cell(box.width, box.size * 0.45, rich_markup(text), dry_run=True, output=MethodReturnValue.LINES,
                                   markdown=True))

    # chooses the largest slot text size that fits its line limit
    def slot_size(self, block, slot, width=None):
        box = LAYOUTS[block.layout].boxes[slot]
        box = replace(box, width=width) if width else box
        pieces = slot_pieces(block, slot)
        for scale in SHRINK_STEPS:
            size = round(box.size * scale, 1)
            if all(self.line_count(piece, replace(box, size=size)) <= box.lines for piece in pieces):
                return size
        return round(box.size * SHRINK_STEPS[-1], 1)

    # measures the height needed for text in the PDF
    def text_height(self, text, width, size, line_height, style=""):
        return self.line_count(text, Box(width, size, 0, style)) * size * 0.3528 * line_height * self.tightness if text else 0

    # chooses the largest text size that fits the available height
    def fitting_size(self, text, width, size, smallest=11):
        self.set_font("Brand", "B", size)
        while size > smallest and self.get_string_width(text) > width - 2 * self.c_margin:
            size -= 1
            self.set_font("Brand", "B", size)
        return size

    # draws a solid horizontal color bar on the PDF page
    def bar(self, x, y, width=22, height=1.4, role="accent", rgb=None):
        self.set_fill_color(*(rgb or self.theme.rgb(role)))
        self.rect(x, y, width, height, "F")

    # draws an uppercase section label in the PDF
    def kicker(self, x, y, text, on_dark=False):
        self.write_at(x, y, 150, text.upper(), 8.5, "B", rgb=lifted(self.theme.rgb("mood"), 0.55) if on_dark else self.theme.rgb("mood"))

    # draws the page footer rule, label, and page number
    def folio(self, label, left=MARGIN, right=PAGE_WIDTH - MARGIN, on_dark=False):
        role_rgb = FAINT_WHITE if on_dark else self.theme.rgb("muted")
        self.set_draw_color(*((70, 82, 120) if on_dark else self.theme.rgb("rule")))
        self.set_line_width(0.2)
        self.line(left, PAGE_HEIGHT - 14, right, PAGE_HEIGHT - 14)
        self.write_at(left, PAGE_HEIGHT - 11.5, 100, label.upper(), 7.5, "B", rgb=role_rgb)
        self.write_at(right - 30, PAGE_HEIGHT - 11.5, 30, f"{self.page_no()} / {{nb}}", 7.5, "B", rgb=role_rgb, align="R")

    # draws a soft circular glow within the requested page area
    def glow(self, center_x, center_y, size, rings=60, clip=(0, 0, PAGE_WIDTH, PAGE_HEIGHT)):
        with self.rect_clip(*clip):
            for ring in range(rings):
                with self.local_context(fill_opacity=0.03):
                    self.set_fill_color(*self.theme.rgb("glow"))
                    radius = size - ring * size / rings
                    self.ellipse(center_x - radius / 2, center_y - radius / 2, radius, radius, "F")

    # draws the configured logo, brand name, and tagline
    def brand_mark(self, x, y, on_dark):
        if not self.theme.logo:
            return
        self.image(str(self.theme.logo), x, y, h=10)
        self.write_at(x + 13, y + 1.2, 120, self.theme.brand, 11, "B", rgb=WHITE if on_dark else self.theme.rgb("ink"))
        if self.theme.tagline:
            self.write_at(x + 13, y + 6.4, 120, self.theme.tagline, 7, "B",
                          rgb=lifted(self.theme.rgb("mood"), 0.55) if on_dark else self.theme.rgb("primary"))

    # places partner logos across the bottom of the page
    def partner_strip(self, y, gap=6):
        x = MARGIN
        for path, height in self.theme.partners:
            with Image.open(path) as picture:
                width = height * picture.width / picture.height
            if x + width > PAGE_WIDTH - MARGIN:
                break
            self.image(str(path), x, y + (12 - height) / 2, h=height)
            x += width + gap
