import copy
import math
import re
import tempfile
import zlib
from decimal import Decimal
from pathlib import Path

from PIL import Image

from markitdoc.markup.inline import plain_text
from markitdoc.models.attributes import parse_attributes
from markitdoc.options import options_in_use
from markitdoc.themes.theme_constants import IMAGE_SUFFIXES
from markitdoc.visuals.charts import parse_chart_fence
from markitdoc.visuals.photo_fit import interest_box

NUMERIC_CELL = re.compile(r"^([\s$€£¥+−~≈<>-]*)(\d+(?:,\d{3})*(?:\.\d+)?)(\s*(?:%|[kKmMbB]|bn|x|pts?|bps)?\s*)$")
TABLE_COLUMN_ROLES = ("label", "numeric", "rating")
MAX_DECIMAL_PLACES = 6
CALLOUT_KINDS = ("Note", "Action", "Risk", "Key figure")
TABLE_STYLES = ("lined", "striped", "boxed")
IMAGE_WRITTEN = re.compile(r"!\[([^\]]*)\]\(([^)\s]*)\)(?:\{([^{}]*)\})?")
PICTURE_RATIO = re.compile(r"^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$")
CHART_SIZES = {"full": 1.0, "wide": 1.0, "half": 0.75}
TOTALS_ROW = re.compile(r"^\W*(grand total|totals?|sum|gesamt|summe|insgesamt|total général)\b", re.I)
PARAGRAPH_ALIGNMENTS = {"center": "C", "right": "R", "justify": "J"}
SPAN_COLORS = {"accent": "mood", "second": "second", "muted": "muted", "danger": "danger", "success": "success", "highlight": "ink"}
BULLET_MARKERS = ("•", "–", "◦")
SIGNED_NUMBER = re.compile(r"^\s*([+\-−])\s?[$€£]?\d[\d.,]*\s?(%|pts?|bps|[kKmMbB])?\s*$")
RATING_WORDS = {"none": 0, "low": 1, "minimal": 1, "medium": 2, "moderate": 2, "partial": 2, "high": 3, "strong": 3, "very high": 4,
                "full": 4, "complete": 4}
TABLE_MARKS = {**{word: ("✓", "success") for word in ("yes", "✓", "✔", "supported", "included", "true")},
               **{word: ("✕", "danger") for word in ("no", "✕", "✗", "x", "not supported", "none", "false", "not included")}}


# formats a number as a lowercase Roman numeral
def roman(number):
    values = ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))
    result = ""
    for value, letters in values:
        while number >= value:
            result, number = result + letters, number - value
    return result


NUMBERING_SCHEMES = (str, lambda number: chr(96 + (number - 1) % 26 + 1), roman)
LIST_SCHEMES = {"decimal": str, "alpha": NUMBERING_SCHEMES[1], "upper-alpha": lambda number: NUMBERING_SCHEMES[1](number).upper(),
                "roman": roman, "upper-roman": lambda number: roman(number).upper(), "legal": str}


# separates display equations from the surrounding inline content
def without_display_maths(inline):
    children = inline.children or []
    equations = [child.content for child in children if child.type == "math_inline_double"]
    if not equations:
        return inline, []
    kept = [child for child in children if child.type != "math_inline_double"]
    while kept and kept[-1].type in ("softbreak", "hardbreak"):
        kept.pop()
    return replace_children(inline, kept), equations


# copies an inline token with new children and refreshed plain text content
def replace_children(inline, children):
    clone = copy.copy(inline)
    clone.children = children
    clone.content = "".join(child.content for child in children if child.type in ("text", "code_inline"))
    return clone


# checks whether an inline token contains only a display equation
def only_display_maths(inline):
    meaningful = [child for child in inline.children or [] if child.type not in ("softbreak", "hardbreak")
                  and not (child.type == "text" and not child.content.strip())]
    return len(meaningful) == 1 and meaningful[0].type == "math_inline_double"


# reads text alignment settings from markdown table headers
def column_alignments(tokens):
    alignments = []
    for token in tokens:
        if token.type == "th_open":
            style = str(token.attrs.get("style", ""))
            alignments.append("CENTER" if "center" in style else "RIGHT" if "right" in style else "LEFT" if "left" in style else None)
        elif token.type == "thead_close":
            break
    return alignments


# assigns a role to each column, preferring an explicit role over numeric and rating inference
def table_columns(rows, settings):
    declared = [role.strip().lower() for role in str(settings.get("columns", "")).split(",")]
    roles, precisions = [], []
    for index in range(len(rows[0])):
        cells = [plain_text(row[index]).strip() for row in rows[1:] if index < len(row) and row[index].strip()]
        numbers = [NUMERIC_CELL.fullmatch(cell) for cell in cells]
        role = declared[index] if index < len(declared) else ""
        if role not in TABLE_COLUMN_ROLES:
            role = ("numeric" if cells and all(numbers) else
                    "rating" if index and cells and all(rating_level(cell) is not None for cell in cells) else "")
        places = str(settings.get("precision", ""))
        precision = int(places) if places.isascii() and places.isdigit() and len(places) == 1 else None
        if precision is None and cells and all(numbers) and len({(match[1].strip(" +−-"), match[3].strip()) for match in numbers}) == 1:
            precision = max(len(match[2].partition(".")[2]) for match in numbers)
        roles.append(role)
        precisions.append(precision if role == "numeric" and precision is not None and precision <= MAX_DECIMAL_PLACES else None)
    return roles, precisions


# presents comparable numbers at one precision without rewriting non-numeric text or mixed units
def formatted_number(source, precision):
    match = NUMERIC_CELL.fullmatch(plain_text(source).strip()) if precision is not None else None
    if not match:
        return source
    number = match[2]
    decimal = Decimal(number.replace(",", ""))
    fmt = f",.{precision}f" if "," in number else f".{precision}f"
    return source.replace(number, format(decimal, fmt), 1)


# returns the visible text represented by a rating or a yes/no mark
def rating_text(source):
    text = plain_text(source).strip()
    if text in ("✓", "✔"):
        return "Yes"
    if text.lower() in ("✕", "✗", "x"):
        return "No"
    return text


# reads settings attached to a markdown paragraph
def element_settings(tokens, position):
    if position + 1 >= len(tokens) or tokens[position].type != "paragraph_open":
        return {}
    text = tokens[position + 1].content.strip()
    return settings_from(text[1:-1]) if text.startswith("{") and text.endswith("}") else {}


# parses key-value settings and a class name from text
def settings_from(text):
    attributes = parse_attributes(text)
    found = {key: value for key, value in attributes.values.items() if value is not True}
    return {**found, "class": attributes.classes[0]} if attributes.classes else found


# finds the matching closing token for a nested token block
def closing_index(tokens, start, open_type, close_type):
    depth = 0
    for position in range(start, len(tokens)):
        if tokens[position].type == open_type:
            depth += 1
        elif tokens[position].type == close_type:
            depth -= 1
            if depth == 0:
                return position
    return len(tokens) - 1


# groups tokens into top-level markdown blocks
def top_level_blocks(tokens):
    blocks, current = [], []
    top = min((token.level for token in tokens), default=0)
    for token in tokens:
        current.append(token)
        if token.level == top and (token.type.endswith("_close") or token.type in ("fence", "math_block", "hr", "code_block")):
            blocks.append(current)
            current = []
    return blocks + ([current] if current else [])


# parses and validates chart data from a code fence
def chart_data(content):
    data = parse_chart_fence(content.splitlines())
    if data and "values" in data and not data.get("datasets"):
        data["datasets"] = [{"values": data.pop("values")}]
    datasets = data.get("datasets") if data else None
    if (not isinstance(datasets, list) or not datasets or not all(isinstance(dataset, dict) for dataset in datasets)
            or any(not isinstance(values := dataset.get("values"), list) or not values
                   or any(type(value) not in (int, float) or not math.isfinite(value) for value in values) for dataset in datasets)):
        return None
    labels = data.get("labels") or [str(index) for index in range(1, len(datasets[0]["values"]) + 1)]
    if not isinstance(labels, list) or not all(type(label) in (str, int, float) for label in labels):
        return None
    if any(len(dataset["values"]) != len(labels) for dataset in datasets):
        return None
    if "precision" in data and (type(data["precision"]) is not int or not 0 <= data["precision"] <= MAX_DECIMAL_PLACES):
        return None
    if "highlight" in data and data["highlight"] not in labels and data["highlight"] != data.get("total"):
        return None
    data["labels"] = labels
    return data


# converts a rating label or fraction to a level from zero to four
def rating_level(source):
    text = plain_text(source).strip().lower()
    found = re.fullmatch(r"([0-4])\s*/\s*4", text)
    return int(found.group(1)) if found else RATING_WORDS.get(text)


# the match of a markdown image written with a real file path, None for photo-query images such as ![harbour](figure)
def written_image(text):
    found = IMAGE_WRITTEN.search(text)
    return found if found and "://" not in found.group(2) and Path(found.group(2)).suffix.lower() in IMAGE_SUFFIXES else None


# the width-to-height ratio written as 16:9, None when the text is not one
def picture_ratio(text):
    found = PICTURE_RATIO.match(str(text or "").strip())
    return float(found.group(1)) / float(found.group(2)) if found and float(found.group(1)) and float(found.group(2)) else None


# the image cropped to ratio around its most detailed part, saved once in the cache folder; the image itself without a ratio
def cropped_picture(path, ratio):
    path = Path(path)
    if not ratio or not image_size(path):
        return path
    key = f"{path.resolve()}|{path.stat().st_mtime_ns}|{ratio:.4f}".encode()
    target = Path(options_in_use().cache_folder or tempfile.gettempdir()) / "markitdoc-crops" / f"{path.stem}-{zlib.crc32(key):08x}.png"
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as picture:
            picture.crop(interest_box(picture.convert("RGB"), ratio)).save(target)
    return target


# the drawn size of an image of natural (width, height) asked for a width, a height or both, kept in proportion and shrunk to the room
def fitted_size(natural, width, height, room_width, room_height):
    ratio = natural[0] / natural[1]
    drawn = min(width, height * ratio) if width and height else width or (height * ratio if height else natural[0])
    drawn = min(drawn, room_width, room_height * ratio)
    return drawn, drawn / ratio


# the natural size in mm at 96 dpi of an image file, None when it is missing or unreadable
def image_size(path):
    try:
        with Image.open(path) as picture:
            return tuple(pixels * 25.4 / 96 for pixels in picture.size)
    except (OSError, ValueError):
        return None
