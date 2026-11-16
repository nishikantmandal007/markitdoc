import re
from dataclasses import dataclass
from difflib import get_close_matches

from markitdoc.guide.support import support_findings
from markitdoc.markup.latex import latex_findings
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.front_matter import front_matter
from markitdoc.models.model_constants import DIV_CLOSE, DIV_OPEN, KNOWN_KEYS, LEAF_BLOCKS, PAGE_SWITCH
from markitdoc.models.references import reference_findings
from markitdoc.models.style_checks import SPAN_ATTRIBUTES, style_findings
from markitdoc.themes.theme_constants import BOX_PROPERTIES, LAYOUT_ATTRIBUTES, PARAGRAPH_PROPERTIES, STYLE_PROPERTIES

FRONT_KEY_LINE = re.compile(r"^markitdoc\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    line: int
    severity: str
    message: str
    fix: str = ""


# warns about each attribute key no renderer reads, naming the closest key
def unknown_keys(text, line):
    findings = []
    known = KNOWN_KEYS + STYLE_PROPERTIES + BOX_PROPERTIES + LAYOUT_ATTRIBUTES + PARAGRAPH_PROPERTIES + ("italic", "page", "numbers")
    for key in parse_attributes(text).values:
        if key not in known:
            close = get_close_matches(key, known, n=1)
            findings.append(Finding(line, "warning", f"unknown attribute '{key}'", f"did you mean '{close[0]}'?" if close else ""))
    return findings


# problems in a markdown document, never raising: unknown keys, unbalanced ::: fences, the style problems, with style files
# searched in folders, and a note for each feature the output format approximates or ignores
def check_document(markdown, folders=(), output_format="pdf") -> list[Finding]:
    markdown = str(markdown or "")
    lines = markdown.split("\n")
    findings, open_blocks, in_fence, leaf = [], [], False, False
    meta = front_matter(markdown)[0]
    if "markitdoc" in meta:
        line = next((number for number, text in enumerate(lines, 1) if FRONT_KEY_LINE.match(text)), 1)
        findings.append(Finding(line, "info", "'markitdoc:' is not needed: every feature is always on", "remove the line"))
    for number, text in enumerate(lines, 1):
        stripped, was_leaf, leaf = text.strip(), leaf, False
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        elif in_fence:
            continue
        elif was_leaf and DIV_CLOSE.match(stripped):
            continue
        elif DIV_CLOSE.match(stripped):
            if open_blocks:
                open_blocks.pop()
            else:
                findings.append(Finding(number, "error", "closing ::: without an open block", "remove this line"))
        elif (opening := DIV_OPEN.match(stripped)) and opening.group(1).lower() in LEAF_BLOCKS:
            leaf = True
        elif opening := DIV_OPEN.match(stripped):
            open_blocks.append(number)
            findings += unknown_keys(opening.group(2), number)
        elif switch := PAGE_SWITCH.match(stripped):
            findings += unknown_keys(switch.group(1), number)
        elif stripped.startswith("{") and stripped.endswith("}"):
            findings += unknown_keys(stripped, number)
        else:
            for item in SPAN_ATTRIBUTES.findall(text):
                findings += unknown_keys(item, number)
    findings += [Finding(number, "error", "::: block is never closed", "add a closing ::: line") for number in open_blocks]
    findings += [Finding(*item) for item in style_findings(markdown, folders)]
    end = next((number for number, text in enumerate(lines[1:], 2) if text.strip() == "---"), 0) if lines[:1] == ["---"] else 0
    findings += [Finding(*item) for item in reference_findings(lines, end, meta, folders)] + [Finding(*item) for item in latex_findings(lines, end)]
    findings += [Finding(*item) for item in support_findings(markdown, output_format)]
    return sorted(findings, key=lambda finding: finding.line)
