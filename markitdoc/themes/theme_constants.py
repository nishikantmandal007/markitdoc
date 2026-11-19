import re

from markitdoc.utils.constants import ASSETS_FOLDER

THEMES_FOLDER = ASSETS_FOLDER / "themes"
DEFAULT_THEME = "professional"
LEGACY_THEME_NAMES = {"default": DEFAULT_THEME}
COLOR_ROLES = ("primary", "accent", "ink", "body", "muted", "paper", "surface", "night", "rule", "success", "danger")
FONT_ROLES = ("heading", "body", "italic")
COVER_STYLES = ("dark", "light", "photo")
HEX_COLOR = re.compile(r"^[0-9A-Fa-f]{6}$")
MINIMUM_CONTRAST = 4.5
DEFAULT_PALETTE = "graphite"
NIGHT_BASE = "0A0C12"

PALETTES = {
    "ink": ("1F2937", "C2410C", "near-black with a vermilion highlight: editorial, finance, strong opinions"),
    "ocean": ("0E7490", "F59E0B", "deep cyan: technology, data, science, maritime"),
    "forest": ("166534", "B45309", "green: sustainability, health, nature, agriculture"),
    "plum": ("6B21A8", "DB2777", "violet: creative work, education, culture, people"),
    "terracotta": ("9A3412", "0F766E", "burnt orange: hospitality, design, history, community"),
    "navy": ("1E3A8A", "D97706", "dark blue: banking, government, insurance"),
    "crimson": ("9F1239", "334155", "deep red: risk, incidents, security, urgency"),
    "teal": ("0F766E", "7C3AED", "teal: healthcare, wellbeing, services, operations"),
    "ochre": ("92400E", "1E40AF", "ochre: heritage, archives, research, long histories"),
    "graphite": ("334155", "2563EB", "cool grey with a blue spark: legal, policy, engineering, neutral"),
}
ACCENTS = {name: accent for name, (accent, _, _) in PALETTES.items()}
PAPERS = {"white": "professional", "warm": "editorial"}
FONT_PAIRS = {
    "inter": ("Inter-Bold.ttf", "Inter-Regular.ttf", "Inter-Bold.ttf", "Inter-Italic.ttf", "modern sans, neutral and clear"),
    "serif-heads": ("PTSerif-Bold.ttf", "Inter-Regular.ttf", "Inter-Bold.ttf", "Inter-Italic.ttf",
                    "serif headings with a sans body: editorial reports, magazines, histories"),
    "serif": ("PTSerif-Bold.ttf", "PTSerif-Regular.ttf", "PTSerif-Bold.ttf", "PTSerif-Italic.ttf",
              "classic serif throughout: letters, legal, policy, long reading"),
    "plex": ("IBMPlexSans-Bold.ttf", "IBMPlexSans-Regular.ttf", "IBMPlexSans-Bold.ttf", "IBMPlexSans-Italic.ttf",
             "engineered sans: technical, engineering, data"),
    "noto": ("NotoSans-Bold.ttf", "NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSans-Italic.ttf",
             "humanist sans with the widest language coverage: multilingual documents"),
}
TEXT_SIZES = {"small": 0.93, "regular": 1.0, "large": 1.1}
TONES = {"formal": ("professional", "navy"), "warm": ("editorial", "terracotta"), "urgent": ("professional", "crimson"),
         "technical": ("professional", "ocean"), "celebratory": ("editorial", "forest"), "neutral": ("professional", "graphite")}

STYLE_FILE_SUFFIX = ".style.yml"
PAPER_MM = {"a3": (297, 420), "a4": (210, 297), "a5": (148, 210), "letter": (215.9, 279.4), "legal": (215.9, 355.6)}
MARGIN_WORDS = {"narrow": 14, "normal": 20, "wide": 28}
DEFAULT_MARGINS_MM = (20, 25, 22, 25)
PAGE_FIELDS = ("page", "pages", "section", "title", "date")
STYLE_PROPERTIES = ("font", "size", "color", "weight", "italic", "align", "caps", "tracking")
STYLE_ONLY_PROPERTIES = ("kind", "based-on", "numbering")
PARAGRAPH_PROPERTIES = ("dropcap", "lang")
BORDER_SIDES = ("top", "bottom", "left", "right")
BOX_PROPERTIES = ("border", *(f"border-{side}" for side in BORDER_SIDES), "padding", "bg", "radius", "width")
LAYOUT_ATTRIBUTES = ("ratio", "gap", "side", "caption", "height")
BORDER_WORDS = ("none", "thin", "thick", *BORDER_SIDES)
BORDER_WIDTHS_PT = {"thin": 0.5, "thick": 1.5}
PADDING_MM = {"xs": 1, "s": 2, "m": 4, "l": 6, "xl": 9}
RADIUS_MM = {"s": 1, "m": 2, "l": 4}
COLUMN_RATIOS = ("1:1", "1:2", "2:1", "1:3", "3:1")
COLUMN_GAP_MM = 8
POINT_MM = 0.3528
LENGTH_UNIT = re.compile(r"^(\d+(?:\.\d+)?)\s*(mm|pt)$")
FRACTION = re.compile(r"^(\d+)\s*/\s*(\d+)$")
PERCENT = re.compile(r"^(\d+(?:\.\d+)?)\s*%$")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
IMAGE_SIDES = ("left", "right")
SCALE_WORDS = {"xs": 0.8, "s": 0.9, "m": 1.0, "l": 1.25, "xl": 1.6, "xxl": 2.0}
STYLE_ALIGNS = {"left": "L", "center": "C", "right": "R", "justify": "J"}
STYLE_COLOR_ROLES = {"ink": "ink", "body": "body", "muted": "muted", "accent": "mood", "second": "second", "surface": "surface",
                     "success": "success", "danger": "danger"}
FONT_WORDS = {"heading": "Head", "body": "Brand", "mono": "Mono"}
TRACKING_POINTS = {"tight": -0.2, "normal": 0.0, "wide": 0.6}
SMALL_CAPS_SCALE = 0.8
BODY_POINTS = 10.0
MAX_BASED_ON = 3
NAME_STYLE_AFTER = 3
SIZE_POINTS = re.compile(r"^(\d+(?:\.\d+)?)\s*pt$")
HEX_STYLE_COLOR = re.compile(r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$")
BUNDLED_FONTS = {
    "inter": ("Inter-Regular.ttf", "Inter-Bold.ttf", "Inter-Italic.ttf", "Inter-BoldItalic.ttf"),
    "pt serif": ("PTSerif-Regular.ttf", "PTSerif-Bold.ttf", "PTSerif-Italic.ttf", "PTSerif-Bold.ttf"),
    "ibm plex sans": ("IBMPlexSans-Regular.ttf", "IBMPlexSans-Bold.ttf", "IBMPlexSans-Italic.ttf", "IBMPlexSans-Bold.ttf"),
    "jetbrains mono": ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf", "JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"),
    "noto sans": ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf", "NotoSans-Italic.ttf", "NotoSans-BoldItalic.ttf"),
}
ENGINE_DEFAULTS = {
    "text": {"font": "body", "size": "10pt", "color": "body"},
    "h1": {"font": "heading", "size": "24pt", "weight": "bold"},
    "h2": {"font": "heading", "size": "14.5pt", "weight": "bold"},
    "h3": {"font": "heading", "size": "12pt", "weight": "bold"},
    "h4": {"size": "10.5pt", "weight": "bold"},
}
BUILTIN_CLASSES = ("unnumbered", "left", "center", "right", "justify", "lead", "indent", "lined", "striped", "boxed", "decimal", "alpha", "upper-alpha",
                   "roman", "upper-roman", "legal", "underline", "highlight", "accent", "second", "muted", "danger", "success",
                   "callout", "aside")
STYLE_FILE_KEYS = ("use", "page", "pages", "text", "set", "styles", "colors", "fonts", "fields", "allow", "refs")
STYLE_SELECTORS = ("h1", "h2", "h3", "h4", "paragraph", "list", "table", "quote", "code", "figure", "caption", "footnote", "link", "box")
