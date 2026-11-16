import re
from collections import defaultdict
from difflib import get_close_matches

from markitdoc.models.attributes import KEY_ALIASES, parse_attributes
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.models.front_matter import front_matter, front_matter_yaml
from markitdoc.models.model_constants import FLOW_CONTAINERS, PLANNED_KEYS
from markitdoc.themes.stylesheet import load_stylesheet, section
from markitdoc.themes.theme_constants import (
    BUILTIN_CLASSES,
    FONT_WORDS,
    MINIMUM_CONTRAST,
    NAME_STYLE_AFTER,
    PLANNED_SECTIONS,
    PLANNED_STYLE_PROPERTIES,
    STYLE_COLOR_ROLES,
    STYLE_ONLY_PROPERTIES,
    STYLE_PROPERTIES,
)
from markitdoc.themes.themes import contrast, theme_for

SPAN_ATTRIBUTES = re.compile(r"[\]*`]\{([^{}]*)\}")
SUPPORTED = STYLE_PROPERTIES + STYLE_ONLY_PROPERTIES


# a finding as (line, severity, message, fix)
def warning(line, message, fix=""):
    return (line, "warning", message, fix)


# the first line number matching a pattern, 1 when none does
def line_of(lines, pattern):
    return next((number for number, text in enumerate(lines, 1) if re.match(pattern, text, re.IGNORECASE)), 1)


# a warning for a property a style file or front matter section cannot use yet, None for supported ones
def property_finding(key, where):
    key = KEY_ALIASES.get(str(key).lower(), str(key).lower())
    if key in SUPPORTED:
        return None
    if key in PLANNED_KEYS or key in PLANNED_STYLE_PROPERTIES:
        return warning(1, f"{where}: '{key}' is planned for MarkitDoc language v2 and is ignored for now", "remove it or keep it for a later version")
    close = get_close_matches(key, SUPPORTED + PLANNED_KEYS + PLANNED_STYLE_PROPERTIES, n=1)
    return warning(1, f"{where}: unknown property '{key}'", f"did you mean '{close[0]}'?" if close else "")


# the rules of every text, set and styles section of a layer as (where, rule)
def layer_rules(layer):
    yield "text", section(layer, "text")
    for name, rule in section(layer, "set").items():
        yield f"set.{name}", rule if isinstance(rule, dict) else {}
    for name, rule in section(layer, "styles").items():
        yield f"styles.{name}", rule if isinstance(rule, dict) else {}


# problems with a colour value: hex or a name under colors: that reads badly on the page paper
def contrast_finding(sheet, value, paper, line, where):
    text = str(value).strip()
    if text.lower() in STYLE_COLOR_ROLES and text not in sheet.colors:
        return None
    digits = sheet.hex_of(text)
    if digits and contrast(digits, paper) < MINIMUM_CONTRAST:
        return warning(line, f"{where}: color {text} has contrast {contrast(digits, paper):.1f}:1 against the page, below {MINIMUM_CONTRAST}",
                       "pick a darker colour or one of the roles")
    return None


# problems in the style layers: planned sections and properties, fonts, contrast
def layer_findings(sheet, paper, use_line):
    found = []
    for name in sheet.missing:
        found.append(warning(use_line, f"style file '{name}' not found", "check the name in 'use:' and where the .style.yml file is saved"))
    for name, face in sheet.faces.items():
        value = next((str(section(layer, 'fonts')[name]) for layer in reversed(sheet.layers) if name in section(layer, 'fonts')), name)
        if face is None:
            found.append(warning(use_line, f"font '{name}' ({value}) is not available; using the inherited font",
                                 "use Inter, PT Serif, IBM Plex Sans, JetBrains Mono, Noto Sans or a .ttf path"))
    for layer in sheet.layers:
        found += [warning(1, f"{layer.label}: '{key}' is planned for MarkitDoc language v2 and is ignored for now",
                          "remove it or keep it for a later version")
                  for key in layer.data if key in PLANNED_SECTIONS]
        for where, rule in layer_rules(layer):
            for key, value in rule.items():
                found.append(property_finding(key, f"{layer.label} {where}"))
                if KEY_ALIASES.get(str(key).lower(), str(key).lower()) == "font" and str(value) not in sheet.faces and str(value) not in FONT_WORDS:
                    found.append(warning(1, f"{layer.label} {where}: font '{value}' is not declared under fonts:", "declare it or use heading, body or mono"))
                if KEY_ALIASES.get(str(key).lower(), str(key).lower()) == "color":
                    found.append(contrast_finding(sheet, value, paper, 1, f"{layer.label} {where}"))
    return [item for item in found if item]


# problems in the attributes written in the document: unknown styles and fonts, contrast, and raw combinations worth naming
def attribute_findings(sheet, paper, lines, end):
    found, combinations, in_fence = [], defaultdict(list), False
    for number, text in enumerate(lines, 1):
        stripped = text.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        if number <= end or in_fence or stripped.startswith(("```", "~~~")):
            continue
        for item in [*([stripped] if stripped.startswith("{") and stripped.endswith("}") else []), *SPAN_ATTRIBUTES.findall(text)]:
            attributes = parse_attributes(item)
            for name in attributes.classes:
                if name not in sheet.style_names and name not in BUILTIN_CLASSES and name not in LAYOUTS and name not in FLOW_CONTAINERS:
                    close = get_close_matches(name, sheet.style_names, n=1)
                    found.append(warning(number, f"unknown style '.{name}'", f"did you mean '.{close[0]}'?" if close else "define it under styles:"))
            font = attributes.values.get("font")
            if font and str(font) not in sheet.faces and str(font) not in FONT_WORDS:
                found.append(warning(number, f"font '{font}' is not declared under fonts:", "declare it or use heading, body or mono"))
            if attributes.values.get("color"):
                found.append(contrast_finding(sheet, attributes.values["color"], paper, number, "color"))
            raw = tuple(sorted((key, str(value)) for key, value in attributes.values.items() if key in STYLE_PROPERTIES))
            if raw:
                combinations[raw].append(number)
    for raw, numbers in combinations.items():
        if len(numbers) >= NAME_STYLE_AFTER:
            keys = " ".join(f"{key}={value}" for key, value in raw)
            found.append(warning(numbers[0], f"'{keys}' is written out {len(numbers)} times, name this style",
                                 f"styles: {{name: {{{', '.join(f'{key}: {value}' for key, value in raw)}}}}} and write {{.name}}"))
    return [item for item in found if item]


# language v2 problems in a document: style files, fonts, style names, raw combinations, contrast
def style_findings(markdown, folders=()):
    lines = markdown.split("\n")
    front = front_matter_yaml(markdown)
    sheet = load_stylesheet(front or {}, theme_for(front_matter(markdown)[0], "default"), folders)
    end = next((number for number, text in enumerate(lines[1:], 2) if text.strip() == "---"), 0) if lines[:1] == ["---"] else 0
    paper = sheet.theme.colors["paper"]
    found = layer_findings(sheet, paper, line_of(lines, r"^use\s*:"))
    if front is None:
        found.append(warning(1, "front matter is not valid YAML, so style sections are ignored", "check the indentation and quotes"))
    return found + attribute_findings(sheet, paper, lines, end)
