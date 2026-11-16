import re

from markitdoc.markup.inline import parser
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.front_matter import front_matter, front_matter_yaml
from markitdoc.themes.stylesheet import load_stylesheet
from markitdoc.themes.theme_constants import ENGINE_DEFAULTS, SCALE_WORDS, STYLE_PROPERTIES
from markitdoc.themes.themes import theme_for

BLOCK_END = re.compile(r"(?<![\]*_`])\{([^{}]*)\}\s*$")
SELECTORS = {"heading_open": None, "paragraph_open": "paragraph", "blockquote_open": "quote"}


# one explained element: its heading line, then each property with its value and where it came from
def explained(title, sheet, selector, found):
    defaults = {key: (value, "engine default") for key, value in {**ENGINE_DEFAULTS["text"], **ENGINE_DEFAULTS.get(selector, {})}.items()}
    rows = {**defaults, **found}
    lines = [title]
    shown = {key: f"{value} = {sheet.points(value):g}pt" if key == "size" and str(value) in SCALE_WORDS else value
             for key, (value, _) in rows.items()}
    lines += [f"  {key:<9}{shown[key]!s:<18}{rows[key][1]}" for key in STYLE_PROPERTIES if key in rows]
    lines += [f"  font     '{value}' dropped (not available), using {rows.get('font', ('the inherited font',))[0]}  [{source}]"
              for source, value in sheet.dropped]
    return lines


# the stylesheet of a document, with style files searched in folders
def sheet_of(markdown, folders):
    return load_stylesheet(front_matter_yaml(markdown) or {}, theme_for(front_matter(markdown)[0], "default"), folders)


# explains the elements on a 1-based line of a language v2 document: block style, then the spans written on that line
def explain_line(markdown, number, folders=()):
    meta, body = front_matter(markdown)
    if str(meta.get("markitdoc", "")) != "2":
        return ["this document is not 'markitdoc: 2', so no style rules apply"]
    sheet = sheet_of(markdown, folders)
    target = number - 1 - (len(markdown.lstrip("\n").split("\n")) - len(body.split("\n")))
    written = markdown.split("\n")[number - 1]
    tokens, stack, out = parser.parse(body), [], []
    for position, token in enumerate(tokens):
        if token.type in ("list_item_open", "blockquote_open"):
            stack.append(token.type)
        elif token.type in ("list_item_close", "blockquote_close"):
            stack.pop()
        if token.type not in ("heading_open", "paragraph_open") or not token.map or not token.map[0] <= target < token.map[1]:
            continue
        inline = tokens[position + 1]
        selector = token.tag if token.type == "heading_open" else "list" if "list_item_open" in stack else "quote" if stack else "paragraph"
        block = BLOCK_END.search(inline.content)
        attributes = parse_attributes(block.group(1) if block else "")
        found = sheet.resolve(selector, attributes.classes, attributes.values, where=str(number))
        title = f"line {number}: {selector}" + (f" {' '.join('.' + name for name in attributes.classes)}" if attributes.classes else "")
        out += explained(title, sheet, selector, found)
        base = sheet.look(selector, attributes.classes, attributes.values)
        for child in inline.children or []:
            if child.type == "span_open" and child.attrs:
                pairs = tuple((key, str(value)) for key, value in child.attrs.items())
                classes = tuple(name for key, value in pairs if key == "class" for name in value.split())
                raw = {key: value for key, value in pairs if key != "class"}
                if "{" in written and any(name in written for name in classes + tuple(raw)):
                    found = sheet.resolve(None, classes, raw, base.props, str(number))
                    out += explained(f"  span {' '.join('.' + name for name in classes)} {' '.join(f'{k}={v}' for k, v in raw.items())}".rstrip(),
                                     sheet, "", found)
    return out or [f"line {number}: no heading, paragraph, list item or quote starts or continues on this line"]
