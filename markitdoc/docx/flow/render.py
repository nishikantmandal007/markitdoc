import io
import logging
import re
from pathlib import Path

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import Image

from markitdoc.docx.flow.lists import add_list_item, new_list
from markitdoc.docx.flow.tables import add_table, step_table
from markitdoc.docx.styles import BODY_SIZE, border_bottom, cell_borders, cell_fill, cell_margins, new_table
from markitdoc.docx.writer import (
    LIST_FORMATS,
    add_picture,
    align_paragraph,
    bookmark,
    caption,
    first_paragraph,
    master_section,
    photo,
    plain,
    start_on_new_page,
    write_runs,
)
from markitdoc.markup.editorial import dropcap_lines, interrupts_opening, trimmed_runs
from markitdoc.markup.elements import (
    CALLOUT_KINDS,
    TABLE_STYLES,
    chart_data,
    closing_index,
    element_settings,
    image_size,
    settings_from,
    top_level_blocks,
    without_display_maths,
    written_image,
)
from markitdoc.markup.inline import ANCHOR, UNNUMBERED, Run, inline_runs, parser
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.model_constants import PAGE_SWITCH
from markitdoc.options import options_in_use
from markitdoc.themes.theme_constants import POINT_MM, STYLE_PROPERTIES
from markitdoc.visuals.charts import render_chart
from markitdoc.visuals.diagrams import ZOOM, chain_steps, diagram_as_text, diagram_title, render_diagram
from markitdoc.visuals.equations import equation_png_bytes, mathtext_ready
from markitdoc.visuals.infographics import render_infographic

logger = logging.getLogger(__name__)
DROPCAP_LINE, DROPCAP_CAP_HEIGHT = 1.18 * 1.2, 0.7
ALIGNMENTS = {"center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}
BOX_DRAWING = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬"


# parses markdown and renders its tokens into the Word document
def render_markdown(writer, markdown):
    tokens = parser.parse(markdown)
    for position, token in enumerate(tokens):
        if token.type == "heading_open":
            found = ANCHOR.search(tokens[position + 1].content)
            if found:
                writer.targets.add(found.group(1))
    render_tokens(writer, tokens)


# renders markdown tokens into the current output format
def render_tokens(writer, tokens):
    index, stack, pending = 0, [], ""
    while index < len(tokens):
        token = tokens[index]
        kind = token.type
        if interrupts_opening(token):
            writer.section_start = False
        if kind == "footnote_block_open":
            end = closing_index(tokens, index, "footnote_block_open", "footnote_block_close")
            writer.notes += [inline_runs(item, writer.targets) for item in tokens[index:end] if item.type == "inline"]
            index = end + 1
            continue
        if kind.startswith("container_") and kind.endswith("_open"):
            name = kind[len("container_"):-len("_open")]
            end = closing_index(tokens, index, kind, f"container_{name}_close")
            add_container(writer, name, token.info, tokens[index + 1:end])
            index = end + 1
            continue
        if kind == "heading_open":
            add_heading(writer, int(token.tag[1]), tokens[index + 1])
            index += 3
            continue
        if kind == "paragraph_open":
            pending = add_paragraph_token(writer, tokens, index, stack, pending)
            index += 3
            continue
        if kind in ("bullet_list_open", "ordered_list_open"):
            scheme = pending if pending in LIST_FORMATS else "decimal"
            ordered = kind == "ordered_list_open"
            stack.append(new_list(writer, ordered, scheme, int(token.attrs.get("start", 1) or 1) if ordered else 1))
            pending = ""
        elif kind in ("bullet_list_close", "ordered_list_close"):
            stack.pop()
        elif kind == "list_item_open":
            stack[-1]["fresh"] = True
        elif kind == "blockquote_open":
            end = closing_index(tokens, index, "blockquote_open", "blockquote_close")
            add_quote(writer, tokens[index + 1:end])
            index = end + 1
            continue
        elif kind == "table_open":
            end = closing_index(tokens, index, "table_open", "table_close")
            settings = element_settings(tokens, end + 1)
            add_table(writer, tokens[index:end], settings.get("class") if settings.get("class") in TABLE_STYLES else "")
            index = end + 1 + (3 if settings.get("class") in TABLE_STYLES else 0)
            continue
        elif kind == "fence":
            add_fence(writer, token.info.strip(), token.content)
        elif kind == "code_block":
            add_code(writer, token.content)
        elif kind == "math_block":
            add_equation(writer, token.content)
        elif kind == "hr":
            rule = writer.body.add_paragraph()
            border_bottom(rule, writer.hex("rule"), 6, 1)
        elif kind == "dt_open":
            paragraph = writer.body.add_paragraph()
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.space_after = Pt(1)
            write_runs(writer, paragraph, inline_runs(tokens[index + 1], writer.targets), bold=True, role="ink")
            index += 3
            continue
        index += 1


# draws a section heading and tracks its outline level
def add_heading(writer, level, inline):
    unnumbered = UNNUMBERED.search(inline.content)
    found = ANCHOR.search(UNNUMBERED.sub("", inline.content))
    runs = inline_runs(inline, writer.targets)
    if unnumbered and runs:
        runs[-1] = Run(UNNUMBERED.sub("", runs[-1].text), runs[-1].bold, runs[-1].italic)
    if found and runs:
        runs[-1] = Run(ANCHOR.sub("", runs[-1].text), runs[-1].bold, runs[-1].italic)
    if level == 1 and writer.skip_title and "".join(run.text for run in runs).strip() == writer.skip_title:
        writer.skip_title = ""
        return None
    look = writer.look(f"h{min(level, 4)}")
    if level == 1 and not writer.titled:
        writer.titled = True
        paragraph = writer.body.add_paragraph(style="Title")
        align_paragraph(paragraph, look)
        write_runs(writer, paragraph, runs, look=look)
        return paragraph
    if writer.numbered and not unnumbered and 2 <= level <= 4:
        writer.headings[level - 1] += 1
        writer.headings[level:] = [0] * (4 - level)
        runs = [Run(".".join(str(number) for number in writer.headings[1:level]) + "   ")] + runs
    writer.section_start = level <= 2
    paragraph = writer.body.add_paragraph(style=f"Heading {min(level, 4)}")
    start_on_new_page(writer, paragraph)
    align_paragraph(paragraph, look)
    write_runs(writer, paragraph, runs, look=look)
    if found:
        bookmark(writer, paragraph, found.group(1))
    return paragraph


# writes the first letter of a paragraph as a Word drop cap frame spanning the given lines and returns the runs left for the paragraph
def add_dropcap(writer, runs, lines, look):
    pitch = BODY_SIZE * DROPCAP_LINE
    size = ((lines - 1) * pitch + BODY_SIZE * DROPCAP_CAP_HEIGHT) / DROPCAP_CAP_HEIGHT
    paragraph = writer.body.add_paragraph()
    properties = paragraph._p.get_or_add_pPr()
    frame = OxmlElement("w:framePr")
    for key, value in (("dropCap", "drop"), ("lines", str(lines)), ("wrap", "around"), ("vAnchor", "text"), ("hAnchor", "text")):
        frame.set(qn(f"w:{key}"), value)
    properties.insert_element_before(frame, "w:widowControl", "w:numPr", "w:pBdr", "w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc", "w:rPr")
    paragraph.paragraph_format.line_spacing_rule, paragraph.paragraph_format.line_spacing = WD_LINE_SPACING.EXACTLY, Pt(pitch * lines)
    paragraph.paragraph_format.space_after = Pt(0)
    letter = paragraph.add_run(runs[0].text[0])
    letter.font.size, letter.font.name, letter.font.bold = Pt(size), writer.heading_font, True
    letter.font.color.rgb = writer.rgb("mood")
    return [Run(runs[0].text[1:], runs[0].bold, runs[0].italic, style=runs[0].style), *runs[1:]]


# renders a paragraph token with its settings and inline content
def add_paragraph_token(writer, tokens, index, stack, pending):
    inline, equations = without_display_maths(tokens[index + 1])
    content = inline.content.strip()
    if switch := PAGE_SWITCH.match(content):
        values = parse_attributes(switch.group(1)).values
        master_section(writer, str(values.get("page") or writer.master_name), values.get("numbers") == "restart")
        return ""
    settings = re.search(r"\n?\{([^{}]*)\}\s*$", content)
    style = settings_from(settings.group(1)).get("class", "") if settings else ""
    labelled = parse_attributes(settings.group(1)).id if settings else ""
    if settings and not content[:settings.start()].strip():
        for number, equation in enumerate(equations):
            add_equation(writer, equation, labelled if number == 0 else "")
        return style
    picture = next((child for child in inline.children or [] if child.type == "image"), None)
    written = written_image(content) if picture is not None else None
    if written:
        add_file_picture(writer, written)
        return ""
    if picture is not None:
        add_figure(writer, picture.content or str(picture.attrs.get("alt", "")))
        return ""
    runs = inline_runs(inline, writer.targets)
    if settings and runs:
        runs[-1] = Run(re.sub(r"\s*\{[^{}]*\}\s*$", "", runs[-1].text), runs[-1].bold, runs[-1].italic, role=runs[-1].role, style=runs[-1].style)
    text = "".join(run.text for run in runs).strip()
    if content == "+++":
        writer.break_next = True
        return ""
    if text.startswith("Table:") and not stack:
        writer.pending_caption, writer.pending_target = text[6:].strip(), labelled
        return ""
    block_line = re.search(r"(?<![\]*_`])\{([^{}]*)\}\s*$", content)
    attributes = parse_attributes(block_line.group(1) if block_line else "")
    look = writer.look("list" if stack else "paragraph.first" if writer.section_start else "paragraph", attributes.classes, attributes.values)
    writer.section_start = False
    if stack:
        add_list_item(writer, stack, runs, look)
    elif text:
        lines = dropcap_lines(look)
        if lines and style != "lead" and (cut := trimmed_runs(inline, writer.targets, block_line)) and cut[0].text[:1].isalpha() and not cut[0].link:
            runs = add_dropcap(writer, cut, lines, look)
        paragraph = writer.body.add_paragraph(style="Lead" if style == "lead" else None)
        align_paragraph(paragraph, look)
        if style in ALIGNMENTS:
            paragraph.alignment = ALIGNMENTS[style]
        if "\t" in text:
            paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(writer.width), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
            paragraph.paragraph_format.space_after = Pt(3)
        write_runs(writer, paragraph, runs, look=look)
        if labelled in writer.numbers and writer.numbers[labelled].kind == "reference":
            bookmark(writer, paragraph, labelled)
    for number, equation in enumerate(equations):
        add_equation(writer, equation, labelled if number == 0 else "")
    return ""


# renders a blockquote as a callout or quote paragraphs
def add_quote(writer, tokens):
    inlines = [token for token in tokens if token.type == "inline"]
    if not inlines:
        return
    first = inline_runs(inlines[0], writer.targets)
    label = first[0].text.strip().rstrip(":") if first and first[0].bold else ""
    if label in CALLOUT_KINDS:
        runs_list = [inline_runs(token, writer.targets) for token in inlines]
        add_callout(writer, label, runs_list)
        return
    look = writer.look("quote")
    for token in inlines:
        paragraph = writer.body.add_paragraph(style="Quote")
        align_paragraph(paragraph, look)
        write_runs(writer, paragraph, inline_runs(token, writer.targets), look=look)


# draws a colored callout table in the Word document
def add_callout(writer, label, runs_list, role="mood"):
    table = callout_table(writer, writer.hex(writer.tint(role, 0.9)), writer.hex(role))
    cell = table.cell(0, 0)
    for number, runs in enumerate(runs_list):
        paragraph = first_paragraph(cell) if number == 0 else cell.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(3)
        write_runs(writer, paragraph, runs, role="ink" if number == 0 else None)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


# creates a shaded one-cell callout table with an accent border
def callout_table(writer, fill, accent):
    table = new_table(writer, 1, 1, [writer.width])
    cell = table.cell(0, 0)
    cell_fill(cell, fill)
    cell_borders(cell, left=(accent, 24))
    cell_margins(cell, 0.22, 0.35, 0.18)
    return table


# renders a columns or box container in the Word document
def add_container(writer, name, info, tokens):
    attributes = parse_attributes(info)
    if name == "columns":
        children = top_level_blocks(tokens)
        half = (len(children) + 1) // 2
        weights = writer.styles.columns(attributes.values)[0]
        widths = [writer.width / 2 - 0.2, writer.width / 2 + 0.2] if weights == (1, 1) else [writer.width * weight / sum(weights) for weight in weights]
        inner = [writer.width / 2 - 0.4] * 2 if weights == (1, 1) else [width - 0.4 for width in widths]
        table = new_table(writer, 1, 2, widths)
        for column, part in enumerate((children[:half], children[half:])):
            cell = table.cell(0, column)
            cell_margins(cell, 0, 0.1 if column else 0, 0)
            with writer.inside(cell, inner[column]):
                render_tokens(writer, [token for block in part for token in block])
            drop_empty_first(cell)
        return
    look = writer.look("box", attributes.classes, attributes.values) if name == "box" else None
    if look and look.boxed():
        add_styled_box(writer, look, tokens)
        return
    table = callout_table(writer, writer.hex("surface"), writer.hex("mood"))
    cell = table.cell(0, 0)
    with writer.inside(cell, writer.width - 0.7):
        render_tokens(writer, tokens)
    drop_empty_first(cell)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


# renders a box as a one-cell table with the look's borders, fill and padding, its text properties passing down to the content
def add_styled_box(writer, look, tokens):
    width = min(writer.width, writer.styles.length(look.width, writer.width * 10) / 10) if look.width else writer.width
    pad = (look.padding or 0) / 10
    table = new_table(writer, 1, 1, [width])
    cell = table.cell(0, 0)
    if look.fill:
        cell_fill(cell, writer.hex(look.fill))
    for old in cell._tc.tcPr.findall(qn("w:tcBorders")):
        cell._tc.tcPr.remove(old)
    cell_borders(cell, **{side: (writer.hex(rgb), max(2, round(line / POINT_MM * 8))) for side, (line, rgb) in look.borders.items()})
    cell_margins(cell, pad, pad, pad)
    before = writer.context
    writer.context = {key: found for key, found in look.props.items() if key in STYLE_PROPERTIES}
    with writer.inside(cell, width - 2 * pad - 0.2):
        render_tokens(writer, tokens)
    writer.context = before
    drop_empty_first(cell)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


# adds an image written with a file path at its width, with its caption; a missing file leaves its alt text in brackets
def add_file_picture(writer, found):
    alt, source, written = found.group(1), found.group(2), found.group(3) or ""
    attributes = parse_attributes(written)
    look = writer.look("figure", attributes.classes, attributes.values)
    folders = options_in_use().style_folders
    path = (Path(folders[0]) if folders else Path()) / source
    natural = image_size(path)
    if natural:
        asked = writer.styles.length(look.width, writer.width * 10) / 10 if look.width else None
        picture = add_picture(writer, str(path), min(asked or natural[0] / 10, writer.width), alt)
    else:
        logger.warning("Image file not found, its alt text is shown instead: %s", source)
        paragraph = writer.body.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        plain(writer, paragraph, f"[{alt or source}]", italic=True, role="muted")
        picture = paragraph
    if target := writer.numbers.get(attributes.id):
        caption(writer, str(attributes.values.get("caption", "")), target=target, anchor=picture)
    elif attributes.values.get("caption"):
        plain(writer, writer.body.add_paragraph(style="Caption"), str(attributes.values["caption"]))


# removes an unused leading paragraph from a table cell
def drop_empty_first(cell):
    first = cell.paragraphs[0]
    if not first.text and len(cell.paragraphs) > 1 and not first._p.xpath(".//w:drawing"):
        first._p.getparent().remove(first._p)


# renders a code fence as text, chart, diagram, or code
def add_fence(writer, language, content):
    settings = settings_from(language[language.find("{"):]) if "{" in language else {}
    ident = parse_attributes(language[language.find("{"):]).id if "{" in language else ""
    language = language.split("{")[0].strip()
    if language in ("", "text", "plain", "plaintext") and sum(content.count(mark) for mark in BOX_DRAWING) >= 6:
        add_code(writer, content, 8.5)
        return
    if language == "chart":
        add_chart(writer, content, settings, ident)
    elif language == "mermaid":
        add_diagram(writer, content, ident)
    elif language.split()[:1] == ["infographic"]:
        syntax = f"{language}\n{content}" if " " in language else content
        path = render_infographic(syntax, writer.theme)
        if path:
            add_picture(writer, str(path), writer.width, "Infographic")
        else:
            for line in syntax.splitlines():
                if line.strip().startswith("- label "):
                    paragraph = writer.body.add_paragraph()
                    plain(writer, paragraph, "• " + line.strip()[8:], role="ink")
    else:
        add_code(writer, content)


# renders chart data as an image in the Word document
def add_chart(writer, content, settings, ident=""):
    data = chart_data(content)
    if not data:
        logger.warning("Chart skipped: invalid JSON, unknown type, no values, or a value count that differs from the labels")
        return
    title = str(data.pop("title", "") or "")
    shades = [writer.tint("mood", 0.55), writer.theme.rgb("mood"), writer.theme.rgb("night"), writer.theme.rgb("muted")]
    data["colors"] = (["#%02x%02x%02x" % tuple(shade) for shade in shades] if len(data["datasets"]) > 1 and data["type"] not in ("pie", "donut")
                      else ["#" + writer.theme.colors[role].lstrip("#") for role in ("mood", "second", "muted", "primary", "success", "danger")])
    data["background"], data["font"] = "#ffffff", str(writer.theme.fonts["body"])
    width = writer.width * (0.75 if settings.get("size") == "half" else 1.0)
    try:
        image = render_chart(data, width_inches=width / 2.54, height_inches=width * 0.5 / 2.54, dpi=200)
    except Exception as error:
        logger.warning("Chart skipped: %s", type(error).__name__)
        return
    picture = add_picture(writer, io.BytesIO(image), width, f"Chart: {title or data['type']}")
    if target := writer.numbers.get(ident):
        caption(writer, target.text, target=target, anchor=picture)


# renders a diagram or falls back to a Word step table
def add_diagram(writer, content, ident=""):
    target = writer.numbers.get(ident)
    lines = content.strip().splitlines()
    titled = any(line.strip().startswith(("title ", "pie title ")) for line in lines)
    title = diagram_title(content) if titled else ""
    source = "\n".join("pie" if line.strip().startswith("pie title ") else line for line in lines if not line.strip().startswith("title "))
    steps = chain_steps(source)
    if len(steps) >= 3:
        step_table(writer, [(name, note) for name, note in steps])
        if target:
            caption(writer, target.text, target=target)
        elif title:
            caption(writer, title)
        return
    path = render_diagram(source, writer.theme)
    if not path:
        for line in diagram_as_text(source):
            paragraph = writer.body.add_paragraph()
            plain(writer, paragraph, "→ " + line)
        return
    with Image.open(path) as picture:
        natural = picture.width / ZOOM / 96 * 2.54
    picture = add_picture(writer, str(path), min(writer.width, max(natural, writer.width * 0.55)), f"Diagram: {title or 'diagram'}")
    if target:
        caption(writer, target.text, target=target, anchor=picture)
    elif title:
        caption(writer, title)


# adds monospaced code lines to the Word document
def add_code(writer, content, size=9.5):
    for line in content.rstrip("\n").splitlines() or [""]:
        paragraph = writer.body.add_paragraph(style="Code")
        run = paragraph.add_run(line or " ")
        run.font.size = Pt(size)


# adds a rendered equation or readable TeX fallback to Word
def add_equation(writer, tex, ident=""):
    target = writer.numbers.get(ident)
    try:
        image, (width_mm, _) = equation_png_bytes(mathtext_ready(tex), "#" + writer.theme.colors["ink"].lstrip("#"))
    except Exception as error:
        logger.warning("Equation shown as text: %s", type(error).__name__)
        paragraph = writer.body.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        plain(writer, paragraph, tex, italic=True)
        if target:
            bookmark(writer, paragraph, target.id)
            plain(writer, paragraph, f"    {target.mark}")
        return
    if target:
        paragraph = writer.body.add_paragraph()
        paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(writer.width / 2), WD_TAB_ALIGNMENT.CENTER)
        paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(writer.width), WD_TAB_ALIGNMENT.RIGHT)
        paragraph.add_run("\t").add_picture(image, width=Cm(min(writer.width * 0.8, width_mm / 10)))
        paragraph.add_run("\t" + target.mark)
        bookmark(writer, paragraph, target.id)
        return
    add_picture(writer, image, min(writer.width * 0.8, width_mm / 10), "Equation")


# adds a matched image, caption, and credit to Word
def add_figure(writer, query):
    found = writer.figures.get(query)
    if not found:
        logger.info("Figure skipped (no image found or images are off): %s", query[:60])
        return
    path, title, credit, source = found
    photo(writer, path, writer.width, writer.width / 1.5, title or query)
    caption(writer, title or query, credit, source)


# adds footnotes collected from the markdown to Word
def add_notes(writer):
    if not writer.notes:
        return
    writer.body.add_paragraph(style="Heading 2").add_run("Notes")
    for number, runs in enumerate(writer.notes, 1):
        paragraph = writer.body.add_paragraph(style="Note text")
        paragraph.paragraph_format.left_indent, paragraph.paragraph_format.first_line_indent = Cm(0.6), Cm(-0.6)
        plain(writer, paragraph, f"{number}\t", bold=True, role="mood")
        write_runs(writer, paragraph, runs)

