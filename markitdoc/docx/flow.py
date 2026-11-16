import io
import re
from functools import lru_cache

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import Image, ImageDraw

import logging
from markitdoc.visuals.charts import render_chart
from markitdoc.visuals.diagrams import chain_steps, diagram_as_text, diagram_title, render_diagram, zoom
from markitdoc.visuals.infographics import render_infographic
from markitdoc.docx.document import (add_picture, bookmark, bullet_marks, caption, first_paragraph, landscape_section,
                                     list_formats, page_break, photo, plain, start_on_new_page, white, write_runs)
from markitdoc.docx.styles import (border_bottom, cell_borders, cell_fill, cell_margins, keep_together, new_table,
                                   repeat_header)
from markitdoc.markup.elements import (callout_kinds, chart_data, closing_index, column_alignments, element_settings,
                                       settings_from, table_styles, totals_row, without_display_maths, rating_level,
                                       signed_number, table_marks)
from markitdoc.visuals.equations import mathtext_ready, equation_png_bytes
from markitdoc.markup.inline import Run, anchor, inline_runs, parser

logger = logging.getLogger(__name__)
alignments = {"center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}
numeric_cell = re.compile(r"^[\s$€£¥+\-−~≈<>]*\d[\d.,\s]*(%|[kKmMbB]|bn|x|pts?|bps)?\s*$")
box_drawing = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬"


def render_markdown(writer, markdown):
    tokens = parser.parse(markdown)
    for position, token in enumerate(tokens):
        if token.type == "heading_open":
            found = anchor.search(tokens[position + 1].content)
            if found:
                writer.targets.add(found.group(1))
    render_tokens(writer, tokens)


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
            scheme = pending if pending in list_formats else "decimal"
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
            add_table(writer, tokens[index:end], settings.get("class") if settings.get("class") in table_styles else "")
            index = end + 1 + (3 if settings.get("class") in table_styles else 0)
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


def add_heading(writer, level, inline):
    found = anchor.search(inline.content)
    runs = inline_runs(inline, writer.targets)
    if found and runs:
        runs[-1] = Run(anchor.sub("", runs[-1].text), runs[-1].bold, runs[-1].italic)
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
        if style in alignments:
            paragraph.alignment = alignments[style]
        write_runs(writer, paragraph, runs)
    for equation in equations:
        add_equation(writer, equation)
    return ""


def abstract_list(writer, ordered, scheme):
    key = (ordered, scheme)
    if key in writer.lists:
        return writer.lists[key]
    numbering = writer.document.part.numbering_part.element
    known = [int(item.get(qn("w:abstractNumId"))) for item in numbering.findall(qn("w:abstractNum"))]
    abstract_id = max(known, default=0) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "hybridMultilevel")
    abstract.append(multi)
    for level in range(4):
        abstract.append(list_level(writer, level, ordered, scheme))
    first_num = numbering.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        numbering.append(abstract)
    writer.lists[key] = abstract_id
    return abstract_id


def list_level(writer, level, ordered, scheme):
    item = OxmlElement("w:lvl")
    item.set(qn("w:ilvl"), str(level))
    values = [("w:start", "1"),
              ("w:numFmt", list_formats[scheme] if ordered else "bullet"),
              ("w:lvlText", (".".join(f"%{depth + 1}" for depth in range(level + 1)) + "." if scheme == "legal" else f"%{level + 1}.")
               if ordered else bullet_marks[level % 3]),
              ("w:lvlJc", "left")]
    for name, value in values:
        element = OxmlElement(name)
        element.set(qn("w:val"), value)
        item.append(element)
    paragraph = OxmlElement("w:pPr")
    indent = OxmlElement("w:ind")
    hang = 0.75 if scheme == "legal" and ordered else 0.55
    indent.set(qn("w:left"), str(int((0.55 + level * 0.6 + hang - 0.55) * 567 + 0.55 * 567)))
    indent.set(qn("w:hanging"), str(int(hang * 567)))
    paragraph.append(indent)
    item.append(paragraph)
    run = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), writer.hex("mood"))
    run.append(color)
    if ordered:
        run.append(OxmlElement("w:b"))
    item.append(run)
    return item


def new_list(writer, ordered, scheme, start):
    numbering = writer.document.part.numbering_part.element
    number = numbering.add_num(abstract_list(writer, ordered, scheme))
    if start != 1:
        override = number.add_lvlOverride(ilvl=0)
        override.add_startOverride(start)
    return {"id": number.numId, "depth": None, "fresh": False}


def add_list_item(writer, stack, runs):
    current = stack[-1]
    paragraph = writer.body.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(3)
    if current["fresh"]:
        properties = paragraph._p.get_or_add_pPr()
        numbering = OxmlElement("w:numPr")
        level, number = OxmlElement("w:ilvl"), OxmlElement("w:numId")
        level.set(qn("w:val"), str(min(len(stack) - 1, 3)))
        number.set(qn("w:val"), str(current["id"]))
        numbering.append(level)
        numbering.append(number)
        properties.append(numbering)
        current["fresh"] = False
    else:
        paragraph.paragraph_format.left_indent = Cm(0.55 + (len(stack) - 1) * 0.6 + 0.55)
    write_runs(writer, paragraph, runs)


def add_quote(writer, tokens):
    inlines = [token for token in tokens if token.type == "inline"]
    if not inlines:
        return
    first = inline_runs(inlines[0], writer.targets)
    label = first[0].text.strip().rstrip(":") if first and first[0].bold else ""
    if label in callout_kinds:
        runs_list = [inline_runs(token, writer.targets) for token in inlines]
        add_callout(writer, label, runs_list)
        return
    for token in inlines:
        paragraph = writer.body.add_paragraph(style="Quote")
        write_runs(writer, paragraph, inline_runs(token, writer.targets))


def add_callout(writer, label, runs_list, role="mood"):
    table = callout_table(writer, writer.hex(writer.tint(role, 0.9)), writer.hex(role))
    cell = table.cell(0, 0)
    for number, runs in enumerate(runs_list):
        paragraph = first_paragraph(cell) if number == 0 else cell.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(3)
        write_runs(writer, paragraph, runs, role="ink" if number == 0 else None)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


def callout_table(writer, fill, accent):
    table = new_table(writer, 1, 1, [writer.width])
    cell = table.cell(0, 0)
    cell_fill(cell, fill)
    cell_borders(cell, left=(accent, 24))
    cell_margins(cell, 0.22, 0.35, 0.18)
    return table


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


def drop_empty_first(cell):
    first = cell.paragraphs[0]
    if not first.text and len(cell.paragraphs) > 1 and not first._p.xpath(".//w:drawing"):
        first._p.getparent().remove(first._p)


def top_level_blocks(tokens):
    blocks, current = [], []
    for token in tokens:
        current.append(token)
        if token.level == 0 and (token.type.endswith("_close") or token.type in ("fence", "math_block", "hr", "code_block")):
            blocks.append(current)
            current = []
    return blocks + ([current] if current else [])


def table_cells(tokens):
    rows, row = [], None
    for token in tokens:
        if token.type == "tr_open":
            row = []
        elif token.type == "inline" and row is not None:
            row.append(token)
        elif token.type == "tr_close":
            rows.append(row)
            row = None
    return rows


def add_table(writer, tokens, style):
    rows = table_cells(tokens)
    if not rows:
        return
    header_text = ["".join(run.text for run in inline_runs(cell)) for cell in rows[0]]
    if len(rows) > 2 and re.fullmatch(r"\{[^{}]*\}", rows[-1][0].content.strip() if rows[-1] else "") and not any(
            cell.content.strip() for cell in rows[-1][1:]):
        style = settings_from(rows[-1][0].content.strip()[1:-1]).get("class", "") or style
        rows = rows[:-1]
    columns = len(rows[0])
    wide = columns > 8 and writer.body is writer.document
    width = landscape_section(writer, True) if wide else writer.width
    if writer.pending_caption:
        writer.table_count += 1
        paragraph = writer.body.add_paragraph(style="Caption")
        paragraph.paragraph_format.keep_with_next = True
        plain(writer, paragraph, f"Table {writer.table_count}. ", bold=True)
        plain(writer, paragraph, writer.pending_caption)
        writer.pending_caption = ""
    body_rows = [[cell.content for cell in row] for row in rows[1:]]
    numeric = [all(numeric_cell.match(row[column]) for row in body_rows if column < len(row) and row[column].strip()) and any(
        column < len(row) and row[column].strip() for row in body_rows) for column in range(columns)]
    rated = {column for column in range(1, columns) if body_rows and all(rating_level(row[column] if column < len(row) else "") is not None
                                                                          for row in body_rows)}
    brand = (writer.theme.brand or "").split()[:1]
    highlighted = {column for column, heading in enumerate(header_text) if column and brand and brand[0].lower() in heading.lower()}
    alignment = column_alignments(tokens)
    weights = [max(9, max(len(inline_runs_text(row[column])) if column < len(row) else 0 for row in rows)) for column in range(columns)]
    weights = [min(weight, 40) for weight in weights]
    widths = [width * weight / sum(weights) for weight in weights]
    table = new_table(writer, len(rows), columns, widths)
    repeat_header(table.rows[0])
    hairline = writer.hex(writer.tint("mood", 0.75))
    for row_index, row in enumerate(rows):
        header = row_index == 0
        last = row_index == len(rows) - 1
        total = last and row_index > 1 and totals_row.match(row[0].content if row else "")
        for column in range(columns):
            cell = table.cell(row_index, column)
            cell_margins(cell, 0.09, 0.18, 0.09)
            source = row[column] if column < len(row) else None
            fill = writer.hex("night") if header else writer.hex(writer.tint("mood", 0.9)) if column in highlighted else (
                writer.hex("surface") if style == "striped" and row_index % 2 == 0 else None)
            if fill:
                cell_fill(cell, fill)
            edge = (writer.hex("mood"), 10) if last or total else (hairline, 4)
            cell_borders(cell, top=(writer.hex("ink"), 8) if total else None, bottom=None if header else edge,
                         left=(hairline, 4) if style == "boxed" else None, right=(hairline, 4) if style == "boxed" else None)
            paragraph = first_paragraph(cell)
            align = alignment[column] if column < len(alignment) and alignment[column] else ("right" if numeric[column] and not header else "")
            paragraph.alignment = {"right": WD_ALIGN_PARAGRAPH.RIGHT, "center": WD_ALIGN_PARAGRAPH.CENTER}.get(str(align).lower(),
                                                                                                                WD_ALIGN_PARAGRAPH.LEFT)
            runs = inline_runs(source, writer.targets) if source is not None else []
            text = "".join(run.text for run in runs).strip()
            if not header and column in rated:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.add_run().add_picture(harvey_png(rating_level(text), writer.hex("mood")), width=Cm(0.42))
                continue
            mark = table_marks.get(text.lower()) if not header else None
            if mark:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                plain(writer, paragraph, mark[0], 11, mark[1], bold=True)
                continue
            signed = signed_number.match(text) if not header else None
            role = white if header else "mood" if column in highlighted else (
                "success" if signed.group(1) == "+" else "danger") if signed else "ink" if column == 0 and columns > 2 else None
            write_runs(writer, paragraph, runs, size=8.5 if columns > 6 else 9.5 if columns > 4 else 10, role=role,
                       bold=header or total or column in highlighted or (column == 0 and columns > 2))
    if len(rows) <= 7:
        keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)
    if wide:
        landscape_section(writer, False)


def inline_runs_text(token):
    return "".join(run.text for run in inline_runs(token))


@lru_cache(maxsize=None)
def harvey_png(level, color):
    size = 96
    picture = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(picture)
    rgb = tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))
    box = (6, 6, size - 6, size - 6)
    if level:
        draw.pieslice(box, -90, -90 + 90 * level, fill=rgb)
    draw.ellipse(box, outline=rgb, width=7)
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    return io.BytesIO(buffer.getvalue())


def add_fence(writer, language, content):
    settings = settings_from(language[language.find("{"):]) if "{" in language else {}
    language = language.split("{")[0].strip()
    if language in ("", "text", "plain", "plaintext") and sum(content.count(mark) for mark in box_drawing) >= 6:
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
        natural = picture.width / zoom / 96 * 2.54
    add_picture(writer, str(path), min(writer.width, max(natural, writer.width * 0.55)), f"Diagram: {title or 'diagram'}")
    if title:
        caption(writer, title)


def add_code(writer, content, size=9.5):
    for line in content.rstrip("\n").splitlines() or [""]:
        paragraph = writer.body.add_paragraph(style="Code")
        run = paragraph.add_run(line or " ")
        run.font.size = Pt(size)


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


def add_figure(writer, query):
    found = writer.figures.get(query)
    if not found:
        logger.info("Figure skipped (no image found or images are off): %s", query[:60])
        return
    path, title, credit, source = found
    photo(writer, path, writer.width, writer.width / 1.5, title or query)
    caption(writer, title or query, credit, source)


def step_table(writer, steps):
    table = new_table(writer, len(steps), 2, [1.4, writer.width - 1.4])
    for row, (title, detail) in enumerate(steps):
        number, text = table.cell(row, 0), table.cell(row, 1)
        cell_fill(number, writer.hex("mood"))
        cell_fill(text, writer.hex("surface"))
        for cell in (number, text):
            cell_borders(cell, bottom=("FFFFFF", 18))
            cell_margins(cell, 0.18, 0.25, 0.18)
        marker = first_paragraph(number)
        marker.alignment = WD_ALIGN_PARAGRAPH.CENTER
        plain(writer, marker, f"{row + 1:02d}", 13, white, bold=True)
        heading = first_paragraph(text)
        write_runs(writer, heading, inline_runs(parser.parseInline(title)[0], writer.targets), 11.5, "ink", bold=True)
        if detail:
            paragraph = text.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(0)
            write_runs(writer, paragraph, inline_runs(parser.parseInline(detail)[0], writer.targets), 10)
    keep_together(table)
    writer.body.add_paragraph().paragraph_format.space_after = Pt(2)


def add_notes(writer):
    if not writer.notes:
        return
    writer.body.add_paragraph(style="Heading 2").add_run("Notes")
    for number, runs in enumerate(writer.notes, 1):
        paragraph = writer.body.add_paragraph(style="Note text")
        paragraph.paragraph_format.left_indent, paragraph.paragraph_format.first_line_indent = Cm(0.6), Cm(-0.6)
        plain(writer, paragraph, f"{number}\t", bold=True, role="mood")
        write_runs(writer, paragraph, runs)

