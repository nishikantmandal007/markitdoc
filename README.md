<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
    <img src="docs/assets/logo.svg" alt="MarkitDoc" width="300">
  </picture>
</p>

Markdown to professional PDF, PowerPoint and Word documents. One markdown source, three formats, typeset the same way
every time: themes and font pairs, designed pages and slides, native charts, flowcharts, tables, maths and photos.
Built so that an AI model can write the markdown and the library does the design.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Installed as a package (`pip install git+https://github.com/nishikantmandal007/markitdoc.git@main`), MarkitDoc is the
rendering library alone, with its fonts, icons and diagram scripts bundled; no network is needed unless you turn on
photo search or diagram rendering.

## Usage

```python
import markitdoc

markdown = """---
palette: ocean
---
# Quarterly review

Revenue grew **12%** while costs held flat.

| Region | Revenue |
|---|---|
| North | 4.2 |
| South | 3.1 |
"""

markitdoc.render(markdown, "pdf", "review.pdf")
markitdoc.render(markdown, "pptx", "review.pptx")
markitdoc.render(markdown, "docx", "review.docx")
```

From the command line:

```bash
markitdoc render review.md -o review.pdf     # the output suffix picks the format
markitdoc guide pptx                         # the markdown guide for slides
```

### Writing with an AI model

`markitdoc.guide("pdf" | "pptx" | "docx")` returns the full markdown guide for a format: layouts, slots and their word
limits, charts, diagrams and front-matter settings. Give it to the model as instructions, then render what it writes.

To keep the model's context small, load it in parts: `guide(format, "writing")` (about 4k characters) before every
document, then `"layouts"`, `"styles"` or `"charts"` only when the document needs designed pages, custom styling or
visuals. Run `markitdoc.check_document(markdown, output_format=format)` before rendering and send any `error` findings
back to the model to fix.

### The language

MarkitDoc is a typesetting language shared by PDF, Word and PowerPoint: named styles, rules by element, boxes, columns, images,
page masters, cross-references and citations. All of it is always on; write only what the design needs.

```markdown
---
set:
  h2: {color: accent}
styles:
  pull: {size: l, align: center, border: top}
---
## Evidence {#evidence}

The [riparian buffer]{.term} tripled; see [@evidence].

::: box {border=thin padding=m bg=surface}
A boxed note.
:::
```

`markitdoc check report.md --json --format pptx` reports problems, with a note for each feature the format approximates or
ignores. `markitdoc guide pdf --level core` prints the language card, and `markitdoc skill -o folder` writes a SKILL.md
with reference files for an AI model.

### Brands

Two neutral themes ship with the library (`professional`, `editorial`), with ten palettes and five font pairs. A brand is
a folder of theme files with its own logo, partner logos, address, footer and an optional PowerPoint master:

```python
markitdoc.register_brand("brand/")                  # brand/acme.yml, brand/logo.png, brand/acme.pptx
markitdoc.render(markdown, "pdf", "out.pdf", template="acme")
```

A theme file with `locked: true` keeps its own colours and fonts whatever the markdown asks for. Word headers and covers
that a theme file cannot describe are drawn by hooks: `register_brand(folder, docx_chrome=..., docx_cover=...)`.

### Offline by default

Photos (`images: true`) come from Wikimedia Commons and Mermaid diagrams render through a
[Gotenberg](https://gotenberg.dev) server set in `GOTENBERG_ENDPOINT`; without them every visual falls back to text.
Downloads are cached in `~/.cache/markitdoc` (or `MARKITDOC_CACHE`).
Per-render settings can override both defaults: `markitdoc.render(..., options=markitdoc.Options(gotenberg_url="http://localhost:3000", cache_folder=Path("./cache")))`.

## Layout

```
markitdoc/
  rendering.py   render(): markdown to a file
  models/        document parser and the catalogue of designed layouts
  markup/        inline runs, block preparation, fence and table settings (shared by all formats)
  themes/        theme files, palettes, font pairs and brand registration
  guide/         the markdown guide for AI models
  pdf/ pptx/ docx/   the three renderers
  visuals/       charts, diagrams, infographics, equations, icons, photos, Gantt plans
  assets/        bundled fonts (OFL), Lucide icons (ISC), Mermaid and AntV (MIT), themes
```

## Tests

```bash
uv run pytest
```
