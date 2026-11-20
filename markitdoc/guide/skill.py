from pathlib import Path

from markitdoc.guide.contract import GUIDE_PARTS, charts_text, layouts_text, styles_text
from markitdoc.guide.language import core_card

SKILL_FOLDER = "references"


# the SKILL.md text: front matter, the core card, the writing workflow and pointers to the reference files
def skill_text():
    return f"""---
name: markitdoc
description: Write markdown that MarkitDoc renders as a designed PDF, Word or PowerPoint file. Use it when asked for a report, deck, letter or document in one of those formats.
---

# MarkitDoc

Write plain markdown first: headings, paragraphs, lists, tables, charts. Add the language below only where the design needs it.

## Workflow

1. Write the markdown, with front matter where the design needs it.
2. Run `markitdoc check file.md --json --format pdf` (or docx, pptx) and read every finding.
3. Fix each error and warning, using the 'fix' hint of the finding, and check again until it is clean.
4. Render with `markitdoc render file.md -o file.pdf` (the suffix picks the format).

`markitdoc explain file.md:41` shows where a style value on that line came from.

## The language

{core_card("pdf")}

## References

{chr(10).join(f"- `{SKILL_FOLDER}/{name}.md`: {offer}." for name, offer in GUIDE_PARTS.items())}
"""


# writes SKILL.md and its reference files into the folder, returning the paths written
def write_skill(folder):
    folder = Path(folder)
    files = {"SKILL.md": skill_text(), f"{SKILL_FOLDER}/layouts.md": layouts_text(), f"{SKILL_FOLDER}/styles.md": styles_text(),
             f"{SKILL_FOLDER}/charts.md": charts_text()}
    written = []
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
