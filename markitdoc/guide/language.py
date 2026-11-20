from markitdoc.guide.support import limits_of
from markitdoc.themes.theme_constants import (
    BORDER_WORDS,
    BOX_PROPERTIES,
    COLUMN_RATIOS,
    IMAGE_SIDES,
    PADDING_MM,
    RADIUS_MM,
    SCALE_WORDS,
    STYLE_ALIGNS,
    STYLE_COLOR_ROLES,
    STYLE_FILE_KEYS,
    STYLE_PROPERTIES,
    STYLE_SELECTORS,
    TRACKING_POINTS,
)

# front matter keys a slide never reads, left out of the slide card
SLIDE_IGNORED_KEYS = ("page", "pages")


# the language core card for a format: front matter, named styles, attributes, boxes, columns, references and check
def core_card(output_format="pdf"):
    keys = [key for key in STYLE_FILE_KEYS if not (output_format == "pptx" and key in SLIDE_IGNORED_KEYS)]
    limits = limits_of(output_format)
    notes = "; ".join(f"{name} {status}" for status, name in sorted((status, name) for name, (status, _) in limits.items()))
    page = "" if output_format == "pptx" else "\n- page / pages: paper, margins, orientation, header, footer, numbers; '+++ {page=wide}' switches page master"
    dropcap = "" if output_format == "pptx" else ", dropcap lang"
    pages = "" if output_format == "pptx" else ", [@id page] a page number"
    lists = "" if output_format == "pptx" else "; lists: [figures, tables] adds lists; a ::: references block places the bibliography"
    return f"""MARKITDOC LANGUAGE (core).
Front matter and *.style.yml share one schema, top-level keys: {', '.join(keys)}.
- use: [house]  style files, applied in order, later wins. text: {{font: serif, size: 10.5pt, align: justify}} body defaults.
- set: rules by element, e.g. h2: {{font: display, color: accent}}. Elements: {' '.join(STYLE_SELECTORS)}; sub-part: table.header, paragraph.first.
- styles: named styles used as {{.pull}} on a block or [words]{{.term}} in text, e.g. pull: {{based-on: quote, size: l, align: center}}.
- colors / fonts: names usable anywhere ('brand: "#0F766E"'). fields: constants used as {{client}}. allow: {{raw: false}} forbids raw keys. refs: sources inline or a refs.yml file.{page}
Attributes: {{#id .class key=value key="two words" flag}}. Spans and headings take them on the same line, other blocks on their own line below.
Text keys: {', '.join(STYLE_PROPERTIES)}{dropcap}. Box keys: {', '.join(key for key in BOX_PROPERTIES if '-' not in key)}.
Values: size {' '.join(SCALE_WORDS)} or 12pt; padding {' '.join(PADDING_MM)}; radius {' '.join(RADIUS_MM)}; length 1/2, 50%, 4mm; border {' '.join(BORDER_WORDS)} plus a width and a colour.
Colours: {' '.join(STYLE_COLOR_ROLES)}, a name under colors:, or #hex. weight normal|bold; align {' '.join(STYLE_ALIGNS)}; caps small|all; tracking {' '.join(TRACKING_POINTS)}.
Blocks: '::: box {{border=thin padding=m bg=surface}}' ... ':::' and '::: columns {{ratio=2:1}}' (ratios {' '.join(COLUMN_RATIOS)}; the second half starts at the middle block).
Images: ![alt](images/gauge.jpg){{#gauge width=1/2 side={'|'.join(IMAGE_SIDES)} caption="Alder, 2024"}}.
References: give a heading, figure, chart, table caption or equation an {{#id}}; [@id] reads 'Figure 3'{pages}; [@key] cites an entry of refs
  (style: numeric|author-year){lists}.
Not fully supported in {output_format}: {notes or 'nothing, everything above is full'}."""
