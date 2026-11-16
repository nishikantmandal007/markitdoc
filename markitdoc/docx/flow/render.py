import io
import logging
import re

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt
from PIL import Image

from markitdoc.docx.flow.lists import add_list_item, new_list
from markitdoc.docx.flow.tables import add_table, step_table
from markitdoc.docx.styles import border_bottom, cell_borders, cell_fill, cell_margins, new_table
from markitdoc.docx.writer import (
    LIST_FORMATS,
    add_picture,
    bookmark,
    caption,
    first_paragraph,
    photo,
    plain,
    start_on_new_page,
    write_runs,
)
from markitdoc.markup.elements import (
    CALLOUT_KINDS,
    TABLE_STYLES,
    chart_data,
    closing_index,
    element_settings,
    settings_from,
    without_display_maths,
)
from markitdoc.markup.inline import ANCHOR, Run, inline_runs, parser
from markitdoc.visuals.charts import render_chart
from markitdoc.visuals.diagrams import ZOOM, chain_steps, diagram_as_text, diagram_title, render_diagram
from markitdoc.visuals.equations import equation_png_bytes, mathtext_ready
from markitdoc.visuals.infographics import render_infographic

logger = logging.getLogger(__name__)
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
        if kind == "footnote_block_open":
            end = closing_index(tokens, index, "footnote_block_open", "footnote_block_close")
            writer.notes += [inline_runs(item, writer.targets) for item in tokens[index:end] if item.type == "inline"]
            index = end + 1
            continue
        if kind.startswith("container_") and kind.endswith("_open"):
            name = kind[len("container_"):-len("_open")]
            end = closing_index(tokens, index, kind, f"container_{name}_close")
            add_container(writer, name, tokens[index + 1:end])
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
    found = ANCHOR.search(inline.content)
    runs = inline_runs(inline, writer.targets)
    if found and runs:
        runs[-1] = Run(ANCHOR.sub("", runs[-1].text), runs[-1].bold, runs[-1].italic)
    if level == 1 and writer.skip_title and "".join(run.text for run in runs).strip() == writer.skip_title:
        writer.skip_title = ""
        return None
    if level == 1 and not writer.titled:
        writer.titled = True
        paragraph = writer.body.add_paragraph(style="Title")
        write_runs(writer, paragraph, runs)
        return paragraph
    if writer.numbered and 2 <= level <= 4:
        writer.headings[level - 1] += 1
        writer.headings[level:] = [0] * (4 - level)
        runs = [Run(".".join(str(number) for number in writer.headings[1:level]) + "   ")] + runs
    paragraph = writer.body.add_paragraph(style=f"Heading {min(level, 4)}")
    start_on_new_page(writer, paragraph)
    write_runs(writer, paragraph, runs)
    if found:
        bookmark(writer, paragraph, found.group(1))
    return paragraph


# renders a paragraph token with its settings and inline content
def add_paragraph_token(writer, tokens, index, stack, pending):
    inline, equations = without_display_maths(tokens[index + 1])
    content = inline.content.strip()
    settings = re.search(r"\n?\{([^{}]*)\}\s*$", content)
    style = settings_from(settings.group(1)).get("class", "") if settings else ""
    if settings and not content[:settings.start()].strip():
        for equation in equations:
            add_equation(writer, equation)
        return style
    picture = next((child for child in inline.children or [] if child.type == "image"), None)
    if picture is not None:
        add_figure(writer, picture.content or str(picture.attrs.get("alt", "")))
        return ""
    runs = inline_runs(inline, writer.targets)
    if settings and runs:
        runs[-1] = Run(re.sub(r"\s*\{[^{}]*\}\s*$", "", runs[-1].text), runs[-1].bold, runs[-1].italic, role=runs[-1].role)
    text = "".join(run.text for run in runs).strip()
    if content == "+++":
        writer.break_next = True
        return ""
    if text.startswith("Table:") and not stack:
        writer.pending_caption = text[6:].strip()
        return ""
    if stack:
        add_list_item(writer, stack, runs)
    elif text:
        paragraph = writer.body.add_paragraph(style="Lead" if style == "lead" else None)
        if style in ALIGNMENTS:
            paragraph.alignment = ALIGNMENTS[style]
        write_runs(writer, paragraph, runs)
    for equation in equations:
        add_equation(writer, equation)
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
    for token in inlines:
        paragraph = writer.body.add_paragraph(style="Quote")
        write_runs(writer, paragraph, inline_runs(token, writer.targets))


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
def add_container(writer, name, tokens):
    if name == "columns":
        children = top_level_blocks(tokens)
        half = (len(children) + 1) // 2
        table = new_table(writer, 1, 2, [writer.width / 2 - 0.2, writer.width / 2 + 0.2])
        for column, part in enumerate((children[:half], children[half:])):
            cell = table.cell(0, column)
            cell_margins(cell, 0, 0.1 if column else 0, 0)
            with writer.inside(cell, writer.width / 2 - 0.4):
                render_tokens(writer, [token for block in part for token in block])
            drop_empty_first(cell)
        return
    table = callout_table(writer, writer.hex("surface"), writer.hex("mood"))
    cell = table.cell(0, 0)
    with writer.inside(cell, writer.width - 0.7):
        render_tokens(writer, tokens)
    drop_empty_first(cell)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


# removes an unused leading paragraph from a table cell
def drop_empty_first(cell):
    first = cell.paragraphs[0]
    if not first.text and len(cell.paragraphs) > 1 and not first._p.xpath(".//w:drawing"):
        first._p.getparent().remove(first._p)


# groups tokens into top-level markdown blocks
def top_level_blocks(tokens):
    blocks, current = [], []
    for token in tokens:
        current.append(token)
        if token.level == 0 and (token.type.endswith("_close") or token.type in ("fence", "math_block", "hr", "code_block")):
            blocks.append(current)
            current = []
    return blocks + ([current] if current else [])


# renders a code fence as text, chart, diagram, or code
def add_fence(writer, language, content):
    settings = settings_from(language[language.find("{"):]) if "{" in language else {}
    language = language.split("{")[0].strip()
    if language in ("", "text", "plain", "plaintext") and sum(content.count(mark) for mark in BOX_DRAWING) >= 6:
        add_code(writer, content, 8.5)
        return
    if language == "chart":
        add_chart(writer, content, settings)
    elif language == "mermaid":
        add_diagram(writer, content)
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
def add_chart(writer, content, settings):
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
    add_picture(writer, io.BytesIO(image), width, f"Chart: {title or data['type']}")
    if title:
        caption(writer, title)


# renders a diagram or falls back to a Word step table
def add_diagram(writer, content):
    lines = content.strip().splitlines()
    titled = any(line.strip().startswith(("title ", "pie title ")) for line in lines)
    title = diagram_title(content) if titled else ""
    source = "\n".join("pie" if line.strip().startswith("pie title ") else line for line in lines if not line.strip().startswith("title "))
    steps = chain_steps(source)
    if len(steps) >= 3:
        step_table(writer, [(name, note) for name, note in steps])
        if title:
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
    add_picture(writer, str(path), min(writer.width, max(natural, writer.width * 0.55)), f"Diagram: {title or 'diagram'}")
    if title:
        caption(writer, title)


# adds monospaced code lines to the Word document
def add_code(writer, content, size=9.5):
    for line in content.rstrip("\n").splitlines() or [""]:
        paragraph = writer.body.add_paragraph(style="Code")
        run = paragraph.add_run(line or " ")
        run.font.size = Pt(size)


# adds a rendered equation or readable TeX fallback to Word
def add_equation(writer, tex):
    try:
        image, (width_mm, _) = equation_png_bytes(mathtext_ready(tex), "#" + writer.theme.colors["ink"].lstrip("#"))
    except Exception as error:
        logger.warning("Equation shown as text: %s", type(error).__name__)
        paragraph = writer.body.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        plain(writer, paragraph, tex, italic=True)
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

