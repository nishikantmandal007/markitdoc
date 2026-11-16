import re
from dataclasses import dataclass
from difflib import get_close_matches

from markitdoc.models.attributes import parse_attributes
from markitdoc.models.front_matter import front_matter
from markitdoc.models.model_constants import DIV_CLOSE, DIV_OPEN, KNOWN_KEYS, PLANNED_KEYS

VERSION_LINE = re.compile(r"^markitdoc\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    line: int
    severity: str
    message: str
    fix: str = ""


# warns about each attribute key no renderer reads: planned keys are named as such, others get the closest key
def unknown_keys(text, line):
    findings = []
    for key in parse_attributes(text).values:
        if key in PLANNED_KEYS:
            findings.append(Finding(line, "warning", f"'{key}' is planned for MarkitDoc language v2 and is ignored for now",
                                    "remove it or keep it for a later version"))
        elif key not in KNOWN_KEYS:
            close = get_close_matches(key, KNOWN_KEYS + PLANNED_KEYS, n=1)
            findings.append(Finding(line, "warning", f"unknown attribute '{key}'", f"did you mean '{close[0]}'?" if close else ""))
    return findings


# problems in a markdown document, never raising: unknown keys, unbalanced ::: fences, bad language version
def check_document(markdown) -> list[Finding]:
    markdown = str(markdown or "")
    lines = markdown.split("\n")
    findings, open_blocks, in_fence = [], [], False
    value = front_matter(markdown)[0].get("markitdoc")
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
            findings += unknown_keys(opening.group(2), number)
        elif stripped.startswith("{") and stripped.endswith("}"):
            findings += unknown_keys(stripped, number)
    findings += [Finding(number, "error", "::: block is never closed", "add a closing ::: line") for number in open_blocks]
    return sorted(findings, key=lambda finding: finding.line)
