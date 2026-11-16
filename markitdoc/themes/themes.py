import logging
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import yaml

from markitdoc.errors import ThemeError
from markitdoc.themes.theme_constants import (ACCENTS, COLOR_ROLES, COVER_STYLES, DEFAULT_PALETTE, DEFAULT_THEME,
                                              FONT_PAIRS, FONT_ROLES, HEX_COLOR, LEGACY_THEME_NAMES, MINIMUM_CONTRAST,
                                              NIGHT_BASE, PALETTES, PAPERS, THEMES_FOLDER, TONES)
from markitdoc.utils.constants import ASSETS_FOLDER

logger = logging.getLogger(__name__)

theme_folders = [THEMES_FOLDER]


# relative brightness of a hex colour, as WCAG defines it
def luminance(hex_value):
    channels = [int(hex_value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    red, green, blue = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


# WCAG contrast ratio between two hex colours
def contrast(first, second):
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# blend share of other into color
def mixed(color, other, share):
    return "".join(f"{int(int(color[index:index + 2], 16) * (1 - share) + int(other[index:index + 2], 16) * share):02X}"
                   for index in (0, 2, 4))


# darken color step by step until it reads on background
def readable_on(color, background):
    for _ in range(12):
        if contrast(color, background) >= MINIMUM_CONTRAST:
            break
        color = "".join(f"{int(int(color[index:index + 2], 16) * 0.88):02X}" for index in (0, 2, 4))
    return color


@dataclass(frozen=True)
class Theme:
    name: str
    brand: str
    tagline: str
    logo: Path | None
    cover: str
    fonts: dict
    colors: dict
    moods: dict
    header_note: str = ""
    footer_text: str = ""
    address: tuple = ()
    partners: tuple = ()
    master: Path | None = None
    content_layout: str = ""
    sample_texts: tuple = ()
    locked: bool = False

    # one colour role as an (r, g, b) tuple
    def rgb(self, role):
        value = self.colors[role]
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    # the same theme with its mood, second and night colours set from a mood or palette name
    def with_mood(self, mood):
        chosen = ACCENTS.get(mood or "") or self.moods.get(mood or "") or self.colors["primary"]
        second = PALETTES[mood][1] if mood in PALETTES else self.colors["accent"]
        if self.locked:
            chosen, second = self.colors["primary"], self.colors["accent"]
        night = self.colors["night"] if self.locked else mixed(chosen, NIGHT_BASE, 0.72)
        return replace(self, colors={**self.colors, "mood": readable_on(chosen, self.colors["paper"]),
                                     "second": readable_on(second, self.colors["paper"]), "night": night,
                                     "glow": self.colors["primary"] if self.locked else chosen})


# names of the shipped and registered theme files
def available_themes():
    return sorted({path.stem for folder in theme_folders for path in folder.glob("*.yml")})


# the theme file for name, a registered brand folder winning over the shipped themes
def theme_file(name):
    return next(folder / f"{name}.yml" for folder in theme_folders if (folder / f"{name}.yml").is_file())


# a file named in a theme: next to the theme file, else in the bundled assets
def theme_asset(folder, relative):
    return folder / relative if (folder / relative).is_file() else ASSETS_FOLDER / relative


# the first of the names that is a locked brand theme
def locked_theme(*names):
    available = available_themes()
    return next((name for name in names if name in available and read_theme(name).locked), None)


# theme, palette and font pair chosen by a document's front matter
def theme_for(meta, template):
    tone_theme, tone_palette = TONES.get(str(meta.get("tone", "")).lower(), (None, None))
    name = (locked_theme((template or "").lower(), meta.get("template")) or PAPERS.get(str(meta.get("paper", "")).lower())
            or tone_theme or meta.get("template") or template)
    palette = meta.get("palette") or meta.get("accent") or tone_palette or meta.get("mood") or DEFAULT_PALETTE
    theme = load_theme(name, palette)
    pair = FONT_PAIRS.get(str(meta.get("fonts", "")).lower())
    if pair and not theme.locked:
        heading, body, bold, italic, _ = (ASSETS_FOLDER / "fonts" / file if index < 4 else file for index, file in enumerate(pair))
        theme = replace(theme, fonts={"heading": heading, "body": body, "bold": bold, "italic": italic})
    logger.info("Document style: theme %s, palette %s, accent %s, fonts %s", theme.name, palette, theme.colors["mood"],
                meta.get("fonts", "theme default"))
    return theme


# a theme by name with a mood applied, falling back to the default theme
def load_theme(name, mood=None):
    wanted = LEGACY_THEME_NAMES.get(name or DEFAULT_THEME, name or DEFAULT_THEME)
    if wanted not in available_themes():
        logger.warning("Unknown document theme %s, using %s", wanted, DEFAULT_THEME)
        wanted = DEFAULT_THEME
    return read_theme(wanted).with_mood(mood)


# read and check one theme file
@lru_cache(maxsize=None)
def read_theme(name):
    path = theme_file(name)
    folder = path.parent
    data = yaml.safe_load(path.read_text())
    colors = {role: str(data["colors"][role]) for role in COLOR_ROLES}
    moods = {mood: str(value) for mood, value in (data.get("moods") or {}).items()}
    bad_colors = [f"{role}={value}" for role, value in {**colors, **moods}.items() if not HEX_COLOR.match(value)]
    if bad_colors:
        raise ThemeError(f"Theme {name} has invalid colours: {bad_colors}")
    fonts = {role: theme_asset(folder, data["fonts"][role]) for role in FONT_ROLES}
    missing = [str(path) for path in fonts.values() if not path.is_file()]
    logo = theme_asset(folder, data["logo"]) if data.get("logo") else None
    if logo and not logo.is_file():
        missing.append(str(logo))
    partners = tuple((theme_asset(folder, entry["file"]), float(entry["height"])) for entry in data.get("partners") or [])
    missing += [str(path) for path, _ in partners if not path.is_file()]
    master = theme_asset(folder, data["master"]) if data.get("master") else None
    if master and not master.is_file():
        missing.append(str(master))
    if missing:
        raise ThemeError(f"Theme {name} points to missing files: {missing}")
    if data.get("cover") not in COVER_STYLES:
        raise ThemeError(f"Theme {name} has unknown cover style {data.get('cover')}")
    return Theme(name=name, brand=data.get("brand") or "", tagline=data.get("tagline") or "", logo=logo,
                 cover=data["cover"], fonts=fonts,
                 colors={**colors, "mood": colors["primary"], "second": colors["accent"], "glow": colors["primary"]}, moods=moods,
                 header_note=data.get("header_note") or "", footer_text=data.get("footer_text") or "",
                 address=tuple(data.get("address") or ()), partners=partners, master=master,
                 content_layout=data.get("content_layout") or "", sample_texts=tuple(data.get("master_sample_text") or ()),
                 locked=bool(data.get("locked")))
