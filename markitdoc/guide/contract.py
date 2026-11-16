from markitdoc.errors import UnsupportedFormatError
from markitdoc.guide.language import core_card
from markitdoc.markup.elements import CALLOUT_KINDS, CHART_SIZES, LIST_SCHEMES, PARAGRAPH_ALIGNMENTS, SPAN_COLORS, TABLE_STYLES
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.models.model_constants import FLOW_CONTAINERS
from markitdoc.pptx.designed.titles import MAX_PER_SLIDE
from markitdoc.pptx.render import DRAWERS
from markitdoc.themes.theme_constants import FONT_PAIRS, PALETTES, PAPERS, TEXT_SIZES
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
GUIDE_LEVELS = ("core", "full")
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


# builds the PDF design instructions for document generation
def pdf_contract() -> str:
    infographics = "\n".join(f"  - {name} ({INFOGRAPHIC_TEMPLATES[name][0]}): {INFOGRAPHIC_TEMPLATES[name][1]}"
                              for name in CONTRACT_INFOGRAPHICS)
    palette_lines = "\n".join(f"  - {name}: {description}" for name, (_, _, description) in PALETTES.items())
    font_lines = "\n".join(f"  - {name}: {pair[4]}" for name, pair in FONT_PAIRS.items())
    return f"""PDF DESIGN GUIDE. Read it fully, then call generate_document once with the finished markdown.
You are the editor and the designer: decide what the reader needs and shape the pages for it. The engine is
deterministic: it measures every page, gently shrinks or tightens text to fit, and turns a page that still does not
fit into plain text, so the document always renders. You choose content, structure and style; the engine guarantees
fit, contrast and typography.

Front matter:
---
palette: <name>        (choose the one whose world fits THIS subject; all are professional, there is no default)
paper: {' | '.join(PAPERS)}   (white = crisp corporate; warm = soft cream, editorial and long reads)
fonts: <pair>          (choose the typography that suits the reader; see Fonts)
text_size: {' | '.join(TEXT_SIZES)}   (small = dense reference, regular = most documents, large = easy reading, letters)
tables: {' | '.join(TABLE_STYLES)}   (lined = clean rules, best for most; striped = long tables; boxed = dense reference grids)
images: true | false   (true ONLY when the user asks for pictures or photos; false is the normal default)
photos: natural | duotone | mono   (with images: natural = true colour; duotone = tinted in the palette, unifies
                       mixed photos, editorial; mono = black and white, archival or sober)
toc: true | false      (true for documents longer than about 8 pages)
numbering: decimal     (optional: numbers ## and ### headings as 1, 1.1 - for technical, legal and policy documents)
header: <text>         (optional running header; fields {{title}} {{section}} {{date}} {{page}} {{pages}};
                       {{section}} is the current ## section, good for long reports)
footer: <text>         (optional footer, same fields, e.g. "{{title}} · {{date}}")
author: <name>         (optional; the document's author in the file properties)
classification: <text> (optional label printed at the top of every page, e.g. Confidential, Internal, Draft)
watermark: <text>      (optional faint diagonal word on every page, e.g. Draft or Sample; only when asked)
date: YYYY-MM-DD       (optional; the document date used by {{date}})
lang: en | de | fr | es  (document language; sets hyphenation and the language screen readers use)
notes: section | page  (footnotes at the end of each section (default) or at the bottom of the page they are cited on;
                        page suits legal, academic and policy documents)
---
Palettes (one accent colour used sparingly, mostly neutral pages):
{palette_lines}
Fonts (curated pairs that always work together; a brand template keeps its own):
{font_lines}
A brand look is chosen with the template argument, never in the markdown.

Most documents are mainly normal pages (flow): headings, paragraphs, lists, tables, charts and callouts that fill
every page, like a well-set consultancy report. Designed pages are a few strong moments, not the structure.
Without images: a light cover, then flow, with at most one figures or summary page and about one other designed page
per 6 pages; write steps, findings, comparisons and dates as numbered lists, tables or a diagram inside flow, not as
process, keypoints, comparison or timeline pages. A designed page with too little content is printed as normal text.
Designed pages are fenced blocks; text between them flows as normal pages:
::: {{.<layout> variant=<name> image="<photo query>"}}
<slot>: <value on ONE line; separate paragraphs inside a slot with ' || '>
<part> — <part>      (one item per line)
:::
Element settings in normal pages: a line '{{.lined}}', '{{.striped}}' or '{{.boxed}}' directly after a table styles
that table; ```chart {{size=half}} makes a chart smaller (use only for a minor supporting chart; most charts are full width).

LAYOUTS (word counts are guides; text is measured and gently shrunk to fit):
{chr(10).join(layout_rule(name, layout) for name, layout in LAYOUTS.items())}

PLANNING
- Decide what the reader must take away, then choose each page from its content: headline numbers -> figures;
  findings or recommendations -> keypoints; argument or story -> chapter; options or before/after -> comparison;
  SWOT, risks or quadrants -> matrix; steps -> process; dates -> timeline; one striking statement -> quote;
  evidence, tables, charts and long text -> flow. Use only what the content needs; there is no fixed sequence.
- A designed page must be full; never the same designed layout twice in a row. Quote and closing pages only
  with images: true; otherwise end with a normal ## section.
- Length: a designed page is one page; a flow page holds about 450 words. Hit the length the user asked for.
- Chapter body: use two substantial paragraphs, one per column (roughly 80-100 words each); text is measured, so use
  the page-fit check rather than adding filler when the content is shorter.
- Facts: never invent specific dates, years or figures; use what the user gave, well-known history, or clearly
  labelled sample figures.
- images: true -> add 'image: <query>' to the cover and to 1-3 chapter or feature pages: 2-4 English words naming a
  concrete, photographable subject an encyclopedia photo archive holds (a landmark, object, vehicle, machine, place,
  historic event). Be specific: subject + setting + light, like "reed marsh at sunrise", "heron in reeds", "stone
  bridge in fog", never abstract words like "growth" or "teamwork". Never moods, lifestyle scenes, people's or
  company names, user data or document content.
- When changing an existing document, return the full markdown with only the requested change.

MARKDOWN YOU CAN USE IN NORMAL PAGES (settings go on their own line DIRECTLY under the block they style)
- Text: **bold**, *italic*, ~~strikethrough~~, [words]{{.underline}}, `code`, [link text](https://...) (clickable),
  H~2~O and x^2^ (sub/superscript). Colour a few words with palette roles: {' '.join('[words]{.' + name + '}' for name in SPAN_COLORS)}
  (danger/success for good and bad numbers; highlight = a marker-pen band behind the words; use sparingly).
- Maths: inline $x^2 + y_i$ and display equations on their own lines between $$ and $$ (LaTeX syntax:
  \\frac, \\sqrt, \\sum, Greek letters). Money like $25 is never treated as maths.
- Paragraph settings: {' '.join('{.' + name + '}' for name in [*PARAGRAPH_ALIGNMENTS, 'indent', 'lead'])}
  (lead = larger opening paragraph; indent = one step in; justify for long formal prose).
- Lists: '-' bullets nest by indenting (markers change per level); '1.' numbers nest as 1 / a / i;
  '- [ ]' and '- [x]' make checkboxes. A style line on its own just BEFORE a numbered list sets its numbering:
  {' '.join('{.' + name + '}' for name in LIST_SCHEMES)} (legal = 1, 1.1, 1.1.1).
- Headings and links: '## Risks {{#risks}}' gives a heading an id; '[see the risks](#risks)' links to it.
- Containers inside normal pages: {', '.join(f"'::: {{.{name}}}'" for name in FLOW_CONTAINERS)} ... ':::'. box = shaded panel
  (add title="Key facts"), sidebar = narrow panel on the right, columns = two columns (split at ### headings).
- Table captions: a line 'Table: what the table shows' just before the table (numbered automatically).
- Definition list: a term on one line, then ': definition' on the next.
- Footnotes: text[^1] then '[^1]: note' anywhere; notes print at the end of that section.
- Tables: column alignment with |:---|:---:|---:|; a style line under the table: {' '.join('{.' + name + '}' for name in TABLE_STYLES)}.
- Charts: ```chart (sizes: {', '.join(CHART_SIZES)}); callouts: {', '.join("> **" + kind + ":**" for kind in CALLOUT_KINDS)}.
- Figures (only with images: true): ![a concrete photographable subject](figure) on its own line; it is captioned
  "Figure N" with your text, which is also the photo search, so follow the image-query rules.

FLOW PAGES
- Callouts: '> **Note:** ...', '> **Action:** ...', '> **Risk:** ...', '> **Key figure:** 42% — what it means'.
- Charts: ```chart with JSON keys type (bar | horizontal_bar | stacked_bar | line | pie | donut | waterfall), title, labels,
  datasets [{{label, values}}], one value per label.
- Tables: header row, 2-7 columns, units in headers.
- Never draw diagrams with text characters; use a ```mermaid diagram, a layout, a table or an infographic.
- Example of a complete short report (structure only; real documents are longer):
{EXAMPLE_DOCUMENT}
- Diagrams: a ```mermaid fence draws flows, sequences, states, structures and timelines in the document's colours
  and fonts. Use a diagram instead of drawing with text characters. The first line names the type, one of:
  {', '.join(DIAGRAM_TYPES)}. Keep labels short (2-4 words) and use at most about 12 nodes.
  Use flowchart LR for a simple chain of steps; never draw a plain list as a diagram, write the list. Add a 'title <text>' line
  after the type line to give it a numbered caption. Example:
  ```mermaid
  flowchart LR
    title Approval path
    A[Request] --> B{{Approved?}}
    B -->|Yes| C[Deliver]
    B -->|No| D[Revise]
  ```
- Infographics (use sparingly): ```infographic fence, first line 'infographic <template>', then 'data' with title
  and the template's list: '- label <text>' with an indented 'desc <text>'. Templates:
{infographics}"""


# builds the Word document instructions for document generation
def word_contract() -> str:
    return f"""WORD DOCUMENT GUIDE (docx). The same markdown as PDF, rendered as an editable Word document: real headings,
an automatic contents page (toc: true), styled tables, numbered lists, footnotes and page numbers. Read this part first;
the PDF guide below defines the front matter, block syntax and markdown.
- The document flows; there are no fixed pages. Designed blocks become sections inside it: cover becomes a title page;
  figures and summary become a row of key numbers; keypoints and process become numbered blocks; timeline becomes a
  dated table (or a Gantt chart when entries are date ranges); comparison and matrix become tables; quote and closing
  become a pull quote and a final section.
- Length: a Word page holds about 450 words of body text (less with tables and charts). Hit the page count the user
  asked for: a 10-page document is about 3,500-4,000 words in total. Do not pad; cut before you exceed it.
- Use +++ only to start a major part on a new page (it moves the next heading to a new page; never stack two).
- Use ## for sections and ### for subsections; the contents page lists them. Never use bold text as a heading.
- Charts, diagrams, photos and equations are placed as pictures with numbered captions; tables stay editable.
- Comparison tables with High / Medium / Low / None (or Full / Partial) become Harvey balls; a chart with
  "type": "waterfall" draws a bridge from one total to another.

{pdf_contract()}"""


# builds the slide design instructions for document generation
def slides_contract() -> str:
    slide_lines = "\n".join(f"- {name}: {LAYOUT_PURPOSES[name]}" + (f" (up to {MAX_PER_SLIDE[name]} items per slide; more continue on the next)"
                                                                    if name in MAX_PER_SLIDE else "") for name in DRAWERS)
    return f"""SLIDE DESIGN GUIDE (pptx). The same markdown as PDF, rendered as 16:9 slides. Read this part first; the PDF guide
below defines the front matter, block syntax and markdown, and applies unless this part says otherwise.

HOW A DECK READS
- Every ## heading starts a slide. Write it as an action title: one sentence that states the takeaway, at most about
  12 words ('Enterprise drove 67% of growth', not 'Revenue overview'). Reading only the titles must tell the story.
- One message per slide. Under a heading put ONE kind of evidence: 2-4 bullets written '- **Label** — explanation'
  (they become a row of cards), up to 6 short bullets, one table, one chart, one diagram or one figure.
- Slides show short text. Write bullets of at most about 15 words; longer prose is shortened on the slide and kept
  in full in the speaker notes, so put talk-track detail in plain paragraphs only when the speaker needs it.
- A typical deck is 8-15 slides: a cover first, then a figures or summary slide, the evidence slides, and a closing
  slide with the decision or next step. Use designed blocks for the strong moments; most slides are ## sections.
- Tables: at most 5 columns; long tables continue on the next slide with the header repeated. Charts: one per slide.
- Sample figures: say once that figures are samples (in the lead or a footnote), never inside every card or bullet.
- Data visuals, used only when the content has that shape of data:
  - waterfall: a bridge from one total to another, e.g. last year's profit, each driver up or down, this year's profit.
    ```chart {{"type": "waterfall", "labels": ["2025 profit", "New customers", "Hosting"], "values": [12, 6.5, -3.4], "total": "2026 profit"}}```
    The first value is the starting total; the rest are changes (negative for decreases); "total" adds the end bar.
  - ratings in a comparison table: write High, Medium, Low, None (or Full, Partial) in a column and every cell becomes a
    Harvey ball (a filled circle showing the level). Use it for qualitative comparisons, not for numbers.
  - roadmap: a timeline whose entries are date ranges ('Q1 2026 – Q3 2026', 'Jan – Apr 2027', '2026 – 2028') becomes a
    Gantt chart with bars on a time axis. Use one unit (quarters, months or years) for every entry.
  - a figure whose value is a percentage ('82%') gets a progress ring showing that share. Only real percentages.
- Bullets written '- **Label** — explanation' become cards; a short paragraph before them becomes a statement panel.
  Consecutive slides vary their layout automatically, so write content, not layout.
- Photos (only with images: true). Each photo becomes a full-bleed or half-bleed slide, never a small framed picture:
  - cover, divider, quote and closing blocks with image="<query>" fill the whole slide with the photo under a dark
    overlay, with white text on top. Use them for the opening, each major part, a key quotation and the ending.
  - chapter and feature blocks with image="<query>" become split slides: the photo fills one half edge to edge and
    the title and text sit on the other half. Sides alternate through the deck.
  - in a ## section, ![<query>](figure) with a short paragraph makes a split slide; ![<query>](figure) alone under a
    heading makes a full-screen photo with the title on it; two or three figures in a row make a photo grid.
  - Write each query as the subject's encyclopedia name, the way a photo of it would be titled: 'Apollo 11 launch',
    'Chiswick House', 'Royal Crescent Bath'. Put the proper name first. A photo is shown only when its title matches.
  - Use photos on about a third of the slides at most; the rest carry the evidence (figures, cards, charts, tables).

DESIGNED BLOCKS AS SLIDES
{slide_lines}

{pdf_contract()}"""


# the writing guide an AI model should read before producing markdown for output_format: the language core card, then
# (level "full") the layout catalogue
def guide(output_format="pdf", level="full"):
    writers = {"pdf": pdf_contract, "pptx": slides_contract, "docx": word_contract}
    if output_format not in writers:
        raise UnsupportedFormatError(f"No guide for {output_format!r}, expected one of {', '.join(writers)}")
    if level not in GUIDE_LEVELS:
        raise UnsupportedFormatError(f"No guide level {level!r}, expected one of {', '.join(GUIDE_LEVELS)}")
    return core_card(output_format) if level == "core" else core_card(output_format) + "\n\n" + writers[output_format]()
