import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from markitdoc.models.attributes import KEY_ALIASES, VALUE_ALIASES
from markitdoc.themes.theme_constants import (
    BODY_POINTS,
    BUNDLED_FONTS,
    ENGINE_DEFAULTS,
    FONT_WORDS,
    HEX_STYLE_COLOR,
    MAX_BASED_ON,
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


# a rule from yaml as {property: (value, source)}, aliases applied, other keys dropped
def tagged(rule, source):
    found = {}
    for key, value in (rule if isinstance(rule, dict) else {}).items():
        key = KEY_ALIASES.get(str(key).lower(), str(key).lower())
        if key in STYLE_PROPERTIES:
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
        self.style_names = {str(name) for layer in self.layers for name in section(layer, "styles")}
        self.base = self.points(self.cascade_base(None).get("size", (None,))[0], BODY_POINTS) or BODY_POINTS

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
    def resolve(self, selector=None, classes=(), inline=None, parent=None, where=""):
        self.dropped = []
        found = dict(parent) if parent is not None else self.cascade_base(selector)
        for name in classes:
            found.update(self.named(name))
        found.update(self.tag(inline or {}, f"line {where} attributes" if where else "inline attributes"))
        found.update(self.locked_props(selector or "", classes))
        return found

    # the same as resolve, converted to values a renderer can use
    def look(self, selector=None, classes=(), inline=None, parent=None, where=""):
        return self.style_of(self.resolve(selector, classes, inline, None if parent is None else parent.props, where))

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
            tracking=TRACKING_POINTS.get(str(value.get("tracking", "")).lower()))
