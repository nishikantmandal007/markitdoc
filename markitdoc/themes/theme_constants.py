import re

from markitdoc.utils.constants import ASSETS_FOLDER

THEMES_FOLDER = ASSETS_FOLDER / "themes"
DEFAULT_THEME = "professional"
LEGACY_THEME_NAMES = {"default": DEFAULT_THEME}
COMPANY_THEME = "company"
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
