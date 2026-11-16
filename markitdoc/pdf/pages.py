from dataclasses import replace
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue
from PIL import Image

from markitdoc.markup.blocks import slot_pieces
from markitdoc.markup.inline import inline_runs, parser, subscripts, superscripts
from markitdoc.models.catalogue import Box, layouts, margin, page_height, page_width
from markitdoc.themes.themes import Theme
from markitdoc.utils.helpers import lifted

white, soft_white, faint_white = (255, 255, 255), (226, 230, 240), (190, 198, 216)
fpdf_markers = ("**", "__", "--", "~~")
shrink_steps = (1, 0.95, 0.9, 0.85)
heading_point = 12


# protects PDF text markers from being interpreted as formatting
def escaped(text):
    for marker in fpdf_markers:
        text = text.replace(marker, f"{marker[0]}\u200b{marker[1]}")
    return text


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
            text = text.translate(subscripts if run.script == "SUB" else superscripts)
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


class PdfPages(FPDF):
    # sets up the rendering context and its document settings
    def __init__(self, theme: Theme):
        super().__init__(format="A4")
        self.theme = theme
        fonts_folder = Path(theme.fonts["body"]).parent
        bold = theme.fonts.get("bold", theme.fonts["heading"])
        self.add_font("Brand", "", str(theme.fonts["body"]))
        self.add_font("Brand", "B", str(bold))
        self.add_font("Brand", "I", str(theme.fonts["italic"]))
        self.add_font("Brand", "BI", str(bold))
        self.add_font("Head", "", str(theme.fonts["heading"]))
        self.add_font("Head", "B", str(theme.fonts["heading"]))
        self.add_font("Mono", "", str(fonts_folder / "JetBrainsMono-Regular.ttf"))
        self.add_font("Devanagari", "", str(fonts_folder / "NotoSansDevanagari-Regular.ttf"))
        self.add_font("Devanagari", "B", str(fonts_folder / "NotoSansDevanagari-Bold.ttf"))
        self.add_font("Symbols", "", str(fonts_folder / "NotoSansSymbols2-Regular.ttf"))
        self.add_font("Latin", "", str(fonts_folder / "Inter-Regular.ttf"))
        self.add_font("Noto", "", str(fonts_folder / "NotoSans-Regular.ttf"))
        self.set_fallback_fonts(["Devanagari", "Symbols", "Latin", "Noto"], exact_match=False)
        self.photos, self.work_folder, self.photo_credit = "natural", None, None
        self.tightness = 1.0
        self.set_text_shaping(True)
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)

    # fills the PDF page with a theme color
    def fill_page(self, role):
        self.set_fill_color(*self.theme.rgb(role))
        self.rect(0, 0, self.w, self.h, "F")

    # draws text at a fixed PDF position and returns its ending height
    def write_at(self, x, y, width, text, size, style="", role="ink", line_height=1.35, align="L", rgb=None, rich=False):
        self.set_xy(x, y)
        self.set_font("Head" if style == "B" and size >= heading_point else "Brand", style, size)
        self.set_text_color(*(rgb or self.theme.rgb(role)))
        self.multi_cell(width, size * 0.3528 * line_height * self.tightness, rich_markup(text) if rich else escaped(text), align=align, markdown=True)
        return self.get_y()

    # measures how many lines a text box needs
    def line_count(self, text, box: Box):
        self.set_font("Head" if box.style == "B" and box.size >= heading_point else "Brand", box.style, box.size)
        return len(self.multi_cell(box.width, box.size * 0.45, rich_markup(text), dry_run=True, output=MethodReturnValue.LINES,
                                   markdown=True))

    # chooses the largest slot text size that fits its line limit
    def slot_size(self, block, slot):
        box = layouts[block.layout].boxes[slot]
        pieces = slot_pieces(block, slot)
        for scale in shrink_steps:
            size = round(box.size * scale, 1)
            if all(self.line_count(piece, replace(box, size=size)) <= box.lines for piece in pieces):
                return size
        return round(box.size * shrink_steps[-1], 1)

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
    def folio(self, label, left=margin, right=page_width - margin, on_dark=False):
        role_rgb = faint_white if on_dark else self.theme.rgb("muted")
        self.set_draw_color(*((70, 82, 120) if on_dark else self.theme.rgb("rule")))
        self.set_line_width(0.2)
        self.line(left, page_height - 14, right, page_height - 14)
        self.write_at(left, page_height - 11.5, 100, label.upper(), 7.5, "B", rgb=role_rgb)
        self.write_at(right - 30, page_height - 11.5, 30, f"{self.page_no()} / {{nb}}", 7.5, "B", rgb=role_rgb, align="R")

    # draws a soft circular glow within the requested page area
    def glow(self, center_x, center_y, size, rings=60, clip=(0, 0, page_width, page_height)):
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
        self.write_at(x + 13, y + 1.2, 120, self.theme.brand, 11, "B", rgb=white if on_dark else self.theme.rgb("ink"))
        if self.theme.tagline:
            self.write_at(x + 13, y + 6.4, 120, self.theme.tagline, 7, "B",
                          rgb=lifted(self.theme.rgb("mood"), 0.55) if on_dark else self.theme.rgb("primary"))

    # places partner logos across the bottom of the page
    def partner_strip(self, y, gap=6):
        x = margin
        for path, height in self.theme.partners:
            with Image.open(path) as picture:
                width = height * picture.width / picture.height
            if x + width > page_width - margin:
                break
            self.image(str(path), x, y + (12 - height) / 2, h=height)
            x += width + gap
