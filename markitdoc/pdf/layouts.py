import io
import os
import zlib
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from pathlib import Path

from fpdf import FPDF, ViewerPreferences
from fpdf.enums import MethodReturnValue
from markdown_it import MarkdownIt
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.subscript import sub_plugin
from mdit_py_plugins.superscript import superscript_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
import numpy
from PIL import Image, ImageFilter, ImageOps

import logging
from markitdoc.visuals.icons import icon_svg, strip_icon
from markitdoc.models.document import Block, Document
from markitdoc.themes.theme_constants import TEXT_SIZES
from markitdoc.themes.themes import Theme

logger = logging.getLogger(__name__)
page_width, page_height, margin = 210, 297, 20
content_width = page_width - 2 * margin
text_width = content_width
content_limit = page_height - 19
paragraph_break = "||"
white, soft_white, faint_white = (255, 255, 255), (226, 230, 240), (190, 198, 216)
parser = (MarkdownIt("commonmark").enable(["table", "strikethrough"]).disable(["html_block", "html_inline"])
          .use(footnote_plugin).use(tasklists_plugin).use(deflist_plugin).use(attrs_plugin, spans=True)
          .use(sub_plugin).use(superscript_plugin).use(dollarmath_plugin, allow_space=False, allow_digits=False, double_inline=True))
for container_name in ("box", "sidebar", "columns"):
    container_plugin(parser, container_name, validate=lambda params, *_, name=container_name: name in re.findall(r"[\w-]+", params)[:1])
subscripts = str.maketrans("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
superscripts = str.maketrans("0123456789+-=()abcdefghijklmnoprstuvwxyz", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ")
tex_symbols = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "theta": "θ", "lambda": "λ", "mu": "μ",
               "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "omega": "ω", "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω",
               "cdot": "·", "times": "×", "div": "÷", "pm": "±", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠",
               "approx": "≈", "infty": "∞", "sum": "Σ", "prod": "Π", "int": "∫", "rightarrow": "→", "to": "→", "leftarrow": "←",
               "in": "∈", "partial": "∂", "nabla": "∇", "sqrt": "√", "ldots": "…", "dots": "…", "cdots": "⋯",
               "varepsilon": "ε", "vartheta": "ϑ", "varphi": "φ", "eta": "η", "kappa": "κ", "nu": "ν", "xi": "ξ", "chi": "χ",
               "psi": "ψ", "zeta": "ζ", "Gamma": "Γ", "Theta": "Θ", "Lambda": "Λ", "Pi": "Π", "Phi": "Φ", "Psi": "Ψ",
               "oplus": "⊕", "odot": "⊙", "otimes": "⊗", "gg": "≫", "ll": "≪", "sim": "∼", "simeq": "≃", "equiv": "≡",
               "propto": "∝", "circ": "∘", "prime": "′", "degree": "°", "perp": "⊥", "parallel": "∥", "forall": "∀",
               "exists": "∃", "Rightarrow": "⇒", "Leftrightarrow": "⇔", "mapsto": "↦", "hbar": "ħ", "ell": "ℓ"}
tex_text_commands = ("text", "mathrm", "textrm", "mathit", "textit", "operatorname", "mathsf", "mathcal", "boldsymbol",
                     "mathbf", "textbf")
tex_accents = {"dot": "\u0307", "ddot": "\u0308", "hat": "\u0302", "bar": "\u0304", "overline": "\u0304"}
bold_open, bold_close = "\u0001", "\u0002"
anchor = re.compile(r"\s*\{#([\w-]+)\}\s*$")
superscript_digits = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
fpdf_markers = ("**", "__", "--", "~~")
shrink_steps = (1, 0.95, 0.9, 0.85)
tightness_steps = (1.0, 0.92, 0.85)
heading_point = 12
leading_number = re.compile(r"^\s*(step\s+)?\d+\s*[.):-]\s*", re.IGNORECASE)


@dataclass(frozen=True)
class Box:
    width: float
    size: float
    lines: int
    style: str = ""
    required: bool = True
    min_lines: int = 0


@dataclass(frozen=True)
class PdfLayout:
    name: str
    boxes: dict
    items: tuple = (0, 0, ())
    variants: tuple = ("default",)
    image_ratio: float = 0
    dark_variants: tuple = ()


feature_text_width = page_width - 92 - 12 - margin
layouts = {
    "cover": PdfLayout("cover", {"kicker": Box(170, 8.5, 1, "B", False), "title": Box(content_width, 40, 3, "B"),
                                 "subtitle": Box(150, 13, 3)}, variants=("dark", "photo", "light", "split", "company"),
                       image_ratio=page_width / page_height, dark_variants=("dark", "photo")),
    "summary": PdfLayout("summary", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12.5, 4),
                                     "body": Box(text_width, 10.5, 24, min_lines=8)}, items=(2, 4, (12, 40))),
    "divider": PdfLayout("divider", {"number": Box(60, 64, 1, "B", False), "title": Box(content_width, 32, 3, "B"),
                                     "lead": Box(150, 13, 5, required=False)}, items=(0, 6, (70,)),
                         variants=("light", "dark"), dark_variants=("dark",)),
    "chapter": PdfLayout("chapter", {"number": Box(20, 30, 1, "B", False), "title": Box(content_width - 22, 21, 2, "B"),
                                     "lead": Box(content_width, 12.5, 4, required=False),
                                     "body": Box(content_width / 2 - 4, 10, 38, min_lines=12),
                                     "quote": Box(content_width - 6, 12.5, 3, "I", False)},
                         variants=("band", "plain"), image_ratio=page_width / 108),
    "figures": PdfLayout("figures", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 3, required=False),
                                     "body": Box(content_width, 10, 10, required=False)}, items=(3, 6, (10, 32, 110))),
    "keypoints": PdfLayout("keypoints", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 3, required=False)},
                           items=(3, 5, (60, 240))),
    "matrix": PdfLayout("matrix", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 3, required=False)},
                        items=(4, 4, (32, 260))),
    "quote": PdfLayout("quote", {"quote": Box(content_width - 10, 26, 6, "I"), "quote_by": Box(150, 11, 1, "B", False),
                                 "context": Box(130, 10.5, 5, required=False)},
                       variants=("light", "dark"), dark_variants=("dark",)),
    "comparison": PdfLayout("comparison", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 4, required=False),
                                           "left": Box(content_width / 2 - 13, 13, 1, "B"),
                                           "right": Box(content_width / 2 - 13, 13, 1, "B"),
                                           "takeaway": Box(content_width - 14, 11, 3, "B", False)}, items=(3, 7, (170, 170))),
    "process": PdfLayout("process", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 4, required=False)},
                         items=(3, 6, (34, 180)), variants=("vertical", "horizontal")),
    "timeline": PdfLayout("timeline", {"title": Box(content_width, 26, 2, "B"), "lead": Box(150, 11.5, 3, required=False)},
                          items=(3, 8, (16, 48, 160)), variants=("vertical", "horizontal", "dark"), dark_variants=("dark",)),
    "feature": PdfLayout("feature", {"title": Box(feature_text_width, 21, 3, "B"), "body": Box(feature_text_width, 10, 33, min_lines=10)},
                         items=(0, 3, (14, 40)), variants=("left", "right"), image_ratio=92 / page_height),
    "closing": PdfLayout("closing", {"quote": Box(content_width - 8, 22, 5, "I", False), "quote_by": Box(150, 10.5, 1, "B", False),
                                     "title": Box(content_width, 17, 2, "B"), "body": Box(text_width, 10.5, 22)},
                         variants=("default", "company")),
    "flow": PdfLayout("flow", {}),
}
icon_layouts = ("figures",)
trailing_headings = re.compile(r"(?:\n*^#{1,6} [^\n]*\s*)+\Z", re.M)
sectioned_layouts = ("summary", "divider", "chapter", "figures", "keypoints", "matrix", "comparison", "process", "feature", "timeline")


def escaped(text):
    for marker in fpdf_markers:
        text = text.replace(marker, f"{marker[0]}\u200b{marker[1]}")
    return text


@dataclass(frozen=True)
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    role: str = ""
    script: str = ""
    link: str = ""
    highlight: bool = False


span_roles = {"accent": "mood", "second": "second", "muted": "muted", "danger": "danger", "success": "success", "highlight": "ink"}


def inline_runs(token, targets=frozenset()) -> list[Run]:
    runs, state, spans, link = [], {"bold": 0, "italic": 0, "strike": 0}, [], ""
    script = ""

    def add(text, **extra):
        if text:
            runs.append(Run(text, bold=state["bold"] > 0 or extra.get("bold", False), italic=state["italic"] > 0,
                            strike=state["strike"] > 0, underline=any(span[0] for span in spans),
                            role=next((span[1] for span in reversed(spans) if span[1]), ""), script=extra.get("script", script),
                            link=link, highlight=any(span[2] for span in spans)))

    for child in token.children or []:
        kind = child.type
        if kind in ("text", "code_inline"):
            add(child.content)
        elif kind in ("strong_open", "em_open", "s_open"):
            state[{"strong_open": "bold", "em_open": "italic", "s_open": "strike"}[kind]] += 1
        elif kind in ("strong_close", "em_close", "s_close"):
            name = {"strong_close": "bold", "em_close": "italic", "s_close": "strike"}[kind]
            state[name] = max(0, state[name] - 1)
        elif kind in ("sub_open", "sup_open"):
            script = "SUB" if kind == "sub_open" else "SUP"
        elif kind in ("sub_close", "sup_close"):
            script = ""
        elif kind == "softbreak":
            add(" ")
        elif kind == "hardbreak":
            add("\n")
        elif kind == "link_open":
            target = str(child.attrs.get("href") or "")
            link = target if target.startswith(("http://", "https://", "mailto:")) or target[1:] in targets else ""
        elif kind == "link_close":
            link = ""
        elif kind in ("math_inline", "math_inline_double"):
            for index, piece in enumerate(re.split(f"[{bold_open}{bold_close}]", inline_maths(child.content))):
                add(piece, bold=index % 2 == 1)
        elif kind == "footnote_ref":
            add(str(child.meta["id"] + 1).translate(superscripts))
        elif kind == "html_inline" and "checkbox" in child.content:
            add("☑ " if "checked" in child.content else "☐ ")
        elif kind == "span_open":
            classes = str(child.attrs.get("class", "")).split()
            spans.append(("underline" in classes, next((span_roles[name] for name in classes if name in span_roles), ""),
                          "highlight" in classes))
        elif kind == "span_close" and spans:
            spans.pop()
    return runs


def merged(runs):
    result = []
    for run in runs:
        if result and replace(result[-1], text="") == replace(run, text=""):
            result[-1] = replace(result[-1], text=result[-1].text + run.text)
        else:
            result.append(run)
    return result


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


def inline_markup(token, targets=frozenset()) -> str:
    return runs_markup(inline_runs(token, targets))


def inline_maths(tex):
    text = re.sub(r"\\(left|right|big|Big|bigg|Bigg)\b", "", tex)
    text = re.sub(r"\\[,;:! ]|\\q?quad\b", " ", text)
    text = re.sub(r"\\(" + "|".join(tex_text_commands) + r")\{([^{}]*)\}",
                  lambda match: (bold_open + match.group(2) + bold_close) if match.group(1) in ("mathbf", "textbf", "boldsymbol")
                  else match.group(2), text)
    text = re.sub(r"\\vec\{([^{}]*)\}|\\vec\s*(\w)", lambda match: bold_open + (match.group(1) or match.group(2)) + bold_close, text)
    text = re.sub(r"\\(" + "|".join(tex_accents) + r")\{(\w)\}|\\(" + "|".join(tex_accents) + r")\s*(\w)",
                  lambda match: (match.group(2) or match.group(4)) + tex_accents[match.group(1) or match.group(3)], text)
    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", text)
    text = re.sub(r"\\([A-Za-z]+)", lambda match: tex_symbols.get(match.group(1), match.group(1)), text)
    text = re.sub(r"\^\{([^{}]*)\}|\^([^\s{}])", lambda match: (match.group(1) or match.group(2)).translate(superscripts), text)
    text = re.sub(r"_\{([^{}]*)\}|_([^\s{}])", lambda match: (match.group(1) or match.group(2)).translate(subscripts), text)
    text = re.sub(r"√\((\w)\)", r"√\1", text.replace("{", "").replace("}", ""))
    text = re.sub(r"\(([^\s()+\-*/=]+)\)/", r"\1/", text)
    text = re.sub(r"/\(([^\s()+\-*/=]+)\)", r"/\1", text)
    return re.sub(r" {2,}", " ", text).strip()


def rich_markup(text):
    tokens = parser.parseInline(text or "")
    return inline_markup(tokens[0]) if tokens else ""


def lifted(rgb, amount=0.4):
    return tuple(int(channel + (255 - channel) * amount) for channel in rgb)


class PdfPages(FPDF):
    def __init__(self, theme: Theme):
        super().__init__(format="A4")
        self.theme = theme
        fonts_folder = Path(theme.fonts["body"]).parent
        bold = theme.fonts.get("bold", theme.fonts["heading"])
        self.add_font("Brand", "", str(theme.fonts["body"]))
        self.add_font("Brand", "B", str(bold))
        self.add_font("Brand", "I", str(theme.fonts["italic"]))
        self.add_font("Brand", "BI", str(bold))
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

    def fill_page(self, role):
        self.set_fill_color(*self.theme.rgb(role))
        self.rect(0, 0, self.w, self.h, "F")

    def write_at(self, x, y, width, text, size, style="", role="ink", line_height=1.35, align="L", rgb=None, rich=False):
        self.set_xy(x, y)
        self.set_font("Head" if style == "B" and size >= heading_point else "Brand", style, size)
        self.set_text_color(*(rgb or self.theme.rgb(role)))
        self.multi_cell(width, size * 0.3528 * line_height * self.tightness, rich_markup(text) if rich else escaped(text), align=align, markdown=True)
        return self.get_y()

    def line_count(self, text, box: Box):
        self.set_font("Head" if box.style == "B" and box.size >= heading_point else "Brand", box.style, box.size)
        return len(self.multi_cell(box.width, box.size * 0.45, rich_markup(text), dry_run=True, output=MethodReturnValue.LINES,
                                   markdown=True))

    def slot_size(self, block, slot):
        box = layouts[block.layout].boxes[slot]
        pieces = slot_pieces(block, slot)
        for scale in shrink_steps:
            size = round(box.size * scale, 1)
            if all(self.line_count(piece, replace(box, size=size)) <= box.lines for piece in pieces):
                return size
        return round(box.size * shrink_steps[-1], 1)

    def text_height(self, text, width, size, line_height, style=""):
        return self.line_count(text, Box(width, size, 0, style)) * size * 0.3528 * line_height * self.tightness if text else 0

    def fitting_size(self, text, width, size, smallest=11):
        self.set_font("Brand", "B", size)
        while size > smallest and self.get_string_width(text) > width - 2 * self.c_margin:
            size -= 1
            self.set_font("Brand", "B", size)
        return size

    def bar(self, x, y, width=22, height=1.4, role="accent", rgb=None):
        self.set_fill_color(*(rgb or self.theme.rgb(role)))
        self.rect(x, y, width, height, "F")

    def kicker(self, x, y, text, on_dark=False):
        self.write_at(x, y, 150, text.upper(), 8.5, "B", rgb=lifted(self.theme.rgb("mood"), 0.55) if on_dark else self.theme.rgb("mood"))

    def folio(self, label, left=margin, right=page_width - margin, on_dark=False):
        role_rgb = faint_white if on_dark else self.theme.rgb("muted")
        self.set_draw_color(*((70, 82, 120) if on_dark else self.theme.rgb("rule")))
        self.set_line_width(0.2)
        self.line(left, page_height - 14, right, page_height - 14)
        self.write_at(left, page_height - 11.5, 100, label.upper(), 7.5, "B", rgb=role_rgb)
        self.write_at(right - 30, page_height - 11.5, 30, f"{self.page_no()} / {{nb}}", 7.5, "B", rgb=role_rgb, align="R")

    def glow(self, center_x, center_y, size, rings=60, clip=(0, 0, page_width, page_height)):
        with self.rect_clip(*clip):
            for ring in range(rings):
                with self.local_context(fill_opacity=0.03):
                    self.set_fill_color(*self.theme.rgb("glow"))
                    radius = size - ring * size / rings
                    self.ellipse(center_x - radius / 2, center_y - radius / 2, radius, radius, "F")

    def brand_mark(self, x, y, on_dark):
        if not self.theme.logo:
            return
        self.image(str(self.theme.logo), x, y, h=10)
        self.write_at(x + 13, y + 1.2, 120, self.theme.brand, 11, "B", rgb=white if on_dark else self.theme.rgb("ink"))
        if self.theme.tagline:
            self.write_at(x + 13, y + 6.4, 120, self.theme.tagline, 7, "B",
                          rgb=lifted(self.theme.rgb("mood"), 0.55) if on_dark else self.theme.rgb("primary"))

    def partner_strip(self, y, gap=6):
        x = margin
        for path, height in self.theme.partners:
            with Image.open(path) as picture:
                width = height * picture.width / picture.height
            if x + width > page_width - margin:
                break
            self.image(str(path), x, y + (12 - height) / 2, h=height)
            x += width + gap


def slot_pieces(block, slot):
    text = block.slots.get(slot, "")
    return paragraphs(text) if block.layout == "chapter" and slot == "body" else [text.replace(paragraph_break, "\n")]


def paragraphs(text):
    return [part.strip() for part in text.split(paragraph_break) if part.strip()]


def prepared(block: Block) -> Block:
    layout = layouts.get(block.layout)
    if not layout:
        return block
    slots = dict(block.slots)
    for slot in layout.boxes:
        if slot not in slots:
            alias = next((name for name in slots if name.startswith(f"{slot}_")), None)
            if alias:
                slots[slot] = slots.pop(alias)
    if len(slots.get("number", "")) > 3:
        digits = re.findall(r"\d+", slots["number"])
        slots["number"] = digits[0][:3] if digits else ""
    parts = len(layout.items[2]) if layout.items[2] else 0
    items = block.items
    if parts:
        items = tuple(item[:parts - 1] + (" — ".join(item[parts - 1:]),) if len(item) > parts else item + ("",) * (parts - len(item))
                      for item in items)
    if block.layout not in icon_layouts:
        items = tuple((strip_icon(item[0])[1],) + item[1:] if item else item for item in items)
    if block.layout == "process":
        items = tuple((icon_kept(item[0], lambda name: leading_number.sub("", name)),) + item[1:] for item in items)
    if block.layout == "chapter" and len(paragraphs(slots.get("body", ""))) > 2:
        parts = paragraphs(slots["body"])
        half = (len(parts) + 1) // 2
        slots["body"] = "\n\n".join(parts[:half]) + f" {paragraph_break} " + "\n\n".join(parts[half:])
    return replace(block, slots=slots, items=items)


def icon_kept(text, change):
    icon, rest = strip_icon(text)
    return (f":{icon}: " if icon else "") + change(rest)


def cell(text):
    return text.replace("|", "/").replace("\n", " ")


def is_dark(block: Block, theme: Theme) -> bool:
    layout = layouts.get(block.layout)
    if not layout or not layout.dark_variants:
        return False
    variant = block.slots.get("variant") or (theme.cover if block.layout == "cover" else layout.variants[0])
    return variant in layout.dark_variants


def balanced(blocks, theme: Theme):
    result, previous_dark = [], False
    for block in blocks:
        if previous_dark and is_dark(block, theme) and block.layout != "cover":
            logger.info("Page %d (%s) switched to its light variant to keep dark pages apart", len(result) + 1, block.layout)
            block = replace(block, slots={**block.slots, "variant": "light"})
        previous_dark = is_dark(block, theme)
        result.append(block)
    return tuple(result)


def long_date(text):
    try:
        moment = datetime.strptime(str(text).strip(), "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{moment.day} {moment:%B %Y}"


def as_flow(block: Block) -> Block:
    slots = block.slots
    if block.layout in ("process", "keypoints") and block.items:
        steps = "\n".join(f"{number}. **{strip_icon(item[0])[1]}** — {' — '.join(part for part in item[1:] if part)}"
                          for number, item in enumerate(block.items, 1))
        return Block("flow", {}, (), "\n\n".join(part for part in (f"## {slots.get('title', '')}", slots.get("lead", ""), steps,
                                                                   slots.get("takeaway", ""), block.body) if part.strip("# ")))
    if block.layout == "comparison" and slots.get("left") and slots.get("right") and block.items:
        rows = "\n".join(f"| {cell(item[0])} | {cell(' — '.join(part for part in item[1:] if part))} |" for item in block.items)
        table = f"| {cell(slots['left'])} | {cell(slots['right'])} |\n|---|---|\n{rows}"
        return Block("flow", {}, (), "\n\n".join(part for part in (f"## {slots.get('title', '')}", slots.get("lead", ""), table,
                                                                   slots.get("takeaway", ""), block.body) if part.strip("# ")))
    heading = "# " if block.layout == "cover" else "## "
    quote = f"> {slots['quote']}" + (f" — {slots['quote_by']}" if slots.get("quote_by") else "") if slots.get("quote") else ""
    columns = f"**{slots['left']}** — **{slots['right']}**" if slots.get("left") and slots.get("right") else ""
    parts = [quote if block.layout == "closing" else "", slots.get("kicker", ""), heading + " ".join(filter(None, (slots.get("number", ""), slots.get("title", "")))) if slots.get("title") else "",
             slots.get("subtitle", ""), slots.get("lead", ""), *paragraphs(slots.get("body", "")), columns,
             "\n".join(f"- {icon_kept(item[0], lambda name: f'**{name}**')} — {' — '.join(part for part in item[1:] if part)}" for item in block.items),
             quote if block.layout != "closing" else "", slots.get("context", ""),
             slots.get("takeaway", ""), block.body]
    return Block("flow", {}, (), "\n\n".join(part for part in parts if part))


def problems_in(document: Document, theme: Theme | None = None) -> list[str]:
    return [message for _, message in page_problems(document, theme)]


def page_problems(document: Document, theme: Theme | None = None, with_images: bool = False, fitted: dict | None = None,
                  credits=(), sparse: set | None = None) -> list[tuple[int, str]]:
    from markitdoc.visuals.diagrams import problems_in_diagram
    from markitdoc.visuals.infographics import problems_in_infographic
    from markitdoc.pdf.flow import chart_data
    from markitdoc.themes.themes import load_theme
    measurer = PdfPages(theme or load_theme(None))
    measurer.add_page()
    found = []
    for index, block in enumerate(document.blocks):
        block = prepared(block)
        layout = layouts.get(block.layout)
        where = f"page {index + 1} ({block.layout})"
        if layout is None:
            found.append((index, f"page {index + 1}: unknown layout '{block.layout}', use one of {sorted(layouts)}"))
            continue
        if block.layout == "flow":
            if not block.body.strip():
                found.append((index, f"{where}: body is empty"))
            found += [(index, f"{where}: chart {number} has no labels or values")
                      for number, fence in enumerate(fences(block.body, "chart"), 1) if chart_data(fence) is None]
            found += [(index, f"{where}: infographic {number}: {problem}")
                      for number, fence in enumerate(fences(block.body, "infographic"), 1) for problem in problems_in_infographic(fence)]
            found += [(index, f"{where}: diagram {number}: {problem}")
                      for number, fence in enumerate(fences(block.body, "mermaid"), 1) for problem in problems_in_diagram(fence)]
            continue
        before = len(found)
        for slot, box in layout.boxes.items():
            text = block.slots.get(slot, "")
            if not text:
                if box.required:
                    found.append((index, f"{where}: {slot} is missing"))
                continue
            smallest = replace(box, size=round(box.size * shrink_steps[-1], 1))
            for piece in slot_pieces(block, slot):
                lines = measurer.line_count(piece, smallest)
                if lines > box.lines:
                    found.append((index, f"{where}: {slot} needs {lines} lines even at the smallest size, fits {box.lines} (shorten it)"))
                if measurer.line_count(piece, box) < box.min_lines:
                    found.append((index, f"{where}: {slot} is too short to fill its page (at least {box.min_lines} lines)"))
        low, high, limits = layout.items
        if limits and not low <= len(block.items) <= high:
            found.append((index, f"{where}: needs {low} to {high} items, has {len(block.items)}"))
        if len(found) == before:
            photo = measuring_photo if with_images and block.slots.get("image") and layout.image_ratio else None
            try:
                for tightness in tightness_steps:
                    measurer.add_page()
                    measurer.tightness = tightness
                    end, limit = draw_block(measurer, block, photo, None, credits)
                    if end <= limit + 1:
                        break
            except Exception as error:
                measurer.tightness = 1.0
                found.append((index, f"{where}: could not be drawn ({type(error).__name__})"))
                continue
            measurer.tightness = 1.0
            if end > limit + 1:
                found.append((index, f"{where}: content runs {end - limit:.0f} mm past the page (shorten it)"))
            elif sparse is not None and photo is None and not (theme and theme.address) and (
                    block.layout in ("quote", "closing") or (block.layout != "cover" and end < content_limit * 0.7)):
                sparse.add(index)
            elif tightness < 1 and fitted is not None:
                fitted[index] = tightness
    return found


def fences(body, language):
    found = []
    for suffix, content in re.findall(rf"```{language}([^\n]*)\n(.*?)```", body, re.S):
        suffix = suffix.split("{")[0].strip()
        found.append((f"{language} {suffix}\n" if suffix else "") + content)
    return found


measuring_photo = "measuring photo"


def placed(pdf, image, x, y, width, height, work_folder, fades=(), description="Photograph"):
    if image == measuring_photo:
        return
    pdf.image(fitted_image(image, width, height, work_folder, fades, pdf.photos, pdf.theme), x, y, width, height,
              alt_text=description)
    if pdf.photo_credit:
        credit_on_photo(pdf, x, y, width, height, *pdf.photo_credit)


def credit_on_photo(pdf, x, y, width, height, credit, source):
    pdf.set_font("Brand", "", 5.5)
    text = credit if pdf.get_string_width(credit) < width - 8 else credit.split(",")[0]
    text_width = pdf.get_string_width(text) + 3
    left, top = x + width - text_width - 2, y + height - 6
    with pdf.local_context(fill_opacity=0.45):
        pdf.set_fill_color(0, 0, 0)
        pdf.rect(left, top, text_width, 4.2, "F")
    pdf.set_text_color(*white)
    pdf.set_xy(left + 1.5, top + 0.6)
    pdf.cell(text_width - 3, 3, text, link=source)


def interest_box(picture, target):
    small = picture.copy()
    small.thumbnail((160, 160))
    scale = picture.width / small.width
    edges = numpy.asarray(small.convert("L").filter(ImageFilter.FIND_EDGES), dtype=float)
    saturation = numpy.asarray(small.convert("HSV"), dtype=float)[:, :, 1]
    interest = edges + 0.5 * saturation
    rows, columns = interest.shape
    if columns / rows > target:
        window_height, window_width = rows, max(1, int(rows * target))
    else:
        window_width, window_height = columns, max(1, int(columns / target))
    summed = numpy.pad(interest.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best, best_score = (0, 0), -1.0
    for top in range(0, rows - window_height + 1, max(1, (rows - window_height) // 24 or 1)):
        for left in range(0, columns - window_width + 1, max(1, (columns - window_width) // 24 or 1)):
            total = (summed[top + window_height, left + window_width] - summed[top, left + window_width]
                     - summed[top + window_height, left] + summed[top, left])
            centre = abs((left + window_width / 2) / columns - 0.5) + abs((top + window_height / 2) / rows - 0.45)
            score = total * (1 - 0.35 * centre)
            if score > best_score:
                best, best_score = (top, left), score
    top, left = best
    box_width, box_height = window_width * scale, window_height * scale
    return (int(left * scale), int(top * scale), int(min(picture.width, left * scale + box_width)),
            int(min(picture.height, top * scale + box_height)))


def treated(picture, treatment, theme):
    picture = ImageOps.autocontrast(picture, cutoff=1)
    if treatment == "mono":
        return ImageOps.grayscale(picture).convert("RGB")
    if treatment == "duotone" and theme is not None:
        return ImageOps.colorize(ImageOps.grayscale(picture), black=theme.rgb("night"), white=lifted(theme.rgb("paper"), 0.2))
    return picture


def fitted_image(path: Path, width, height, work_folder: Path, fades=(), treatment="natural", theme=None):
    picture = Image.open(path).convert("RGB")
    picture = treated(picture.crop(interest_box(picture, width / height)), treatment, theme)
    for top_ratio, bottom_ratio, start, end, rgb in fades:
        mask = Image.new("L", (1, picture.height), 0)
        first, last = int(picture.height * top_ratio), int(picture.height * bottom_ratio)
        for row in range(first, last):
            mask.putpixel((0, row), int(255 * (start + (end - start) * (row - first) / max(1, last - first - 1))))
        picture = Image.composite(Image.new("RGB", picture.size, rgb), picture, mask.resize(picture.size))
    output = work_folder / f"{path.stem}_{int(width)}x{int(height)}_{zlib.crc32(repr(fades).encode()):08x}_{treatment}.jpg"
    picture.save(output, "JPEG", quality=88)
    return str(output)


def page_heading(pdf, block, label, top=22):
    pdf.kicker(margin, top, label)
    end = pdf.write_at(margin, top + 8, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    if block.slots.get("lead"):
        end = pdf.write_at(margin, end + 4, content_width, block.slots["lead"], pdf.slot_size(block, "lead"), role="body", line_height=1.45, rich=True)
    return end


def cover_text(pdf, block, on_dark, top):
    pdf.bar(margin, top - 8, rgb=lifted(pdf.theme.rgb("mood"), 0.55) if on_dark else pdf.theme.rgb("mood"))
    end = pdf.write_at(margin, top, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B",
                       rgb=white if on_dark else pdf.theme.rgb("ink"), line_height=1.08)
    return pdf.write_at(margin, end + 6, 150, block.slots["subtitle"], pdf.slot_size(block, "subtitle"), rgb=soft_white if on_dark else pdf.theme.rgb("body"),
                        line_height=1.4)


def draw_cover(pdf: PdfPages, block: Block, image, work_folder):
    variant = block.slots.get("variant") or ("photo" if image else pdf.theme.cover if pdf.theme.cover in ("dark", "light") else "dark")
    if variant in ("photo", "split", "dark") and not image:
        variant = "light"
    if variant == "company" and not pdf.theme.address:
        variant = "light"
    kicker = block.slots.get("kicker", "")
    if variant == "company":
        pdf.fill_page("paper")
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(0, 0, page_width, 150, "F")
        pdf.glow(page_width - 20, 40, 190, clip=(0, 0, page_width, 150))
        pdf.brand_mark(margin, 18, on_dark=False)
        pdf.kicker(margin, 112, kicker)
        cover_text(pdf, block, on_dark=False, top=128)
        y = page_height - 40 - len(pdf.theme.address) * 4.6
        for line in pdf.theme.address:
            y = pdf.write_at(margin, y, 90, line, 8.5, role="body", line_height=1.35)
        pdf.partner_strip(page_height - 30)
        return 0, page_height
    if variant == "light":
        pdf.fill_page("paper")
        pdf.brand_mark(margin, 18, on_dark=False)
        pdf.kicker(margin, 40, kicker)
        cover_text(pdf, block, on_dark=False, top=118)
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, page_height - 40, page_width - margin, page_height - 40)
        pdf.write_at(margin, page_height - 34, content_width / 2, long_date(getattr(pdf, "meta_date", "")), 9, role="muted")
        pdf.write_at(page_width / 2, page_height - 34, content_width / 2, pdf.theme.brand or "", 9, role="muted", align="R")
        return 0, page_height
    if variant == "split":
        pdf.fill_page("paper")
        pdf.set_fill_color(*pdf.theme.rgb("night"))
        pdf.rect(0, 0, 76, page_height, "F")
        if image:
            placed(pdf, image, 0, 0, 76, page_height, work_folder, description=block.slots.get("image", "Photograph"))
        else:
            pdf.glow(38, 200, 160, clip=(0, 0, 76, page_height))
        pdf.brand_mark(88, 20, on_dark=False)
        pdf.kicker(88, 100, kicker)
        pdf.bar(88, 110, role="mood")
        size = 32
        while size > 20 and pdf.line_count(block.slots["title"], Box(104, size, 0, "B")) > 4:
            size -= 2
        end = pdf.write_at(88, 118, 104, block.slots["title"], size, "B", line_height=1.1)
        pdf.write_at(88, end + 6, 104, block.slots["subtitle"], pdf.slot_size(block, "subtitle"), role="body", line_height=1.45)
        return 0, page_height
    night = pdf.theme.rgb("night")
    pdf.fill_page("night")
    if variant == "photo":
        fades = ((0, 0.3, 0.7, 0.0, night), (0.38, 0.62, 0.0, 0.93, night), (0.62, 1.0, 0.93, 0.97, night))
        placed(pdf, image, 0, 0, page_width, page_height, work_folder, fades, block.slots.get("image", "Photograph"))
    else:
        pdf.glow(page_width - 30, 70, 230)
    pdf.brand_mark(margin, 16, on_dark=True)
    pdf.kicker(margin, 34 if pdf.theme.logo else 20, kicker, on_dark=True)
    cover_text(pdf, block, on_dark=True, top=page_height - 100 if variant == "photo" else 112)
    return 0, page_height


def draw_summary(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    pdf.kicker(margin, 22, "Executive summary")
    end = pdf.write_at(margin, 30, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    end = pdf.write_at(margin, end + 4, content_width, block.slots["lead"], pdf.slot_size(block, "lead"), line_height=1.45, rich=True)
    count, gap, top = len(block.items), 5, end + 9
    width = (content_width - gap * (count - 1)) / max(count, 1)
    card = max([30] + [20 + pdf.text_height(label, width - 8, 8.5, 1.3) for _, label in block.items])
    for index, (value, label) in enumerate(block.items):
        x = margin + index * (width + gap)
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(x, top, width, card, "F")
        pdf.bar(x, top, 1.2, card, role="mood")
        size = pdf.fitting_size(value, width - 8, 20)
        pdf.write_at(x + 5, top + 5 + (20 - size) * 0.18, width - 8, value, size, "B", "mood", line_height=1.0)
        pdf.write_at(x + 5, top + 16, width - 8, label, 8.5, role="muted", line_height=1.3)
    y = top + card + 10
    for paragraph in paragraphs(block.slots["body"]):
        y = pdf.write_at(margin, y, text_width, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True) + 3
    pdf.folio("Executive summary")
    return y, content_limit


def draw_divider(pdf: PdfPages, block: Block, image, work_folder):
    dark = block.slots.get("variant") == "dark"
    pdf.fill_page("night" if dark else "surface")
    if dark:
        pdf.glow(page_width - 10, page_height - 60, 260, rings=70)
    else:
        pdf.bar(0, 0, 6, page_height, role="mood")
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    pdf.write_at(margin, 64, 80, block.slots.get("number", ""), pdf.slot_size(block, "number"), "B", rgb=tone, line_height=1.0)
    pdf.bar(margin, 96, rgb=tone)
    end = pdf.write_at(margin, 104, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B",
                       rgb=white if dark else pdf.theme.rgb("ink"), line_height=1.1)
    end = pdf.write_at(margin, end + 6, 150, block.slots.get("lead", ""), pdf.slot_size(block, "lead"), rgb=soft_white if dark else pdf.theme.rgb("body"),
                       line_height=1.45)
    if block.items:
        y = max(end + 18, 190)
        pdf.write_at(margin, y, 120, "IN THIS PART", 7.5, "B", rgb=tone)
        y += 7
        for number, (entry,) in enumerate(block.items, 1):
            pdf.set_draw_color(*((70, 82, 120) if dark else pdf.theme.rgb("rule")))
            pdf.line(margin, y, margin + 120, y)
            pdf.write_at(margin, y + 2.5, 10, f"{number:02d}", 9, "B", rgb=tone)
            y = pdf.write_at(margin + 12, y + 2.5, 108, entry, 10, rgb=soft_white if dark else pdf.theme.rgb("ink")) + 2.5
        end = y
    return end, content_limit


def chapter_text_height(pdf, block):
    column = content_width / 2 - 4
    tallest = max((pdf.text_height(part, column, 9.6, 1.55) for part in paragraphs(block.slots["body"])), default=0)
    quote = pdf.text_height(block.slots.get("quote", ""), content_width - 6, 12.5, 1.4, "I") + 8 if block.slots.get("quote") else 0
    lead = pdf.text_height(block.slots.get("lead", ""), content_width, 12.5, 1.45) + 5
    title = pdf.text_height(block.slots["title"], content_width - 22, 21, 1.15)
    return title + lead + tallest + quote + 30


def draw_chapter(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    plain = not image and block.slots.get("variant") != "band"
    room = content_limit - chapter_text_height(pdf, block)
    band = 0 if plain else max(36, min(108 if image else 72, room))
    if image:
        placed(pdf, image, 0, 0, page_width, band, work_folder, ((0.6, 1.0, 0.0, 0.35, (0, 0, 0)),), block.slots.get("image", "Photograph"))
    elif not plain:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(0, 0, page_width, band, "F")
        pdf.bar(0, band - 1.4, page_width, 1.4, role="mood")
    number = block.slots.get("number", "")
    top = band + 10 if band else 26
    if number:
        pdf.write_at(margin, top, 40, number, 30, "B", "mood", line_height=1.0)
    title_x = margin + 22 if number else margin
    title_end = pdf.write_at(title_x, top + 0.5, page_width - margin - title_x, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    lead_end = pdf.write_at(margin, max(title_end, top + 12) + 5, content_width, block.slots.get("lead", ""), pdf.slot_size(block, "lead"),
                            line_height=1.45, rich=True)
    column_width, top = content_width / 2 - 4, lead_end + 6
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.line(margin, top - 2, page_width - margin, top - 2)
    left, right = (paragraphs(block.slots["body"]) + [""])[:2]
    body_size = pdf.slot_size(block, "body")
    left_end = pdf.write_at(margin, top + 2, column_width, left, body_size, role="body", line_height=1.55, rich=True)
    right_end = pdf.write_at(margin + column_width + 8, top + 2, column_width, right, body_size, role="body", line_height=1.55, rich=True)
    end = max(left_end, right_end)
    if block.slots.get("quote"):
        quote_top = end + 8 * pdf.tightness ** 3
        end = pdf.write_at(margin + 6, quote_top, content_width - 6, block.slots["quote"], pdf.slot_size(block, "quote"), "I", line_height=1.4)
        pdf.bar(margin, quote_top, 1.2, end - quote_top, role="mood")
    pdf.folio(f"Chapter {number}" if number else "Chapter")
    return end, content_limit


def draw_figures(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "Key figures")
    count = len(block.items)
    columns = 2 if count == 4 else 3
    rows = (count + columns - 1) // columns
    gap, top = 8, end + 12
    body_height = pdf.text_height(block.slots.get("body", ""), content_width, 10, 1.6) + 10 if block.slots.get("body") else 0
    cell_height = min(78, (content_limit - top - body_height) / rows)
    width = (content_width - gap * (columns - 1)) / columns
    bottom, overflow = top, 0
    shift = 9 if any(strip_icon(item[0])[0] for item in block.items) else 0
    for index, (value, label, *note) in enumerate(block.items):
        icon, value = strip_icon(value)
        x, y = margin + (index % columns) * (width + gap), top + (index // columns) * cell_height
        pdf.bar(x, y, width, 0.8, role="mood")
        if icon:
            pdf.image(io.BytesIO(icon_svg(icon, pdf.theme.rgb("mood"))), x=x, y=y + 4, w=7, h=7)
        size = pdf.fitting_size(value, width, 34, 18)
        pdf.write_at(x, y + 6 + shift, width, value, size, "B", "mood", line_height=1.0)
        label_end = pdf.write_at(x, y + 22 + shift, width, label, 10.5, "B", line_height=1.3)
        note_end = pdf.write_at(x, label_end + 1.5, width, note[0] if note else "", 9, role="body", line_height=1.45)
        overflow = max(overflow, note_end + 4 - (y + cell_height))
        bottom = max(bottom, note_end)
    end = max(bottom, top + rows * cell_height - 10) + max(overflow, 0)
    if block.slots.get("body"):
        end = pdf.write_at(margin, end + 8, content_width, block.slots["body"], pdf.slot_size(block, "body"), role="body", line_height=1.6, rich=True)
    pdf.folio("Key figures")
    return end, content_limit


def draw_keypoints(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "Key findings")
    points = [(*strip_icon(heading), text) for heading, text in block.items]
    heights = [pdf.text_height(heading, 130, 13, 1.25, "B") + pdf.text_height(text, 130, 10, 1.55) + 3 for _, heading, text in points]
    base_gap = 10 * pdf.tightness ** 3
    spare = max(0, content_limit - end - 14 - sum(heights) - base_gap * len(heights))
    gap = base_gap + min(4, spare / max(len(heights), 1))
    y = end + 12
    for number, (icon, heading, text) in enumerate(points, 1):
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, y, page_width - margin, y)
        if icon:
            pdf.image(io.BytesIO(icon_svg(icon, pdf.theme.rgb("mood"))), x=margin, y=y + 5, w=11, h=11)
        else:
            pdf.write_at(margin, y + 5, 30, f"{number:02d}", 26, "B", "mood", line_height=1.0)
        heading_end = pdf.write_at(margin + 40, y + 5, 130, heading, 13, "B", line_height=1.25)
        y = pdf.write_at(margin + 40, heading_end + 2, 130, text, 10, role="body", line_height=1.55, rich=True) + gap
    pdf.folio("Key findings")
    return y - gap, content_limit


def draw_matrix(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "At a glance")
    gap, top = 6, end + 12
    width = (content_width - gap) / 2
    height = min(96, (content_limit - top - gap) / 2)
    mood = pdf.theme.rgb("mood")
    tones = (mood, lifted(mood, 0.25), lifted(mood, 0.45), pdf.theme.rgb("muted"))
    bottom, overflow = top, 0
    for index, (label, text) in enumerate(block.items[:4]):
        x, y = margin + (index % 2) * (width + gap), top + (index // 2) * (height + gap)
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(x, y, width, height, "F")
        pdf.bar(x, y, width, 1.4, rgb=tones[index])
        label_end = pdf.write_at(x + 7, y + 8, width - 14, label, 14, "B", line_height=1.2)
        text_end = pdf.write_at(x + 7, label_end + 3, width - 14, text, 10, role="body", line_height=1.5, rich=True)
        overflow = max(overflow, text_end + 4 - (y + height))
        bottom = max(bottom, y + height)
    pdf.folio("At a glance")
    return bottom + max(overflow, 0), content_limit


def draw_quote(pdf: PdfPages, block: Block, image, work_folder):
    dark = block.slots.get("variant") == "dark"
    pdf.fill_page("night" if dark else "surface")
    if dark:
        pdf.glow(30, page_height - 40, 220, rings=70)
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    height = (pdf.text_height(block.slots["quote"], content_width - 10, 26, 1.3, "I")
              + pdf.text_height(block.slots.get("context", ""), pdf.slot_size(block, "context"), 10.5, 1.55) + 50)
    top = max(50, (page_height - height) / 2)
    pdf.write_at(margin, top - 34, 40, "“", 110, "B", rgb=tone, line_height=0.8)
    end = pdf.write_at(margin + 10, top, content_width - 10, block.slots["quote"], pdf.slot_size(block, "quote"), "I",
                       rgb=white if dark else pdf.theme.rgb("ink"), line_height=1.3)
    if block.slots.get("quote_by"):
        pdf.bar(margin + 10, end + 8, rgb=tone)
        end = pdf.write_at(margin + 10, end + 13, 150, block.slots["quote_by"], pdf.slot_size(block, "quote_by"), "B", rgb=tone)
    if block.slots.get("context"):
        end = pdf.write_at(margin + 10, end + 8, 130, block.slots["context"], pdf.slot_size(block, "context"),
                           rgb=soft_white if dark else pdf.theme.rgb("body"), line_height=1.55)
    return end, content_limit


def draw_comparison(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "Comparison")
    column, top = content_width / 2 - 3, end + 10
    for side, x, role in (("left", margin, "muted"), ("right", margin + column + 6, "mood")):
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(x, top, column, 14, "F")
        pdf.bar(x, top, column, 1.2, role=role)
        pdf.write_at(x + 5, top + 4.5, column - 10, block.slots[side], 13, "B", role)
    takeaway = block.slots.get("takeaway", "")
    takeaway_height = pdf.text_height(takeaway, content_width - 14, 11, 1.45, "B") + 16 if takeaway else 0
    rows = [max(pdf.text_height(left, column - 10, 9.8, 1.45), pdf.text_height(right, column - 10, 9.8, 1.45)) for left, right in block.items]
    spare = max(0, content_limit - top - 18 - sum(rows) - 6 * len(rows) - takeaway_height)
    padding = 3 + min(2, spare / max(len(rows), 1) / 2)
    y = top + 18
    for left, right in block.items:
        ends = [pdf.write_at(x + 5, y + padding, column - 10, text, 9.8, role="body", line_height=1.45, rich=True)
                for text, x in ((left, margin), (right, margin + column + 6))]
        y = max(ends) + padding
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, y, page_width - margin, y)
    if takeaway:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        box_end = y + 8 + takeaway_height - 8
        pdf.rect(margin, y + 8, content_width, takeaway_height - 8, "F")
        pdf.bar(margin, y + 8, 1.4, takeaway_height - 8, role="mood")
        pdf.write_at(margin + 8, y + 12, content_width - 14, takeaway, 11, "B", line_height=1.45)
        y = box_end
    pdf.folio("Comparison")
    return y, content_limit


def draw_process(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "How it works")
    count = len(block.items)
    if block.slots.get("variant") == "horizontal" and count <= 4:
        width, top = content_width / count, end + 18
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.set_line_width(0.8)
        pdf.line(margin + width / 2, top + 7, margin + width * (count - 0.5), top + 7)
        bottom = top
        for index, (title, description) in enumerate(block.items):
            icon, title = strip_icon(title)
            center = margin + width * (index + 0.5)
            pdf.set_fill_color(*pdf.theme.rgb("mood"))
            pdf.ellipse(center - 7, top, 14, 14, "F")
            if icon:
                pdf.image(io.BytesIO(icon_svg(icon, white)), x=center - 4, y=top + 3, w=8, h=8)
            else:
                pdf.write_at(center - 7, top + 3.4, 14, str(index + 1), 13, "B", rgb=white, align="C", line_height=1.0)
            title_end = pdf.write_at(margin + width * index + 3, top + 22, width - 6, title, 12.5, "B", line_height=1.2, align="C")
            bottom = max(bottom, pdf.write_at(margin + width * index + 3, title_end + 3, width - 6, description, 9.6,
                                              role="body", line_height=1.5, align="C", rich=True))
        pdf.folio("Process")
        return bottom, content_limit
    heights = [pdf.text_height(description, content_width - 20, 9.8, 1.45) + 10 for _, description in block.items]
    top, axis = end + 12, margin + 7
    spare = max(0, content_limit - top - sum(heights))
    steps = [height + min(6, spare / max(count, 1)) for height in heights]
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.set_line_width(0.8)
    pdf.line(axis, top + 7, axis, top + sum(steps[:-1]) + 7)
    y = top
    for index, ((title, description), step) in enumerate(zip(block.items, steps)):
        icon, title = strip_icon(title)
        pdf.set_fill_color(*pdf.theme.rgb("mood"))
        pdf.ellipse(axis - 7, y, 14, 14, "F")
        if icon:
            pdf.image(io.BytesIO(icon_svg(icon, white)), x=axis - 4, y=y + 3, w=8, h=8)
        else:
            pdf.write_at(axis - 7, y + 3.4, 14, str(index + 1), 13, "B", rgb=white, align="C", line_height=1.0)
        title_end = pdf.write_at(axis + 13, y + 1, content_width - 20, title, 13, "B", line_height=1.2)
        bottom = pdf.write_at(axis + 13, max(y + 8, title_end + 1.5), content_width - 20, description, 9.8, role="body",
                              line_height=1.45, rich=True)
        y += step
    pdf.folio("Process")
    return bottom, content_limit


def draw_timeline(pdf: PdfPages, block: Block, image, work_folder):
    variant = block.slots.get("variant", "vertical")
    dark = variant == "dark"
    pdf.fill_page("night" if dark else "paper")
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    ink = white if dark else pdf.theme.rgb("ink")
    body = faint_white if dark else pdf.theme.rgb("body")
    pdf.kicker(margin, 22, "Timeline", on_dark=dark)
    end = pdf.write_at(margin, 30, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B", rgb=ink, line_height=1.1)
    end = pdf.write_at(margin, end + 4, 150, block.slots.get("lead", ""), pdf.slot_size(block, "lead"),
                       rgb=(200, 206, 222) if dark else body, line_height=1.45)
    count = len(block.items)
    if variant == "horizontal" and count <= 5:
        width = content_width / count
        heights = [pdf.text_height(event, width - 8, 13, 1.25, "B") + pdf.text_height(description, width - 8, 10.5, 1.5) + 12
                   for _, event, description in block.items]
        axis = max(end + 40, (end + content_limit) / 2 - max(heights) / 2)
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.set_line_width(0.4)
        pdf.line(margin, axis, page_width - margin, axis)
        bottom = axis
        for index, (when, event, description) in enumerate(block.items):
            x = margin + index * width
            pdf.write_at(x, axis - 16, width - 6, when, 18, "B", rgb=tone, line_height=1.0)
            pdf.set_fill_color(*tone)
            pdf.ellipse(x, axis - 2, 4, 4, "F")
            event_end = pdf.write_at(x, axis + 8, width - 8, event, 13, "B", rgb=ink, line_height=1.25)
            bottom = max(bottom, pdf.write_at(x, event_end + 2.5, width - 8, description, 10.5, rgb=body, line_height=1.5, rich=True))
        pdf.folio("Timeline", on_dark=dark)
        return bottom, content_limit
    top, axis, text_x = end + 14, margin + 34, margin + 42
    text_width = page_width - margin - text_x
    pdf.set_draw_color(*((70, 82, 120) if dark else pdf.theme.rgb("rule")))
    pdf.set_line_width(0.4)
    y, marks = top, []
    for when, event, description in block.items:
        marks.append(y)
        pdf.write_at(margin, y - 0.6, 30, when, 10.5, "B", rgb=tone, align="R", line_height=1.2)
        event_end = pdf.write_at(text_x, y - 0.8, text_width, event, 12, "B", rgb=ink, line_height=1.25)
        y = pdf.write_at(text_x, event_end + 1.5, text_width, description, 10, rgb=body, line_height=1.5, rich=True) + 9
    pdf.line(axis, marks[0] + 2, axis, marks[-1] + 2)
    for mark in marks:
        pdf.set_fill_color(*(pdf.theme.rgb("night") if dark else pdf.theme.rgb("paper")))
        pdf.set_draw_color(*tone)
        pdf.set_line_width(0.6)
        pdf.ellipse(axis - 1.9, mark + 0.1, 3.8, 3.8, "DF")
    pdf.folio("Timeline", on_dark=dark)
    return y - 9, content_limit


def draw_feature(pdf: PdfPages, block: Block, image, work_folder):
    if not image and not block.items:
        story = replace(block, layout="chapter", slots={**block.slots, "variant": "plain"})
        return draw_chapter(pdf, story, None, work_folder)
    pdf.fill_page("paper")
    image_left = block.slots.get("variant", "left") == "left"
    panel = 92 if image else 64
    panel_x = 0 if image_left else page_width - panel
    if image:
        placed(pdf, image, panel_x, 0, panel, page_height, work_folder, description=block.slots.get("image", "Photograph"))
    else:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(panel_x, 0, panel, page_height, "F")
        pdf.bar(panel_x + (panel - 1.2 if image_left else 0), 0, 1.2, page_height, role="mood")
        y = (page_height - 46 * len(block.items)) / 2
        for figure, label in block.items:
            size = pdf.fitting_size(figure, panel - 20, 30, 16)
            pdf.write_at(panel_x + 10, y, panel - 20, figure, size, "B", "mood", line_height=1.0)
            pdf.write_at(panel_x + 10, y + 14, panel - 20, label, 9, role="muted", line_height=1.35)
            y += 46
    x = panel + 12 if image_left else margin
    width = page_width - panel - 12 - margin
    pdf.kicker(x, 22, "Feature")
    end = pdf.write_at(x, 30, width, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    for paragraph in paragraphs(block.slots["body"]):
        end = pdf.write_at(x, end + 5, width, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True)
    if image and block.items and end + 10 + 25 * len(block.items) > content_limit:
        column = width / len(block.items)
        y, end = end + 10, end + 10
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(x, y, x + width, y)
        for index, (figure, label) in enumerate(block.items):
            left = x + index * column
            size = pdf.fitting_size(figure, column - 4, 16, 11)
            pdf.write_at(left, y + 4, column - 4, figure, size, "B", "mood", line_height=1.0)
            end = max(end, pdf.write_at(left, y + 12, column - 4, label, 8.5, role="muted", line_height=1.3))
    elif image:
        y = end + 10
        for figure, label in block.items:
            pdf.set_draw_color(*pdf.theme.rgb("rule"))
            pdf.line(x, y, x + width, y)
            pdf.write_at(x, y + 4, width, figure, 22, "B", "mood", line_height=1.0)
            y = pdf.write_at(x, y + 13, width, label, 9.5, role="muted", line_height=1.3) + 5
        end = y - 5
    pdf.folio("Feature", left=x, right=x + width)
    return end, content_limit


def draw_closing(pdf: PdfPages, block: Block, image, work_folder, credits=()):
    pdf.fill_page("paper")
    company = block.slots.get("variant") == "company" and pdf.theme.address
    bottom = page_height - 19
    if company:
        company_top = page_height - 36 - 16 - len(pdf.theme.address) * 5
        pdf.brand_mark(margin, company_top, on_dark=False)
        for index, line in enumerate(pdf.theme.address):
            pdf.write_at(margin, company_top + 16 + index * 5, 120, line, 9, role="body")
        pdf.partner_strip(page_height - 34)
        bottom = company_top - 8
    if credits:
        credit_height = 6 + sum(pdf.text_height(credit, content_width, 7, 1.4) + 1.2 for credit in credits)
        y = bottom - credit_height
        pdf.write_at(margin, y, 100, "IMAGE CREDITS", 7.5, "B", "mood")
        y += 6
        for credit in credits:
            y = pdf.write_at(margin, y, content_width, credit, 7, role="muted", line_height=1.4) + 1.2
        bottom -= credit_height + 6
    text_height = (pdf.text_height(block.slots["title"], content_width, 17, 1.35, "B")
                   + sum(pdf.text_height(paragraph, text_width, 10.5, 1.55) + 4 for paragraph in paragraphs(block.slots["body"])))
    end = 26 if block.slots.get("quote") else max(40, (bottom - text_height) / 2 - 10)
    if block.slots.get("quote"):
        pdf.write_at(margin, 26, 30, "“", 90, "B", "mood", line_height=0.8)
        end = pdf.write_at(margin + 4, 52, content_width - 8, block.slots["quote"], pdf.slot_size(block, "quote"), "I", line_height=1.3)
        if block.slots.get("quote_by"):
            end = pdf.write_at(margin + 4, end + 5, 150, "— " + block.slots["quote_by"], pdf.slot_size(block, "quote_by"), "B", "muted")
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, end + 12, page_width - margin, end + 12)
        end += 20
    end = pdf.write_at(margin, end, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B")
    for paragraph in paragraphs(block.slots["body"]):
        end = pdf.write_at(margin, end + 4, text_width, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True)
    if not company:
        pdf.folio("Closing")
    return end, bottom


drawers = {"cover": draw_cover, "summary": draw_summary, "divider": draw_divider, "chapter": draw_chapter,
           "figures": draw_figures, "keypoints": draw_keypoints, "matrix": draw_matrix, "quote": draw_quote,
           "comparison": draw_comparison, "process": draw_process, "timeline": draw_timeline, "feature": draw_feature}


def draw_block(pdf, block, image, work_folder, credits):
    if block.layout == "closing":
        return draw_closing(pdf, block, image, work_folder, credits)
    return drawers[block.layout](pdf, block, image, work_folder)


def creation_date(written):
    try:
        if written:
            return datetime.combine(date.fromisoformat(str(written)), time.min, tzinfo=timezone.utc)
    except ValueError:
        pass
    epoch = os.getenv("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return datetime.combine(date.today(), time.min, tzinfo=timezone.utc)


def render_pdf(document: Document, theme: Theme, output_path: Path, work_folder: Path, images=None, credits=()):
    from markitdoc.pdf.flow import FlowPages, fitted_spacing, render_flow, render_toc
    images = images or {}
    blocks = balanced([prepared(block) for block in document.blocks], theme)
    first = blocks[0]
    title = first.slots.get("title") or next((line.lstrip("# ").strip() for line in first.body.splitlines()
                                             if line.startswith("# ")), "Document")
    pdf = FlowPages(theme, title, document.meta.get("style") == "plain")
    pdf.table_style = str(document.meta.get("tables", "lined")).lower()
    pdf.flow_images = {key[1]: path for key, path in images.items() if isinstance(key, tuple)}
    pdf.photos = str(document.meta.get("photos", "natural")).lower()
    pdf.work_folder = work_folder
    pdf.targets = frozenset(match.group(1) for block in blocks for line in block.body.splitlines()
                            if line.lstrip().startswith("#") and (match := anchor.search(line)))
    pdf.numbering = str(document.meta.get("numbering", "")).lower() == "decimal"
    pdf.header_text, pdf.footer_text, pdf.classification, pdf.watermark = (str(document.meta.get(key, "")).strip().strip("'\"")
                                                                            for key in ("header", "footer", "classification", "watermark"))
    pdf.meta_date = str(document.meta.get("date", ""))
    pdf.lang = str(document.meta.get("lang", "en")) or "en"
    pdf.notes_at_page_bottom = str(document.meta.get("notes", "")).lower() == "page"
    pdf.set_lang(pdf.lang)
    pdf.scale = TEXT_SIZES.get(str(document.meta.get("text_size", "regular")).lower(), 1.0)
    pdf.set_title(title)
    pdf.set_author(str(document.meta.get("author", "")).strip("'\" ") or theme.brand or "")
    pdf.set_creation_date(creation_date(document.meta.get("date")))
    pdf.set_subject(str(document.meta.get("subject", "")) or title)
    pdf.viewer_preferences = ViewerPreferences(display_doc_title=True)
    toc_at = 1 if first.layout == "cover" and len(blocks) > 1 else 0
    wants_toc = document.meta.get("toc") in ("true", "yes", "on")
    for index, block in enumerate(blocks):
        fresh_page = False
        if wants_toc and index == toc_at:
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=22)
            pdf.add_page()
            pdf.decorate = block.layout == "flow"
            pdf.insert_toc_placeholder(render_toc, pages=1, allow_extra_pages=True)
            fresh_page = block.layout != "flow"
        if block.layout == "flow" and not block.body.strip():
            continue
        if block.layout == "flow":
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=22)
            if not (wants_toc and index == toc_at) and (index == 0 or blocks[index - 1].layout != "flow"):
                pdf.add_page()
            next_is_designed = index + 1 < len(blocks) and blocks[index + 1].layout != "flow"
            body = trailing_headings.sub("", block.body.rstrip()) if next_is_designed else block.body
            if not body.strip():
                continue
            pdf.spacing = fitted_spacing(pdf, body) if next_is_designed else 1.0
            render_flow(pdf, body)
            pdf.spacing = 1.0
            continue
        pdf.decorate = False
        pdf.set_auto_page_break(False)
        if not fresh_page:
            pdf.add_page()
        if block.slots.get("title") and block.layout in sectioned_layouts:
            pdf.start_section(block.slots["title"].replace("**", "").replace("__", ""), level=0, strict=False)
        try:
            pdf.tightness = float(block.slots.get("tightness", 1.0))
            picture = images.get(index)
            pdf.photo_credit = picture[2:4] if picture else None
            draw_block(pdf, block, picture[0] if picture else None, work_folder, ())
            pdf.photo_credit = None
            pdf.tightness = 1.0
        except Exception:
            logger.exception("Page %d (%s) failed to draw; shown as text instead", index + 1, block.layout)
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=22)
            pdf.fill_page("paper")
            pdf.set_xy(pdf.l_margin, 24)
            render_flow(pdf, as_flow(block).body)
    pdf.output(str(output_path))
    logger.info("PDF rendered: %d blocks, %d pages, theme %s, contents %s, %d images",
                len(blocks), pdf.pages_count, theme.name, "yes" if wants_toc else "no", len(images))
    return output_path
