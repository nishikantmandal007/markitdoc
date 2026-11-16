import re
from dataclasses import dataclass
from difflib import get_close_matches

from markitdoc.models.attributes import parse_attributes
from markitdoc.models.front_matter import front_matter, language_version
from markitdoc.models.model_constants import DIV_CLOSE, DIV_OPEN, KNOWN_KEYS, PAGE_SWITCH, PLANNED_KEYS
from markitdoc.models.style_checks import SPAN_ATTRIBUTES, style_findings
from markitdoc.themes.theme_constants import BOX_PROPERTIES, LAYOUT_ATTRIBUTES, STYLE_PROPERTIES

VERSION_LINE = re.compile(r"^markitdoc\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    line: int
    severity: str
    message: str
    fix: str = ""


# warns about each attribute key no renderer reads: planned keys are named as such, others get the closest key
def unknown_keys(text, line, v2=False):
    findings, taken = [], STYLE_PROPERTIES + BOX_PROPERTIES + LAYOUT_ATTRIBUTES + ("italic", "page", "numbers") if v2 else ()
    planned, known = tuple(key for key in PLANNED_KEYS if key not in taken), KNOWN_KEYS + taken
    for key in parse_attributes(text).values:
        if key in planned:
            findings.append(Finding(line, "warning", f"'{key}' is planned for MarkitDoc language v2 and is ignored for now",
                                    "remove it or keep it for a later version"))
        elif key not in known:
            close = get_close_matches(key, known + planned, n=1)
            findings.append(Finding(line, "warning", f"unknown attribute '{key}'", f"did you mean '{close[0]}'?" if close else ""))
    return findings


# problems in a markdown document, never raising: unknown keys, unbalanced ::: fences, bad language version, and for
# language v2 documents the style problems, with style files searched in folders
def check_document(markdown, folders=()) -> list[Finding]:
    markdown = str(markdown or "")
    lines = markdown.split("\n")
    findings, open_blocks, in_fence = [], [], False
    meta = front_matter(markdown)[0]
    v2 = language_version(meta) == 2
    value = meta.get("markitdoc")
    if value is not None and value not in ("1", "2"):
        line = next((number for number, text in enumerate(lines, 1) if VERSION_LINE.match(text)), 1)
        findings.append(Finding(line, "warning", f"markitdoc version '{value}' is not 1 or 2", "use 'markitdoc: 2' or remove the line"))
    for number, text in enumerate(lines, 1):
        stripped = text.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        elif in_fence:
            continue
        elif DIV_CLOSE.match(stripped):
            if open_blocks:
                open_blocks.pop()
            else:
                findings.append(Finding(number, "error", "closing ::: without an open block", "remove this line"))
        elif opening := DIV_OPEN.match(stripped):
            open_blocks.append(number)
            findings += unknown_keys(opening.group(2), number, v2)
        elif v2 and (switch := PAGE_SWITCH.match(stripped)):
            findings += unknown_keys(switch.group(1), number, v2)
        elif stripped.startswith("{") and stripped.endswith("}"):
            findings += unknown_keys(stripped, number, v2)
        elif v2:
            for item in SPAN_ATTRIBUTES.findall(text):
                findings += unknown_keys(item, number, v2)
    findings += [Finding(number, "error", "::: block is never closed", "add a closing ::: line") for number in open_blocks]
    if v2:
        findings += [Finding(*item) for item in style_findings(markdown, folders)]
    return sorted(findings, key=lambda finding: finding.line)
