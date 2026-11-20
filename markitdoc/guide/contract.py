from markitdoc.errors import UnsupportedFormatError
from markitdoc.guide.language import core_card
from markitdoc.guide.support import support_table
from markitdoc.markup.elements import CALLOUT_KINDS, CHART_SIZES, LIST_SCHEMES, PARAGRAPH_ALIGNMENTS, SPAN_COLORS, TABLE_STYLES
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.models.model_constants import FLOW_CONTAINERS
from markitdoc.pptx.designed.titles import MAX_PER_SLIDE
from markitdoc.pptx.render import DRAWERS
from markitdoc.themes.brands import brand_summary, registered_brands
from markitdoc.themes.theme_constants import DEFAULT_PALETTE, FONT_PAIRS, PALETTES, PAPERS, STYLE_SELECTORS, TEXT_SIZES
from markitdoc.visuals.diagrams import DIAGRAM_TYPES
from markitdoc.visuals.infographics import INFOGRAPHIC_TEMPLATES

LAYOUT_PURPOSES = {
    "cover": "first page of a report, proposal or guide: kicker (small label), title, subtitle",
    "summary": "executive summary: conclusion first; title, lead, 2-4 headline figures 'value — label', body",
    "divider": "opens a major part of a long document: number, title, lead, optional items 'section name' listing what the part covers",
    "chapter": "narrative argument or story: number, title, lead, body as exactly two paragraphs (two columns; limits are per paragraph), optional quote",
    "figures": "3-6 headline numbers that carry the message: items 'value — label — one-sentence note', optional body",
    "keypoints": "3-5 numbered findings, recommendations or principles: items 'heading — explanation'",
    "matrix": "a 2x2 grid: SWOT, risks, options, quadrants: exactly 4 items 'label — text'",
    "quote": "one memorable statement given a whole page: quote, quote_by, optional context",
    "comparison": "two options, before/after, us/them side by side: left and right headings, items 'left text — right text', optional takeaway",
    "process": "ordered steps: title, lead, items 'step name — what happens' (no numbers in the step name)",
    "timeline": "dated events or a roadmap: title, lead, items 'when — event — description'",
    "feature": "one topic told in depth with 0-3 big figures: title, body, items 'figure — label'",
    "closing": "last page: optional quote and quote_by, title, body (conclusion, call to action, next steps)",
    "flow": "free markdown of any length: ## and ### headings, paragraphs, lists, tables, callouts, ```chart, ```mermaid and ```infographic; "
            "pages break automatically. Use it for analysis, evidence, tables, policies and anything long",
}
VARIANT_MEANINGS = {
    "cover": "light | dark | photo (full-bleed photo, needs images: true) | split (colour or photo strip on the left) | "
             "company (the brand's address and partner logos, brand templates only)",
    "divider": "light (default) | dark (use for at most one strong section break)",
    "chapter": "plain (default without a photo) | band (photo band when there is an image, colour band otherwise)",
    "quote": "light (default) | dark (a single dramatic statement)",
    "process": "vertical (default, up to 6 steps) | horizontal (3-4 steps side by side)",
    "timeline": "vertical (default, up to 8 events) | horizontal (3-5 events with short text)",
    "feature": "left | right (side of the photo or the figures rail)",
    "closing": "default | company (the brand's address and logos, brand templates only; then keep the body to ~100 words and skip the quote)",
}


EXAMPLE_DOCUMENT = """---
palette: forest
paper: warm
fonts: serif-heads
---
::: {.cover variant=light}
kicker: Annual review
title: Restoring the River Valley
subtitle: What five years of wetland restoration changed for water, wildlife and the towns downstream.
:::

## What changed
Flooding fell in all four towns and two species returned. The table compares the start and end of the programme.

| Measure | 2021 | 2025 |
|---|---|---|
| Flood days per year | 14 | 5 |
| Wetland area (ha) | 120 | 410 |
{.lined}

```chart
{"type": "bar", "title": "Wetland area (ha)", "labels": ["2021", "2025"], "datasets": [{"label": "Area", "values": [120, 410]}]}
```

::: {.figures}
title: Five years in numbers
410 ha — Wetland restored — Up from 120 hectares when the programme began.
64% — Fewer flood days — Across the four towns along the lower river.
2 — Species returned — Otters and kingfishers, absent for twenty years.
:::

::: {.closing}
title: The next five years
body: The programme now moves upstream, where the same methods can protect three more towns.
:::"""
GUIDE_LEVELS = ("core", "full", "writing", "layouts", "styles", "charts")
GUIDE_PARTS = {
    "layouts": "designed pages and slides (cover, key figures, timeline, comparison and more) and photos",
    "styles": "two-column sections, boxes and sidebars, drop caps, citations with a bibliography, cross-references such as "
              "'see Figure 3', landscape or per-section pages, headers and footers, watermark, custom heading and paragraph styles",
    "charts": "every chart type and size, waterfall charts, diagrams (flows, sequences, timelines, mind maps, Gantt) and infographics",
}
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
CONTRACT_INFOGRAPHICS = ("sequence-steps-badge-card", "list-grid-badge-card", "list-pyramid-badge-card")


# estimates how many words fit in a designed text box
def approximate_words(box, lines):
    average_width = 0.62 if "B" in box.style else 0.55
    return max(1, round(0.9 * lines * box.width / (box.size * 0.3528 * average_width) / 6.2))


# describes the word limit and requirement for a layout slot
def slot_rule(name, box):
    most = approximate_words(box, box.lines)
    rule = f"{name} ~{most} words" if most > 3 else f"{name} 1-3 words"
    if box.min_lines:
        rule += f" (at least ~{approximate_words(box, box.min_lines)})"
    return rule + ("" if box.required else ", optional")


# describes the text and item limits for a document layout
def layout_rule(name, layout):
    parts = [slot_rule(slot, box) for slot, box in layout.boxes.items()]
    low, high, limits = layout.items
    if limits:
        words = " / ".join(f"~{max(1, round(limit / 6.2))}" for limit in limits)
        parts.append(f"{low}-{high} items of {words} words per part" if low != high else f"{low} items of {words} words per part")
    if name in VARIANT_MEANINGS:
        parts.append(f"variant: {VARIANT_MEANINGS[name]}")
    if layout.image_ratio:
        parts.append("image: photo query (only when images: true)")
    return f"- {name}: {LAYOUT_PURPOSES[name]}." + (f"\n    {'; '.join(parts)}" if parts else "")


# the layouts reference: every designed layout with its purpose, slots and limits
def layouts_text():
    return ("# Layouts\n\nDesigned pages and slides. Each is a fenced block; text between blocks flows as normal pages:\n"
            "::: {.<layout> variant=<name> image=\"<photo query>\"}\n<slot>: <value on ONE line; separate paragraphs inside a slot with ' || '>\n"
            "<part> — <part>      (one item per line)\n:::\n\n") + "\n".join(
        layout_rule(name, layout) for name, layout in LAYOUTS.items() if name in LAYOUT_PURPOSES) + "\n"


# the styles reference: palettes, fonts, papers, selectors, an example style file and the support table
def styles_text():
    palettes = "\n".join(f"- {name}: {description}" for name, (_, _, description) in PALETTES.items())
    fonts = "\n".join(f"- {name}: {pair[4]}" for name, pair in FONT_PAIRS.items())
    return f"""# Styles

Front matter settings: palette, paper ({' | '.join(PAPERS)}), fonts, text_size ({' | '.join(TEXT_SIZES)}), tables ({' | '.join(TABLE_STYLES)}).

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


WRITING_HEADS = {
    "pdf": "PDF WRITING GUIDE.",
    "pptx": "SLIDE WRITING GUIDE (pptx).",
    "docx": "WORD WRITING GUIDE (docx).",
}
STRUCTURES = {
    "pdf": """STRUCTURE
- Open a report with a cover block, then write normal markdown; pages break by themselves (about 450 words a page):
  ::: {.cover}
  kicker: Annual review
  title: Restoring the River Valley
  subtitle: One sentence on what the document covers.
  :::
  A letter or memo has no cover: start with '# Title' or the letter itself.
- ## for sections, ### for subsections; never bold text as a heading. Hit the length the user asked for.
- toc: true in the front matter for documents longer than about 8 pages; numbering: decimal numbers headings
  1, 1.1 for technical, legal and policy documents.
- Write steps, findings, comparisons and dates as numbered lists, tables or a diagram. Other designed pages (summary,
  figures, timeline, chapter and more) are optional strong moments, about one per 6 pages: read the layouts part first.""",
    "pptx": """HOW A DECK READS (16:9 slides)
- Open with a cover block, then every ## heading starts a slide:
  ::: {.cover}
  kicker: Board update
  title: Restoring the River Valley
  subtitle: One sentence on what the deck covers.
  :::
- Write each ## as an action title: one sentence with the takeaway, at most about 12 words ('Enterprise drove 67% of
  growth', not 'Revenue overview'). Reading only the titles must tell the story.
- One message per slide, with ONE kind of evidence under its heading: 2-4 bullets written '- **Label** — explanation'
  (they become cards; a short paragraph before them becomes a statement panel), up to 6 short bullets, one table of
  at most 5 columns, one chart or one diagram. Layouts vary by themselves: write content, not layout.
- Bullets of at most about 15 words; longer text is shortened on the slide and kept in the speaker notes.
- A typical deck is 8-15 slides: cover, evidence slides, and a last slide with the decision or next step. For a
  headline-numbers slide, a timeline, a comparison or photo slides, read the layouts part first.
- In a table, cells written High, Medium, Low or None become Harvey balls (for ratings, not numbers).
- Sample figures: say once that they are samples, never in every bullet.""",
    "docx": """STRUCTURE (an editable Word file: real headings, editable tables, numbered lists, footnotes, page numbers)
- Open a report with a cover block (it becomes a title page), then write normal markdown:
  ::: {.cover}
  kicker: Annual review
  title: Restoring the River Valley
  subtitle: One sentence on what the document covers.
  :::
  A letter or memo has no cover: start with '# Title' or the letter itself.
- ## for sections, ### for subsections; the contents page lists them. Never bold text as a heading.
- A page holds about 450 words (less with tables and charts): a 10-page document is about 3,500-4,000 words.
  Do not pad; cut before you pass the page count the user asked for.
- toc: true in the front matter for documents longer than about 8 pages; numbering: decimal numbers headings
  1, 1.1 for technical, legal and policy documents. +++ on its own line starts a major part on a new page.
- Charts, diagrams and equations become pictures with numbered captions; tables stay editable. In a table, cells
  written High, Medium, Low or None become Harvey balls.
- Write steps, findings, comparisons and dates as numbered lists or tables. Designed blocks (summary, figures,
  timeline and more) become sections in the flow: read the layouts part first.""",
}
WRITING_MARKDOWN = """- Facts: never invent specific dates, years or figures; use what the user gave, well-known history, or clearly
  labelled sample figures.

MARKDOWN
- Text: **bold**, *italic*, `code`, [link](https://...); footnote text[^1] with '[^1]: note' on its own line.
  Colour a few words, sparingly: [words]{.accent} [words]{.danger} [words]{.success} [words]{.muted}.
- Lists: '-' bullets and '1.' numbers, nested by indenting; '- [ ]' and '- [x]' make checkboxes.
- Tables: a header row, at most 7 columns (5 on slides), units in the headers; a line 'Table: what it shows'
  just before the table numbers it.
- Callouts: '> **Note:** ...', '> **Action:** ...', '> **Risk:** ...', '> **Key figure:** 42% — what it means'.
- Shaded panel: '::: {.box title="Key facts"}' ... ':::'.
- Images: ![what it shows](file.png){width=1/2} sizes an image by width, {height=60mm} by height, both together fit it in
  that box, {ratio=16:9} crops it to that shape; an image always shrinks to fit the page.
- Maths: $x^2$ inline, display equations between $$ lines (LaTeX). Money like $25 is never maths.
- Chart:
  ```chart
  {"type": "bar", "title": "Wetland area (ha)", "labels": ["2021", "2025"], "datasets": [{"label": "Area", "values": [120, 410]}]}
  ```
  type: bar | horizontal_bar | stacked_bar | line | pie | donut | waterfall. Values are plain numbers (no %, units
  or commas), exactly one per label, or the chart is left out.
- Never draw diagrams with text characters; use a diagram (charts part)."""
CHOOSING_LAYOUTS = """CHOOSING DESIGNED PAGES
- From the content: headline numbers -> figures; findings or recommendations -> keypoints; argument or story -> chapter;
  options or before/after -> comparison; SWOT, risks or quadrants -> matrix; steps -> process; dates -> timeline;
  one striking statement -> quote. Use only what the content needs; there is no fixed sequence.
- A designed page must be full; never the same layout twice in a row; about one per 6 pages. A page with too little
  content is printed as normal text. Quote and closing pages only with images: true.
- Chapter body: two substantial paragraphs, one per column (roughly 80-100 words each).

PHOTOS (only with images: true)
- photos: natural | duotone | mono (natural = true colour; duotone = tinted in the palette, unifies mixed photos;
  mono = black and white, archival or sober).
- Add 'image: <query>' to the cover and to 1-3 chapter or feature pages: 2-4 English words naming a concrete,
  photographable subject an encyclopedia photo archive holds (a landmark, object, vehicle, machine, place, historic
  event). Be specific: subject + setting + light, like "reed marsh at sunrise" or "stone bridge in fog", never abstract
  words like "growth", moods, people's or company names, user data or document content.
- In normal pages, ![a concrete photographable subject](figure) on its own line becomes a captioned "Figure N"; its
  text is also the photo search.
- To use one exact Wikimedia Commons photo, write its file title instead of a query: image="File:Tram 28 Lisbon.jpg"
  on a designed page, or ![Tram 28 climbing in Alfama](File:Tram 28 Lisbon.jpg) in normal pages."""
SLIDE_EXTRAS = """SLIDE VISUALS
- A timeline whose entries are date ranges ('Q1 2026 – Q3 2026', 'Jan – Apr 2027') becomes a Gantt chart; use one unit
  (quarters, months or years) for every entry. A figure whose value is a percentage gets a progress ring.
- Photos (only with images: true): cover, divider, quote and closing blocks with image="<query>" fill the whole slide
  under a dark overlay; chapter and feature blocks with image="<query>" become split slides. In a ## section,
  ![<query>](figure) with a short paragraph makes a split slide, alone under a heading a full-screen photo, two or three
  in a row a photo grid. Write each query as the subject's encyclopedia name, proper name first ('Apollo 11 launch').
  Use photos on about a third of the slides at most."""
WORD_EXTRAS = """IN WORD
The document flows; there are no fixed pages. Designed blocks become sections: cover becomes a title page; figures and
summary become a row of key numbers; keypoints and process become numbered blocks; timeline becomes a dated table (or a
Gantt chart when entries are date ranges); comparison and matrix become tables; quote and closing become a pull quote
and a final section."""
CHART_EXTRAS = """- Waterfall: a bridge from one total to another, e.g. last year's profit, each driver up or down, this year's profit:
  ```chart
  {"type": "waterfall", "labels": ["2025 profit", "New customers", "Hosting"], "values": [12, 6.5, -3.4], "total": "2026 profit"}
  ```
  The first value is the starting total; the rest are changes (negative for decreases); "total" adds the end bar.
- Diagrams: keep labels short (2-4 words) and use at most about 12 nodes; flowchart LR for a simple chain of steps;
  never draw a plain list as a diagram. A 'title <text>' line after the type line gives it a numbered caption:
  ```mermaid
  flowchart LR
    title Approval path
    A[Request] --> B{Approved?}
    B -->|Yes| C[Deliver]
    B -->|No| D[Revise]
  ```
- Infographics, used sparingly: after 'data' and the title, the template's list is '- label <text>' with an indented
  'desc <text>'."""


# the front matter every document can set, with the palette and font names the renderer knows
def front_matter_rules():
    palettes = "; ".join(f"{name} ({description.split(': ', 1)[-1]})" for name, (_, _, description) in PALETTES.items())
    fonts = "; ".join(f"{name} ({pair[4]})" for name, pair in FONT_PAIRS.items())
    return f"""FRONT MATTER (every key is optional; leave one out to get its default)
---
palette: <name>          ({DEFAULT_PALETTE} when left out)
paper: {' | '.join(PAPERS)}      (warm = soft cream, editorial and long reads)
fonts: <pair>
images: true             (your call: photos help guides, places, history, products and brochures; leave them out
                         of data reports, policies, legal texts and letters; with true, read the layouts part)
---
Palettes, by subject: {palettes}.
Fonts: {fonts}.
Other parts of this guide, to read only when the document needs what they offer:
{chr(10).join(f"- {name}: {offer}" for name, offer in GUIDE_PARTS.items())}{brands_rule()}"""


# the brands an application registered, so a model can choose one only when the user asks for it or the document has it
def brands_rule():
    brands = registered_brands()
    if not brands:
        return ""
    lines = "\n".join(f"- {brand_summary(name)}" for name in brands)
    return (f"\nBrands you can use: choose one when the user asks for it, the current document has it, or the document speaks for that\n"
            f"organisation (its proposals, pitches, reports and letters). The brand sets colours and fonts:\n"
            f"{lines}")


# the part a model reads before every document: front matter, structure for the format and the everyday markdown
def writing_part(output_format):
    head = (f"{WRITING_HEADS[output_format]} Read it before every document, then submit the finished markdown once. You choose "
            "content and structure; the engine guarantees fit, contrast and typography, and prints a designed page that does not "
            "fit as normal text.")
    return "\n\n".join((head, front_matter_rules(), STRUCTURES[output_format] + "\n" + WRITING_MARKDOWN))


# the part for designed pages and photos: block syntax, how to choose, every layout and a complete example
def layouts_part(output_format):
    extras = {"pptx": SLIDE_EXTRAS + "\n\n" + slide_blocks(), "docx": WORD_EXTRAS}.get(output_format, "")
    return "\n\n".join(part for part in (layouts_text(), CHOOSING_LAYOUTS, extras, "Example:\n" + EXAMPLE_DOCUMENT) if part)


# the settings and markdown an ordinary document rarely needs, then the style language
def style_settings():
    return f"""{styles_text()}
## More front matter
text_size: {' | '.join(TEXT_SIZES)}; tables: {' | '.join(TABLE_STYLES)} (a line '{{.lined}}', '{{.striped}}' or '{{.boxed}}' directly
under a table styles that table); header and footer text with the fields {{title}} {{section}} {{date}} {{page}} {{pages}};
author; classification (a label on every page, e.g. Confidential); watermark (a faint diagonal word, e.g. Draft on a draft or Sample on a sample);
date: YYYY-MM-DD; lang: en | de | fr | es; notes: section | page (footnotes at the end of each section or on their page).

## More markdown
- ~~strikethrough~~, [words]{{.underline}}, H~2~O and x^2^; colours {' '.join('[words]{.' + name + '}' for name in SPAN_COLORS)}.
- Paragraph settings on their own line under the paragraph: {' '.join('{.' + name + '}' for name in [*PARAGRAPH_ALIGNMENTS, 'indent', 'lead'])}.
- A style line just before a numbered list sets its numbering: {' '.join('{.' + name + '}' for name in LIST_SCHEMES)} (legal = 1, 1.1, 1.1.1).
- '## Risks {{#risks}}' gives a heading an id; '[see the risks](#risks)' links to it.
- Containers: {', '.join(f"'::: {{.{name}}}'" for name in FLOW_CONTAINERS)}: box = shaded panel, sidebar = narrow panel on the
  right, columns = two columns split at ### headings.
- Definition list: a term on one line, then ': definition' on the next. Column alignment with |:---|:---:|---:|.
- LaTeX in $...$ and $$ blocks: \\frac, \\sqrt, \\sum, Greek letters.
"""


# how each designed block becomes a slide
def slide_blocks():
    slide_lines = "\n".join(f"- {name}: {LAYOUT_PURPOSES[name]}" + (f" (up to {MAX_PER_SLIDE[name]} items per slide; more continue on the next)"
                                                                    if name in MAX_PER_SLIDE else "") for name in DRAWERS)
    return f"DESIGNED BLOCKS AS SLIDES\n{slide_lines}"


# the guide for output_format at one level: core is the language card, writing is read before every document, layouts,
# styles and charts are loaded when a document needs them, and full is all of it
def guide(output_format="pdf", level="full"):
    if output_format not in WRITING_HEADS:
        raise UnsupportedFormatError(f"No guide for {output_format!r}, expected one of {', '.join(WRITING_HEADS)}")
    parts = {
        "core": lambda: core_card(output_format),
        "writing": lambda: writing_part(output_format),
        "layouts": lambda: layouts_part(output_format),
        "styles": lambda: style_settings() + "\n" + core_card(output_format),
        "charts": lambda: charts_text() + CHART_EXTRAS,
        "full": lambda: "\n\n".join((core_card(output_format), writing_part(output_format), layouts_part(output_format),
                                     style_settings(), charts_text() + CHART_EXTRAS)),
    }
    if level not in parts:
        raise UnsupportedFormatError(f"No guide level {level!r}, expected one of {', '.join(GUIDE_LEVELS)}")
    return parts[level]()
