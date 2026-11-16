from pathlib import Path

from markitdoc.guide.contract import LAYOUT_PURPOSES, layout_rule
from markitdoc.guide.language import core_card
from markitdoc.guide.support import support_table
from markitdoc.markup.elements import CALLOUT_KINDS, CHART_SIZES, LIST_SCHEMES, TABLE_STYLES
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.themes.theme_constants import FONT_PAIRS, PALETTES, PAPERS, STYLE_SELECTORS, TEXT_SIZES
from markitdoc.visuals.diagrams import DIAGRAM_TYPES
from markitdoc.visuals.infographics import INFOGRAPHIC_TEMPLATES

SKILL_FOLDER = "references"
CHART_TYPES = ("bar", "horizontal_bar", "stacked_bar", "line", "pie", "donut", "waterfall")
STYLE_EXAMPLE = """page: {paper: a4, margins: wide}
pages:
  default: {header: "{section} | | {client}", footer: " | {page} of {pages} | "}
  wide:    {orientation: landscape}
fonts: {display: "Playfair Display", serif: "PT Serif"}
text:  {font: serif, size: 10.5pt, align: justify}
set:
  h2: {font: display, color: accent, numbering: "1"}
  paragraph.first: {dropcap: 2}
styles:
  pull: {kind: block, based-on: quote, size: l, align: center, border: top}"""


# the SKILL.md text: front matter, the core card, the writing workflow and pointers to the reference files
def skill_text():
    return f"""---
name: markitdoc
description: Write markdown that MarkitDoc renders as a designed PDF, Word or PowerPoint file. Use it when asked for a report, deck, letter or document in one of those formats.
---

# MarkitDoc

Write plain markdown first: headings, paragraphs, lists, tables, charts. Add the language below only where the design needs it.

## Workflow

1. Write the markdown with front matter ('markitdoc: 2' turns the language on).
2. Run `markitdoc check file.md --json --format pdf` (or docx, pptx) and read every finding.
3. Fix each error and warning, using the 'fix' hint of the finding, and check again until it is clean.
4. Render with `markitdoc render file.md -o file.pdf` (the suffix picks the format).

## The language

{core_card("pdf")}

## References

- `{SKILL_FOLDER}/layouts.md`: the designed pages and slides, their slots and limits.
- `{SKILL_FOLDER}/styles.md`: palettes, font pairs, papers, selectors, a style file example and the support table by format.
- `{SKILL_FOLDER}/charts.md`: charts, diagrams and infographics.
"""


# the layouts reference: every designed layout with its purpose, slots and limits
def layouts_text():
    return "# Layouts\n\nDesigned pages and slides. Each is a fenced block; text between blocks flows as normal pages.\n\n" + "\n".join(
        layout_rule(name, layout) for name, layout in LAYOUTS.items() if name in LAYOUT_PURPOSES) + "\n"


# the styles reference: palettes, fonts, papers, selectors, an example style file and the support table
def styles_text():
    palettes = "\n".join(f"- {name}: {description}" for name, (_, _, description) in PALETTES.items())
    fonts = "\n".join(f"- {name}: {pair[4]}" for name, pair in FONT_PAIRS.items())
    return f"""# Styles

Front matter settings (version 1): palette, paper ({' | '.join(PAPERS)}), fonts, text_size ({' | '.join(TEXT_SIZES)}), tables ({' | '.join(TABLE_STYLES)}).

## Palettes
{palettes}

## Font pairs
{fonts}

## Selectors
{' '.join(STYLE_SELECTORS)}; sub-parts table.header, paragraph.first. List styles on a block before a list: {' '.join('{.' + name + '}' for name in LIST_SCHEMES)}.

## A style file
```yaml
{STYLE_EXAMPLE}
```

## Support by format
{support_table()}
"""


# the charts reference: chart JSON, callouts, diagram types and infographic templates
def charts_text():
    templates = "\n".join(f"- {name} ({kind}): {use}" for name, (kind, use) in INFOGRAPHIC_TEMPLATES.items())
    return f"""# Charts, diagrams and infographics

## Charts
A ```chart fence holds JSON with type ({' | '.join(CHART_TYPES)}), title, labels and datasets [{{label, values}}], one value per label.
Sizes: {', '.join(CHART_SIZES)} (```chart {{size=half}}). Give a chart {{#id caption="..."}} to number it and cite it as [@id].
Callouts: {', '.join('> **' + kind + ':**' for kind in CALLOUT_KINDS)}.

## Diagrams
A ```mermaid fence. The first line names the type, one of: {', '.join(DIAGRAM_TYPES)}. Keep labels short and use about 12 nodes at most.

## Infographics
A ```infographic fence: 'infographic <template>', then 'data' with a title and the template's list. Templates:
{templates}
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
