import copy
import math
import re

from markitdoc.markup.inline import plain_text
from markitdoc.visuals.charts import parse_chart_fence

numeric_cell = re.compile(r"^[-+]?[\d.,]+\s*%?$|^[-+]?[$€£]\s?[\d.,]+[kKmMbB]?$")
callout_kinds = ("Note", "Action", "Risk", "Key figure")
table_styles = ("lined", "striped", "boxed")
chart_sizes = {"full": 1.0, "wide": 1.0, "half": 0.75}
totals_row = re.compile(r"^\W*(grand total|totals?|sum|gesamt|summe|insgesamt|total général)\b", re.I)
paragraph_alignments = {"center": "C", "right": "R", "justify": "J"}
span_colors = {"accent": "mood", "second": "second", "muted": "muted", "danger": "danger", "success": "success", "highlight": "ink"}
bullet_markers = ("•", "–", "◦")
signed_number = re.compile(r"^\s*([+\-−])\s?[$€£]?\d[\d.,]*\s?(%|pts?|bps|[kKmMbB])?\s*$")
rating_words = {"none": 0, "low": 1, "minimal": 1, "medium": 2, "moderate": 2, "partial": 2, "high": 3, "strong": 3, "very high": 4,
                "full": 4, "complete": 4}
table_marks = {**{word: ("✓", "success") for word in ("yes", "✓", "✔", "supported", "included", "true")},
               **{word: ("✕", "danger") for word in ("no", "✕", "✗", "x", "not supported", "none", "false", "not included")}}


def roman(number):
    values = ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))
    result = ""
    for value, letters in values:
        while number >= value:
            result, number = result + letters, number - value
    return result


numbering_schemes = (str, lambda number: chr(96 + (number - 1) % 26 + 1), roman)
list_schemes = {"decimal": str, "alpha": numbering_schemes[1], "upper-alpha": lambda number: numbering_schemes[1](number).upper(),
                "roman": roman, "upper-roman": lambda number: roman(number).upper(), "legal": str}


def without_display_maths(inline):
    children = inline.children or []
    equations = [child.content for child in children if child.type == "math_inline_double"]
    if not equations:
        return inline, []
    kept = [child for child in children if child.type != "math_inline_double"]
    while kept and kept[-1].type in ("softbreak", "hardbreak"):
        kept.pop()
    return replace_children(inline, kept), equations


def replace_children(inline, children):
    clone = copy.copy(inline)
    clone.children = children
    clone.content = "".join(child.content for child in children if child.type in ("text", "code_inline"))
    return clone


def only_display_maths(inline):
    meaningful = [child for child in inline.children or [] if child.type not in ("softbreak", "hardbreak")
                  and not (child.type == "text" and not child.content.strip())]
    return len(meaningful) == 1 and meaningful[0].type == "math_inline_double"


def column_alignments(tokens):
    alignments = []
    for token in tokens:
        if token.type == "th_open":
            style = str(token.attrs.get("style", ""))
            alignments.append("CENTER" if "center" in style else "RIGHT" if "right" in style else "LEFT" if "left" in style else None)
        elif token.type == "thead_close":
            break
    return alignments


def element_settings(tokens, position):
    if position + 1 >= len(tokens) or tokens[position].type != "paragraph_open":
        return {}
    text = tokens[position + 1].content.strip()
    return settings_from(text[1:-1]) if text.startswith("{") and text.endswith("}") else {}


def settings_from(text):
    found = dict(re.findall(r"([a-z_]+)=([\w-]+)", text))
    classes = re.findall(r"\.([\w-]+)", text)
    return {**found, "class": classes[0]} if classes else found


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


def chart_data(content):
    data = parse_chart_fence(content.splitlines())
    if data and "values" in data and not data.get("datasets"):
        data["datasets"] = [{"values": data.pop("values")}]
    datasets = data.get("datasets") if data else None
    if (not isinstance(datasets, list) or not datasets or not all(isinstance(dataset, dict) for dataset in datasets)
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for dataset in datasets
                       for value in (dataset.get("values") or [None]))):
        return None
    labels = data.get("labels") or []
    if labels and any(len(dataset.get("values") or []) != len(labels) for dataset in data["datasets"]):
        return None
    return data


def rating_level(source):
    text = plain_text(source).strip().lower()
    found = re.fullmatch(r"([0-4])\s*/\s*4", text)
    return int(found.group(1)) if found else rating_words.get(text)
