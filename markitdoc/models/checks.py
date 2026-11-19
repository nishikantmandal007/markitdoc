import re
from dataclasses import dataclass
from difflib import get_close_matches

from markitdoc.guide.support import support_findings
from markitdoc.markup.elements import IMAGE_WRITTEN, chart_data, picture_ratio
from markitdoc.markup.latex import latex_findings
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.front_matter import front_matter, front_matter_yaml
from markitdoc.models.model_constants import DIV_CLOSE, DIV_OPEN, KNOWN_KEYS, LEAF_BLOCKS, PAGE_SWITCH
from markitdoc.models.references import reference_findings
from markitdoc.models.style_checks import SPAN_ATTRIBUTES, style_findings
from markitdoc.themes.theme_constants import (
    ACCENTS,
    BOX_PROPERTIES,
    FONT_PAIRS,
    LAYOUT_ATTRIBUTES,
    LEGACY_THEME_NAMES,
    PAPER_MM,
    PAPERS,
    PARAGRAPH_PROPERTIES,
    STYLE_PROPERTIES,
    TONES,
)
from markitdoc.themes.themes import available_themes, read_theme
from markitdoc.visuals.diagrams import problems_in_diagram
from markitdoc.visuals.infographics import problems_in_infographic

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


# the names each front matter setting accepts; anything else silently falls back to a default when rendering
def accepted_names():
    themes = available_themes()
    moods = {mood for name in themes for mood in read_theme(name).moods}
    colours = sorted({*ACCENTS, *moods})
    return {"palette": colours, "accent": colours, "mood": colours, "fonts": sorted(FONT_PAIRS), "paper": sorted({*PAPERS, *PAPER_MM}),
            "template": sorted({*themes, *LEGACY_THEME_NAMES}), "tone": sorted(TONES)}


# an error for each front matter setting whose value the renderer does not know, naming the closest known value
def unknown_names(meta, parsed, lines, end):
    findings = []
    for key, names in accepted_names().items():
        value = parsed.get(key, meta.get(key))
        if not isinstance(value, str) or value.lower() in names:
            continue
        line = next((number for number, text in enumerate(lines[:end], 1) if text.strip().lower().startswith(f"{key}:")), 1)
        close = get_close_matches(value.lower(), names, n=1)
        findings.append(Finding(line, "error", f"unknown {key} '{value}'", f"use one of: {', '.join(names)}" if not close else f"did you mean '{close[0]}'?"))
    return findings


# an error for each chart, infographic or diagram fence the renderer would leave out
def broken_visuals(lines):
    findings, opening, content = [], None, []
    for number, text in enumerate(lines, 1):
        stripped = text.strip()
        if opening is None and stripped.startswith("```"):
            opening, content = (number, stripped[3:].split("{")[0].strip()), []
        elif opening and stripped.startswith("```"):
            start, info = opening
            language, _, suffix = info.partition(" ")
            source = (f"{language} {suffix}\n" if suffix else "") + "\n".join(content) + "\n"
            if language == "chart" and chart_data(source) is None:
                findings.append(Finding(start, "error", "chart data is not usable, so the chart would be left out",
                                        "valid JSON with type, labels and datasets; values are plain numbers, one per label"))
            problems = (problems_in_infographic(source) if language == "infographic"
                        else problems_in_diagram(source) if language == "mermaid" else [])
            findings += [Finding(start, "error", f"{language}: {problem}") for problem in problems]
            opening = None
        elif opening:
            content.append(text)
    return findings


# an error for each image whose ratio is not a shape like 16:9, so its crop would be skipped
def bad_picture_ratios(lines):
    findings = []
    for number, text in enumerate(lines, 1):
        for found in IMAGE_WRITTEN.finditer(text):
            ratio = parse_attributes(found.group(3) or "").values.get("ratio")
            if ratio is not None and picture_ratio(ratio) is None:
                findings.append(Finding(number, "error", f"image ratio '{ratio}' is not a shape", "write it as width:height, e.g. 16:9, 4:3, 1:1 or 3:2"))
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
    findings += unknown_names(meta, front_matter_yaml(markdown) or {}, lines, end) + broken_visuals(lines) + bad_picture_ratios(lines)
    return sorted(findings, key=lambda finding: finding.line)
