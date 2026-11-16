import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from markitdoc.models.attributes import KEY_ALIASES, VALUE_ALIASES
from markitdoc.themes.theme_constants import (
    BODY_POINTS,
    BORDER_SIDES,
    BORDER_WIDTHS_PT,
    BOX_PROPERTIES,
    BUNDLED_FONTS,
    COLUMN_GAP_MM,
    COLUMN_RATIOS,
    DEFAULT_MARGINS_MM,
    ENGINE_DEFAULTS,
    FONT_WORDS,
    FRACTION,
    HEX_STYLE_COLOR,
    LENGTH_UNIT,
    MARGIN_WORDS,
    MAX_BASED_ON,
    PADDING_MM,
    PAPER_MM,
    PERCENT,
    POINT_MM,
    RADIUS_MM,
    SCALE_WORDS,
    SIZE_POINTS,
    STYLE_ALIGNS,
    STYLE_COLOR_ROLES,
    STYLE_FILE_SUFFIX,
    STYLE_PROPERTIES,
    TRACKING_POINTS,
)
from markitdoc.themes.themes import theme_folders
from markitdoc.utils.constants import ASSETS_FOLDER

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Layer:
    label: str
    data: dict
    folder: Path | None = None
    locked: bool = False


@dataclass(frozen=True)
class Face:
    family: str
    files: tuple


@dataclass(frozen=True)
class Master:
    name: str
    width: float
    height: float
    margins: tuple
    header: str | None
    footer: str | None
    numbers: str


@dataclass(frozen=True)
class TextStyle:
    props: dict
    font: str | None = None
    size: float | None = None
    rgb: tuple | None = None
    bold: bool | None = None
    italic: bool | None = None
    align: str | None = None
    caps: str | None = None
    tracking: float | None = None
    borders: dict | None = None
    padding: float | None = None
    fill: tuple | None = None
    radius: float | None = None
    width: str | None = None

    # does the look carry any box property: border, padding, background, radius or width
    def boxed(self):
        return bool(self.borders) or any(item is not None for item in (self.padding, self.fill, self.radius, self.width))


# a rule from yaml as {property: (value, source)}, aliases applied, other keys dropped
def tagged(rule, source):
    found = {}
    for key, value in (rule if isinstance(rule, dict) else {}).items():
        key = KEY_ALIASES.get(str(key).lower(), str(key).lower())
        if key in STYLE_PROPERTIES + BOX_PROPERTIES:
            found[key] = (VALUE_ALIASES.get(value.lower(), value) if isinstance(value, str) else value, source)
    return found


# a yaml section as a dict, empty when it is anything else
def section(layer, name):
    value = layer.data.get(name)
    return value if isinstance(value, dict) else {}


# the file for a style name: document folders, registered brand folders, then the built-in themes
def find_style_file(name, folders):
    for folder in [*map(Path, folders), *theme_folders]:
        for candidate in (folder, folder / "styles", folder / "brands" / name, folder / name):
            if (candidate / f"{name}{STYLE_FILE_SUFFIX}").is_file():
                return candidate / f"{name}{STYLE_FILE_SUFFIX}"
    return None


# the style names a front matter 'use:' asks for, from a list or a comma separated string
def used_names(front):
    value = front.get("use") or []
    names = value.replace(",", " ").split() if isinstance(value, str) else value
    return [str(name).strip() for name in names if str(name).strip()]


# the font a fonts: entry points to: a bundled family or a .ttf next to its style file, None when neither exists
def face_of(value, folder):
    text = str(value).strip()
    if text.lower() in BUNDLED_FONTS:
        return Face(text, tuple(ASSETS_FOLDER / "fonts" / name for name in BUNDLED_FONTS[text.lower()]))
    path = Path(folder) / text if folder and text.lower().endswith(".ttf") else None
    # ponytail: one file serves all four styles, siblings like Name-Bold.ttf are not looked up
    return Face(path.stem.split("-")[0], (path,) * 4) if path and path.is_file() else None


# the style layers of a document: use: files in order, then its own front matter, plus what could not be loaded
def load_layers(front, folders):
    layers, problems = [], []
    for name in used_names(front):
        path = find_style_file(name, folders)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path else None
        except (OSError, yaml.YAMLError):
            data = None
        if not isinstance(data, dict):
            problems.append(name)
            continue
        layers.append(Layer(path.name, data, path.parent, bool(data.get("locked"))))
    layers.append(Layer("front matter", front, Path(folders[0]) if folders else None))
    return layers, problems


# loads and merges the style files and front matter of a document into one stylesheet
def load_stylesheet(front, theme, folders=()):
    layers, missing = load_layers(front or {}, folders)
    return Stylesheet(layers, theme, missing)


class Stylesheet:
    # merges named colours and fonts across layers, locked brands last so they win
    def __init__(self, layers, theme, missing=()):
        self.layers, self.theme, self.missing = tuple(layers), theme, tuple(missing)
        self.locked = [layer for layer in self.layers if layer.locked]
        self.colors, self.faces, self.dropped = {}, {}, []
        for layer in [*self.layers, *self.locked]:
            self.colors.update({str(name): value for name, value in section(layer, "colors").items()})
            self.faces.update({str(name): face_of(value, layer.folder) for name, value in section(layer, "fonts").items()})
        self.raw_allowed = all(str(section(layer, "allow").get("raw")).lower() != "false" for layer in self.layers)
        self.fields = {str(name): str(value) for layer in self.layers for name, value in section(layer, "fields").items()}
        self.pages_defined = any(section(layer, "page") or section(layer, "pages") for layer in self.layers)
        self.style_names = {str(name) for layer in self.layers for name in section(layer, "styles")}
        self.base = self.points(self.cascade_base(None).get("size", (None,))[0], BODY_POINTS) or BODY_POINTS

    # the names of the page masters any layer defines, default first
    def master_names(self):
        return ["default", *dict.fromkeys(str(name) for layer in self.layers for name in section(layer, "pages") if str(name) != "default")]

    # the page master called name: the page section, then the default master, then the named master, each merged over the layers
    def master(self, name="default"):
        found = {}
        for source in (None, "default", name):
            for layer in self.layers:
                rule = section(layer, "page") if source is None else section(layer, "pages").get(source)
                found.update({str(key).lower(): value for key, value in (rule if isinstance(rule, dict) else {}).items()})
        width, height = PAPER_MM.get(str(found.get("paper", "a4")).lower(), PAPER_MM["a4"])
        if str(found.get("orientation", "")).lower() == "landscape":
            width, height = height, width
        header, footer = (None if found.get(key) is None else str(found[key]).strip() for key in ("header", "footer"))
        return Master(name, width, height, self.margins_of(found.get("margins")), header, footer, str(found.get("numbers", "arabic")))

    # the top, right, bottom and left margins in mm of a margins value: a word, or one, two or four lengths
    def margins_of(self, value):
        text = str(value).strip().lower()
        if text in MARGIN_WORDS:
            return (MARGIN_WORDS[text],) * 4
        sizes = [self.length(word if LENGTH_UNIT.match(word) else f"{word}mm") for word in text.split()]
        if None in sizes or len(sizes) not in (1, 2, 4):
            return DEFAULT_MARGINS_MM
        return {1: sizes * 4, 2: sizes * 2, 4: sizes}[len(sizes)]

    # a rule's properties with an unusable font dropped, so the element keeps the font it would have had without that key
    def tag(self, rule, source):
        found = tagged(rule, source)
        value = found.get("font", (None,))[0]
        if value is not None and str(value).lower() not in FONT_WORDS and not self.faces.get(str(value)):
            self.dropped.append((source, str(value)))
            del found["font"]
        return found

    # the text and element rules of every layer for a selector such as h2 or table.header, element rules winning
    def cascade_base(self, selector):
        found = {}
        for layer in self.layers:
            found.update(self.tag(section(layer, "text"), f"{layer.label}:text"))
        found.update(self.tag(ENGINE_DEFAULTS.get((selector or "").split(".")[0]), "engine default"))
        for layer in self.layers:
            for key in dict.fromkeys(selector.split(".")[:1] + [selector] if selector else []):
                found.update(self.tag(section(layer, "set").get(key), f"{layer.label}:set.{key}"))
        return found

    # a named style or the element it is based on, merged over layers, with based-on followed up to three levels
    def named(self, name, depth=0):
        rules = [(layer, section(layer, "styles")[name]) for layer in self.layers if name in section(layer, "styles")]
        if not rules:
            return self.cascade_base(name) if depth else {}
        based = next((rule.get("based-on") for _, rule in reversed(rules) if isinstance(rule, dict) and rule.get("based-on")), None)
        found = self.named(str(based), depth + 1) if based and depth < MAX_BASED_ON else {}
        for layer, rule in rules:
            found.update(self.tag(rule, f"{layer.label}:styles.{name}"))
        return found

    # what locked brands set for the selector and styles, applied last
    def locked_props(self, selector, classes):
        found = {}
        for layer in self.locked:
            found.update(self.tag(section(layer, "text"), f"{layer.label}:text"))
            for key in dict.fromkeys(selector.split(".")[:1] + [selector] if selector else []):
                found.update(self.tag(section(layer, "set").get(key), f"{layer.label}:set.{key}"))
            for name in classes:
                found.update(self.tag(section(layer, "styles").get(name), f"{layer.label}:styles.{name}"))
        return found

    # every property of an element as {property: (value, source)}: text, element rules, named styles, inline keys, locked brands
    def resolve(self, selector=None, classes=(), inline=None, parent=None, where="", context=None):
        self.dropped = []
        found = {key: item for key, item in parent.items() if key not in BOX_PROPERTIES} if parent is not None else self.cascade_base(selector)
        for key, item in (context or {}).items() if parent is None else ():
            if key not in found or found[key][1].endswith(":text"):
                found[key] = item
        for name in classes:
            found.update(self.named(name))
        if inline and not self.raw_allowed:
            logger.warning("Raw style keys ignored because a style file sets allow: {raw: false}: %s", ", ".join(inline))
            inline = None
        found.update(self.tag(inline or {}, f"line {where} attributes" if where else "inline attributes"))
        found.update(self.locked_props(selector or "", classes))
        return found

    # the same as resolve, converted to values a renderer can use
    def look(self, selector=None, classes=(), inline=None, parent=None, where="", context=None):
        return self.style_of(self.resolve(selector, classes, inline, None if parent is None else parent.props, where, context))

    # a span's look from its own class and raw key pairs, inheriting from the paragraph look
    def span_look(self, pairs, parent):
        classes = tuple(name for key, value in pairs if key == "class" for name in value.split())
        raw = {key: value for key, value in pairs if key != "class"}
        return self.look(None, classes, raw, parent)

    # a points value from a scale word or 'Npt', None when it is neither
    def points(self, value, base=None):
        text = str(value).strip().lower()
        if text in SCALE_WORDS:
            return SCALE_WORDS[text] * (base or self.base)
        found = SIZE_POINTS.match(text)
        return float(found.group(1)) if found else None

    # millimetres from a length: a scale word of the given table, mm, pt, or a fraction or percent of full; None when it is none of these
    def length(self, value, full=None, scale=None):
        text = str(value).strip().lower()
        if scale and text in scale:
            return float(scale[text])
        if found := LENGTH_UNIT.match(text):
            return float(found.group(1)) * (1 if found.group(2) == "mm" else POINT_MM)
        if full is not None and (found := FRACTION.match(text)) and int(found.group(2)):
            return full * int(found.group(1)) / int(found.group(2))
        if full is not None and (found := PERCENT.match(text)):
            return full * float(found.group(1)) / 100
        return None

    # the column weights and gap in mm of a columns container's attributes, an even split when the ratio is not a supported one
    def columns(self, values):
        ratio = str(values.get("ratio", "1:1"))
        gap = self.length(values["gap"], scale=PADDING_MM) if "gap" in values else None
        return tuple(int(weight) for weight in (ratio if ratio in COLUMN_RATIOS else "1:1").split(":")), COLUMN_GAP_MM if gap is None else gap

    # an RGB tuple from a colour value, None when it is not a colour
    def rgb_of(self, value):
        digits = self.hex_of(value)
        return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4)) if digits else None

    # the border edges of resolved values as {side: (width in mm, rgb)}; border sets edges first, border-top and the like refine them
    def edges_of(self, value):
        edges = {}
        for key in ("border", *(f"border-{side}" for side in BORDER_SIDES)):
            if key not in value:
                continue
            words = str(value[key]).split()
            sides = [key[7:]] if "-" in key else [word.lower() for word in words if word.lower() in BORDER_SIDES] or BORDER_SIDES
            if any(word.lower() == "none" for word in words):
                edges = {side: edge for side, edge in edges.items() if side not in sides}
                continue
            width, rgb = BORDER_WIDTHS_PT["thin"] * POINT_MM, self.theme.rgb("rule") if self.theme else (0, 0, 0)
            for word in words:
                if word.lower() in BORDER_WIDTHS_PT:
                    width = BORDER_WIDTHS_PT[word.lower()] * POINT_MM
                elif (found := self.length(word)) is not None:
                    width = found
                elif word.lower() not in BORDER_SIDES and (colour := self.rgb_of(word)):
                    rgb = colour
            edges.update({side: (width, rgb) for side in sides})
        return edges

    # a hex string from a colour value: hex, a name under colors:, or a role
    def hex_of(self, value, depth=0):
        text = str(value).strip()
        if text in self.colors and depth < 4:
            return self.hex_of(self.colors[text], depth + 1)
        if HEX_STYLE_COLOR.match(text):
            digits = text[1:]
            return (digits if len(digits) == 6 else "".join(digit * 2 for digit in digits)).upper()
        role = STYLE_COLOR_ROLES.get(text.lower())
        return self.theme.colors[role] if role and self.theme else None

    # converts resolved properties into a TextStyle
    def style_of(self, props):
        value = {key: found[0] for key, found in props.items()}
        digits = self.hex_of(value["color"]) if "color" in value else None
        font = str(value["font"]) if "font" in value else None
        italic = value.get("italic")
        weight = str(value.get("weight", "")).lower()
        return TextStyle(
            props=props,
            font=(font.lower() if font.lower() in FONT_WORDS else font) if font else None,
            size=self.points(value.get("size")),
            rgb=tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4)) if digits else None,
            bold={"bold": True, "normal": False}.get(weight),
            italic=italic if isinstance(italic, bool) else {"true": True, "false": False}.get(str(italic).lower()),
            align=STYLE_ALIGNS.get(str(value.get("align", "")).lower()),
            caps=str(value["caps"]).lower() if str(value.get("caps", "")).lower() in ("small", "all") else None,
            tracking=TRACKING_POINTS.get(str(value.get("tracking", "")).lower()),
            borders=self.edges_of(value),
            padding=self.length(value["padding"], scale=PADDING_MM) if "padding" in value else None,
            fill=self.rgb_of(value["bg"]) if "bg" in value else None,
            radius=self.length(value["radius"], scale=RADIUS_MM) if "radius" in value else None,
            width=str(value["width"]) if "width" in value else None)
