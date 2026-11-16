import io
import math
import re
from dataclasses import replace

from PIL import Image
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_MARK
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

import logging
from markitdoc.visuals.charts import render_chart
from markitdoc.visuals.diagrams import diagram_as_text, render_diagram
from markitdoc.visuals.infographics import render_infographic
from markitdoc.models.document import Block
from markitdoc.visuals.equations import mathtext_ready, equation_png
from markitdoc.markup.inline import inline_maths, literal, plain_text
from markitdoc.pptx.diagrams import draw_flow as draw_flow_diagram, flow_graph
from markitdoc.pptx.cards import (card_pairs, card_preset, draw_panel, panel_fits, draw_cards, draw_takeaway,
                                  figure_cards)
from markitdoc.pptx.deck import (Item, add_rect, add_textbox, body_height, body_top, comfortable_size, content_width,
                                 fitted_items, place_title, set_spacing, side_margin, side_text_width, slide_width,
                                 soft_white, split_to_fit, stack_height, text_width, tint, visual_left, visual_width,
                                 white, write_column, write_items, write_text)
from markitdoc.pptx.photos import (add_image, contained, full_bleed, half_bleed, image_ratio, overlay, photo_for,
                                   side_title)
from markitdoc.utils.helpers import mono_font
from markitdoc.pptx.flow_reader import Piece, break_piece, read_sections
from markitdoc.pptx.tables import add_table, max_bullets, max_lead_above, table_pages

logger = logging.getLogger(__name__)
chart_scale, chart_dpi = 1.6, 200
equation_zoom = 2.0
caption_height, credit_height = 0.5, 0.3
code_sizes, code_leading, code_padding = (16, 14), 1.25, 0.25
opening_limit = 220
chart_roles = ("mood", "second", "muted", "night", "success", "danger")
native_charts = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "horizontal_bar": XL_CHART_TYPE.BAR_CLUSTERED, "stacked_bar": XL_CHART_TYPE.COLUMN_STACKED,
                 "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE, "donut": XL_CHART_TYPE.DOUGHNUT}


def title_stream(title, continued=False):
    if not continued:
        yield literal(title)
    while True:
        yield literal(title) + " (cont.)"


def bullet_count(items):
    return sum(item.listed for item in items)


def settled(groups):
    for position, group in enumerate(groups[:-1]):
        if group and group[-1].kind == "subheading" and len(group) > 1:
            groups[position + 1] = [group[-1]] + groups[position + 1]
            groups[position] = group[:-1]
    return groups


def draw_text_slides(deck, titles, items):
    def fits(group):
        return bullet_count(group) <= max_bullets and stack_height(deck, group, text_width, comfortable_size) <= body_height

    start = next((position for position, item in enumerate(items) if item.listed), len(items))
    end = len(items) - next((position for position, item in enumerate(reversed(items)) if item.listed), len(items))
    lead, middle, tail = items[:start], items[start:end], items[end:]
    pairs = card_pairs(middle) if middle else None
    tail_height = deck.text_height(" ".join(item.source for item in tail), content_width - 0.6, 16, "B") + 0.6 if tail else 0
    figures = figure_cards(pairs) if pairs else None
    if figures and tail_height < 1.4:
        lead_text = " ".join(plain_text(item.source) for item in lead)
        if lead_text and not lead_fits(deck, lead, text_width, 1.2):
            draw_text_slides(deck, titles, lead)
            lead_text = ""
        deck.draw_designed(deck, Block("figures", {"title": next(titles), **({"lead": lead_text} if lead_text else {}),
                                                   **({"body": " || ".join(item.source for item in tail)} if tail else {})}, figures))
        return
    lead_text = " ".join(item.source for item in lead)
    if pairs and lead and all(not item.listed for item in lead) and deck.last_cards != "panel" and tail_height < 1.4:
        room = body_height - tail_height
        if len(lead_text.split()) <= 45 and panel_fits(deck, lead_text, pairs, room):
            slide = deck.new_slide(next(titles))
            draw_panel(deck, slide, lead_text, pairs, body_top, room)
            if tail:
                draw_takeaway(deck, slide, tail, body_top + body_height)
            return
    lead_height = stack_height(deck, lead, text_width, comfortable_size) + 0.3 if lead else 0
    room = body_height - lead_height - tail_height
    preset = card_preset(deck, pairs, room) if pairs and lead_height < 1.6 and tail_height < 1.4 else None
    if preset:
        slide = deck.new_slide(next(titles))
        if lead:
            write_items(deck, slide, lead, side_margin, body_top, text_width, comfortable_size)
        draw_cards(deck, slide, pairs, body_top + lead_height, room, preset)
        if tail:
            draw_takeaway(deck, slide, tail, body_top + body_height)
        return
    for group in settled(split_to_fit(list(items), fits)):
        slide = deck.new_slide(next(titles))
        shown, size = fitted_items(deck, group, text_width, body_height, "Full text")
        write_items(deck, slide, shown, side_margin, body_top, text_width, size)


def lead_fits(deck, lead, width, height):
    return stack_height(deck, lead, width, comfortable_size) <= height and bullet_count(lead) <= max_bullets - 1


def with_trailing_text(deck, parts):
    result = []
    for part in parts:
        last = result[-1] if result else None
        if isinstance(part, Item) and isinstance(last, Piece) and last.kind == "equation" and len(last.after) < 3 and not last.caption:
            trial = last.after + (part,)
            if stack_height(deck, list(trial), text_width, comfortable_size) <= 1.0:
                result[-1] = replace(last, after=trial)
                continue
        result.append(part)
    return result


def gallery_photo(deck, part):
    return isinstance(part, Piece) and part.kind == "figure" and part.data in deck.figures and not part.after


def with_photo_text(deck, parts):
    result, index = [], 0
    while index < len(parts):
        part = parts[index]
        index += 1
        chart_like = isinstance(part, Piece) and part.kind in ("chart", "diagram") and not part.after
        if not chart_like and (not gallery_photo(deck, part) or (result and isinstance(result[-1], Item))):
            result.append(part)
            continue
        following = []
        while index < len(parts) and isinstance(parts[index], Item):
            following.append(parts[index])
            index += 1
        width, room = (text_width, 1.1) if chart_like else (slide_width / 2 - 1.2, 4.6)
        if following and stack_height(deck, following, width, comfortable_size) <= room:
            result.append(replace(part, after=tuple(following)))
        else:
            result += [part, *following]
    return result


def draw_parts(deck, titles, parts):
    pending, gallery = [], []

    def flush_gallery():
        if len(gallery) > 1:
            draw_gallery(deck, titles, list(gallery))
        elif gallery:
            draw_piece(deck, titles, [], gallery[0])
        gallery.clear()

    for part in with_trailing_text(deck, with_photo_text(deck, parts)):
        if gallery_photo(deck, part) and not pending:
            gallery.append(part)
            if len(gallery) == 3:
                flush_gallery()
            continue
        flush_gallery()
        if isinstance(part, Item):
            pending.append(part)
            continue
        if part is not break_piece:
            draw_piece(deck, titles, pending, part)
        elif pending:
            draw_text_slides(deck, titles, pending)
        pending = []
    flush_gallery()
    if pending:
        draw_text_slides(deck, titles, pending)


def draw_gallery(deck, titles, pieces):
    slide = deck.new_slide(next(titles))
    gap = 0.25
    width = (content_width - gap * (len(pieces) - 1)) / len(pieces)
    height = body_height - 0.5
    for index, piece in enumerate(pieces):
        path, caption, credit, _ = deck.figures[piece.data]
        left = side_margin + index * (width + gap)
        add_image(slide, photo_for(deck, path, width, height, overlay(deck, 0.0, 0.6, 0.85)), left, body_top, width, height, caption or "Photograph")
        write_text(deck, slide, literal(credit), left + 0.15, body_top + height - 0.3, width - 0.3, 9, white, align=PP_ALIGN.RIGHT, name="Credit")
        write_text(deck, slide, literal(caption), left, body_top + height + 0.1, width, 14, "muted", italic=True, name="Caption")


def draw_photo_slide(deck, titles, items, piece):
    path, caption, credit, _ = deck.figures[piece.data]
    title = next(titles)
    slide = deck.new_slide(title, footer=False, standard=False)
    if items:
        left, width = half_bleed(deck, slide, (path, caption, credit), caption or "Photograph")
        top = side_title(deck, slide, title, left, width)
        write_column(deck, slide, items, left, top, width, 6.45)
        write_text(deck, slide, literal(caption), left, 6.6, width, 14, "muted", italic=True, name="Caption")
        return
    full_bleed(deck, slide, (path, caption, credit), overlay(deck, 0.08, 0.86, 0.35), caption or "Photograph")
    place_title(deck, slide, title, white, side_margin, 4.6, content_width, 1.6, (40, 36, 32, 28), 2, MSO_ANCHOR.BOTTOM)
    write_text(deck, slide, literal(caption), side_margin, 6.35, content_width - 6.5, 16, soft_white, italic=True, name="Caption")


def draw_piece(deck, titles, lead, piece):
    drawer = {"table": draw_table, "code": draw_code, "steps": draw_steps}.get(piece.kind, draw_visual)
    drawer(deck, titles, lead, piece)


def draw_steps(deck, titles, lead, piece):
    lead_text = " ".join(plain_text(item.source) for item in lead)
    if lead and not lead_fits(deck, lead, text_width, 1.2):
        draw_text_slides(deck, titles, lead)
        lead_text = ""
    deck.draw_designed(deck, Block("process", {"title": next(titles), **({"lead": lead_text} if lead_text else {})}, piece.data))


def lead_above(deck, titles, lead):
    if not lead:
        return 0.0
    if stack_height(deck, lead, text_width, comfortable_size) <= max_lead_above and bullet_count(lead) <= 3:
        return stack_height(deck, lead, text_width, comfortable_size) + 0.25
    draw_text_slides(deck, titles, lead)
    return 0.0


def draw_table(deck, titles, lead, piece):
    lead_room = lead_above(deck, titles, lead)
    shown_lead = lead if lead_room else []
    caption_room = 0.4 if piece.caption else 0.0
    _, _, size, widths, header, pages, heights = table_pages(deck, piece.data, body_height - lead_room - caption_room)
    start = 0
    for number, rows in enumerate(pages):
        slide = deck.new_slide(next(titles))
        top = body_top
        if number == 0 and shown_lead:
            top += write_items(deck, slide, shown_lead, side_margin, top, text_width, comfortable_size) + 0.25
        if piece.caption:
            write_text(deck, slide, literal(piece.caption), side_margin, top, content_width, 14, "muted", italic=True, name="Caption")
            top += caption_room
        rows_heights = heights[start:start + len(rows)]
        spare = body_top + body_height - top - header - sum(rows_heights)
        rows_heights = [height + min(0.25, spare * 0.6 / len(rows)) for height in rows_heights] if spare > 0 else rows_heights
        add_table(deck, slide, piece.data, rows, widths, header, rows_heights, size, top)
        start += len(rows)


def code_layout(deck, lines, size, width):
    deck.measurer.set_font("Mono", "", size)
    capacity = max(10, int(width * 25.4 * 0.93 / deck.measurer.get_string_width("M")))
    return [max(1, math.ceil(len(line) / capacity)) for line in lines]


def code_chunks(deck, lines, size, room):
    counts = code_layout(deck, lines, size, content_width - 2 * code_padding)
    limit = max(1, int(room / (size * code_leading / 72)))
    chunks, current, used = [], [], 0
    for line, count in zip(lines, counts):
        if current and used + count > limit:
            chunks.append(current)
            current, used = [], 0
        current.append(line)
        used += count
    chunks.append(current)
    return chunks, counts, limit


def draw_code(deck, titles, lead, piece):
    lead_room = lead_above(deck, titles, lead)
    lines = piece.data.expandtabs(4).split("\n")
    room = body_height - lead_room - 2 * code_padding
    size = next((size for size in code_sizes if len(code_chunks(deck, lines, size, room)[0]) == 1), code_sizes[-1])
    chunks, _, _ = code_chunks(deck, lines, size, room)
    for number, chunk in enumerate(chunks):
        slide = deck.new_slide(next(titles))
        top = body_top
        if number == 0 and lead_room:
            top += write_items(deck, slide, lead, side_margin, top, text_width, comfortable_size) + 0.25
        used = sum(code_layout(deck, chunk, size, content_width - 2 * code_padding)) * size * code_leading / 72
        add_rect(deck, slide, side_margin, top, content_width, used + 2 * code_padding, "surface", "Code panel")
        frame = add_textbox(slide, side_margin + code_padding, top + code_padding, content_width - 2 * code_padding, used, "Code").text_frame
        for position, line in enumerate(chunk):
            paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
            set_spacing(paragraph, size, code_leading, 0)
            run = paragraph.add_run()
            run.text = line
            run.font.name, run.font.size, run.font.color.rgb = mono_font, Pt(size), deck.color("ink")


def chart_png(deck, data, width, height):
    data = {**data, "colors": ["#" + deck.theme.colors[role].lstrip("#") for role in ("mood", "second", "muted", "primary", "success", "danger")],
            "background": "#" + deck.theme.colors["paper"].lstrip("#"), "font": str(deck.theme.fonts["body"])}
    return io.BytesIO(render_chart(data, width_inches=width / chart_scale, height_inches=height / chart_scale, dpi=chart_dpi))


def landscape_diagram(deck, source):
    path = render_diagram(source, deck.theme)
    direction = re.match(r"\s*(flowchart|graph)\s+(TB|TD|BT|LR|RL)\b", source)
    if not path or not direction:
        return path
    turned = render_diagram(source[:direction.start(2)] + ("LR" if direction.group(2) in ("TB", "TD", "BT") else "TB")
                            + source[direction.end(2):], deck.theme)
    return max((path, turned) if turned else (path,), key=lambda option: diagram_scale(option))


def diagram_scale(path):
    with Image.open(path) as picture:
        return min(content_width / picture.width, (body_height - 0.4) / picture.height)


def infographic_items(syntax):
    items, current = [], None
    for line in syntax.splitlines():
        stripped = line.strip()
        if stripped.startswith("- label "):
            current = [stripped[8:], ""]
            items.append(current)
        elif stripped.startswith("desc ") and current:
            current[1] = stripped[5:]
    return [Item(f"**{label}**" + (f" — {description}" if description else ""), "bullet") for label, description in items]


def visual_box(side, width_limit=None):
    if side:
        return visual_left, body_top, visual_width, body_height
    width = width_limit or content_width
    return (slide_width - width) / 2, body_top, width, body_height


def place_chart(deck, slide, piece, box):
    data = piece.data
    if data["type"] == "waterfall":
        place_waterfall(deck, slide, data, box)
        return
    kind = native_charts.get(data["type"])
    if kind is None:
        left, top, width, height = box
        add_image(slide, chart_png(deck, data, width, height), left, top, width, height, f"Chart: {data.get('title') or data['type']}")
        return
    values = CategoryChartData()
    values.categories = [str(label) for label in data.get("labels") or range(1, len(data["datasets"][0]["values"]) + 1)]
    for number, dataset in enumerate(data["datasets"], 1):
        values.add_series(str(dataset.get("label") or f"Series {number}"), [float(value) for value in dataset["values"]])
    left, top, width, height = box
    graphic = slide.shapes.add_chart(kind, Inches(left), Inches(top), Inches(width), Inches(height), values)
    graphic.name = "Chart"
    style_chart(deck, graphic.chart, data, kind in (XL_CHART_TYPE.PIE, XL_CHART_TYPE.DOUGHNUT), deck.section_title)


def waterfall_steps(data):
    labels = [str(label) for label in data.get("labels") or []]
    values = [float(value) for value in data["datasets"][0]["values"]]
    if not values:
        return []
    steps, running = [(labels[0] if labels else "Start", 0.0, values[0], "total")], values[0]
    for label, value in zip(labels[1:] or [f"Step {n}" for n in range(1, len(values))], values[1:]):
        steps.append((label, running if value >= 0 else running + value, abs(value), "up" if value >= 0 else "down"))
        running += value
    if data.get("total"):
        steps.append((str(data["total"]), 0.0, running, "total"))
    return steps


def place_waterfall(deck, slide, data, box):
    steps = waterfall_steps(data)
    values = CategoryChartData()
    values.categories = [label for label, _, _, _ in steps]
    values.add_series("Base", [base for _, base, _, _ in steps])
    for kind in ("total", "up", "down"):
        values.add_series(kind, [size if step == kind else 0 for _, _, size, step in steps])
    left, top, width, height = box
    graphic = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, Inches(left), Inches(top), Inches(width), Inches(height), values)
    graphic.name = "Chart"
    chart = graphic.chart
    chart.font.size, chart.font.name = Pt(13), deck.body_font
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.gap_width, plot.overlap = 45, 100
    colors = {"total": deck.color("night"), "up": deck.color("success"), "down": deck.color("danger")}
    for series in chart.series:
        if series.name == "Base":
            series.format.fill.background()
            series.format.line.fill.background()
            continue
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = colors[series.name]
        for index, (_, _, size, step) in enumerate(steps):
            if step == series.name and size:
                label = series.points[index].data_label
                label.has_text_frame = True
                sign = "+" if step == "up" else "−" if step == "down" else ""
                label.text_frame.text = f"{sign}{size:,.10g}"
                label.position = XL_LABEL_POSITION.INSIDE_BASE if step == "total" else XL_LABEL_POSITION.CENTER
                font = label.text_frame.paragraphs[0].runs[0].font
                font.size, font.bold, font.name = Pt(14 if step == "total" else 13), True, deck.body_font
                font.color.rgb = deck.color(white)
    value_axis, category_axis = chart.value_axis, chart.category_axis
    value_axis.visible, value_axis.has_major_gridlines = False, False
    category_axis.format.line.color.rgb = deck.color("rule")
    category_axis.tick_labels.font.size = Pt(13)
    category_axis.tick_labels.font.color.rgb = deck.color("body")
    category_axis.major_tick_mark = XL_TICK_MARK.NONE


def style_chart(deck, chart, data, round_chart, slide_title=""):
    colors = [deck.color(role) for role in chart_roles]
    many = len(data["datasets"]) > 1
    if many and not round_chart:
        colors = [deck.color(tint(deck, "mood", 0.62)), deck.color("mood"), deck.color("night"), deck.color("muted")]
    chart.font.size, chart.font.name = Pt(13), deck.body_font
    chart.font.color.rgb = deck.color("body")
    chart.has_title = bool(data.get("title")) and plain_text(str(data["title"])).lower() not in plain_text(slide_title).lower()
    if chart.has_title:
        chart.chart_title.text_frame.text = plain_text(str(data["title"]))
        title_font = chart.chart_title.text_frame.paragraphs[0].font
        title_font.size, title_font.bold, title_font.name = Pt(16), True, deck.body_font
        title_font.color.rgb = deck.color("ink")
    line_chart = data["type"] == "line"
    chart.has_legend = (many and not line_chart) or round_chart
    if chart.has_legend:
        chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.TOP if not round_chart else XL_LEGEND_POSITION.BOTTOM, False
        chart.legend.font.size = Pt(13)
        chart.legend.font.color.rgb = deck.color("body")
    plot = chart.plots[0]
    plot.has_data_labels = not line_chart
    if plot.has_data_labels:
        labels = plot.data_labels
        labels.font.size, labels.number_format, labels.number_format_is_linked = Pt(13), "#,##0.##", False
        labels.font.color.rgb = deck.color("ink")
        if data["type"] == "stacked_bar":
            labels.position = XL_LABEL_POSITION.CENTER
            labels.font.color.rgb = deck.color(white)
        elif not round_chart:
            labels.position = XL_LABEL_POSITION.OUTSIDE_END
    if round_chart:
        labels.show_value, labels.show_percentage, labels.number_format = False, True, "0%"
        labels.font.color.rgb, labels.font.bold = deck.color(white), True
        donut_colors = [deck.color(tint(deck, "mood", share)) for share in (0.0, 0.3, 0.5, 0.65, 0.78, 0.88)]
        for index, point in enumerate(chart.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = donut_colors[index % len(donut_colors)] if data["type"] == "donut" else colors[index % len(colors)]
            point.format.line.color.rgb, point.format.line.width = deck.color("paper"), Pt(2)
        hole = plot._element.find(qn("c:holeSize"))
        if hole is not None:
            hole.set("val", "62")
        return
    if not line_chart:
        plot.gap_width = 60
        if many:
            plot.overlap = -12
    for index, series in enumerate(chart.series):
        if line_chart:
            color = colors[index % len(colors)] if many else deck.color("mood")
            series.format.line.color.rgb, series.format.line.width = color, Pt(3.25)
            series.smooth = False
            series.marker.style = XL_MARKER_STYLE.NONE
            last = series.points[len(data["datasets"][index]["values"]) - 1]
            last.marker.style, last.marker.size = XL_MARKER_STYLE.CIRCLE, 9
            last.marker.format.fill.solid()
            last.marker.format.fill.fore_color.rgb = color
            last.marker.format.line.color.rgb = color
            label = last.data_label
            label.position = XL_LABEL_POSITION.RIGHT
            label.has_text_frame = True
            name = str(data["datasets"][index].get("label") or "") if many else ""
            value = data["datasets"][index]["values"][-1]
            label.text_frame.text = f"{value:,.10g}" + (f"  {name}" if name else "")
            font = label.text_frame.paragraphs[0].runs[0].font
            font.size, font.bold, font.name = Pt(13), True, deck.body_font
            font.color.rgb = color
        else:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = colors[index % len(colors)] if many else deck.color(tint(deck, "mood", 0.45))
            if not many:
                largest = max(range(len(data["datasets"][0]["values"])), key=lambda position: data["datasets"][0]["values"][position])
                point = series.points[largest]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = deck.color("mood")
    value_axis, category_axis = chart.value_axis, chart.category_axis
    value_axis.has_major_gridlines = data["type"] == "line"
    if value_axis.has_major_gridlines:
        value_axis.major_gridlines.format.line.color.rgb = deck.color("rule")
    value_axis.visible = data["type"] == "line"
    value_axis.format.line.fill.background()
    value_axis.tick_labels.font.size = Pt(12)
    value_axis.tick_labels.font.color.rgb = deck.color("muted")
    category_axis.format.line.color.rgb = deck.color("rule")
    category_axis.tick_labels.font.size = Pt(13)
    category_axis.tick_labels.font.color.rgb = deck.color("body")
    category_axis.has_major_gridlines = False
    category_axis.major_tick_mark = value_axis.major_tick_mark = XL_TICK_MARK.NONE
    if data["type"] == "horizontal_bar":
        category_axis.reverse_order = True


def place_picture(deck, slide, path, box, alt, caption=""):
    left, top, width, height = box
    room = height - (caption_height if caption else 0)
    add_image(slide, str(path), *contained(image_ratio(path), left, top, width, room), alt)
    if caption:
        write_text(deck, slide, literal(caption), left, top + room + 0.1, width, 14, "muted", italic=True, align=PP_ALIGN.CENTER, name="Caption")


def place_equation(deck, slide, piece, box):
    left, top, width, height = box
    stream, (natural_width, natural_height) = equation_png(deck, piece.data)
    scale = min(equation_zoom, width * 0.9 / (natural_width / 25.4), height * 0.8 / (natural_height / 25.4))
    drawn_width, drawn_height = natural_width / 25.4 * scale, natural_height / 25.4 * scale
    add_image(slide, stream, left + (width - drawn_width) / 2, top + (height - drawn_height) / 2, drawn_width, drawn_height,
              f"Equation: {piece.data}")


def place_figure(deck, slide, piece, box):
    path, caption, credit, _ = deck.figures[piece.data]
    left, top, width, height = box
    photo_height = height - caption_height - credit_height
    add_image(slide, photo_for(deck, path, width, photo_height), left, top, width, photo_height, caption or "Photograph")
    write_text(deck, slide, literal(caption), left, top + photo_height + 0.08, width, 14, "muted", italic=True, name="Caption")
    write_text(deck, slide, literal(credit), left, top + photo_height + caption_height, width, 10, "muted", name="Credit")


def prepared_visual(deck, piece):
    if piece.kind == "figure":
        return piece if piece.data in deck.figures else None
    if piece.kind == "diagram":
        graph = flow_graph(piece.data)
        if graph:
            return Piece("flow", graph, piece.caption)
        path = landscape_diagram(deck, piece.data)
        return Piece("picture", path, piece.caption) if path else None
    if piece.kind == "infographic":
        path = render_infographic(piece.data, deck.theme)
        return Piece("picture", path) if path else None
    if piece.kind == "equation":
        try:
            equation_png(deck, piece.data)
        except Exception as error:
            logger.warning("Equation shown as text: %s", type(error).__name__)
            return None
    return piece


def visual_fallback(deck, piece):
    if piece.kind == "diagram":
        lines = diagram_as_text(piece.data)
        return [Item(line, "bullet") for line in lines] or [Item(piece.data.strip(), "paragraph")]
    if piece.kind == "infographic":
        return infographic_items(piece.data)
    if piece.kind == "equation":
        return [Item(literal(inline_maths(mathtext_ready(piece.data))))]
    return []


def draw_visual(deck, titles, lead, piece):
    visual = prepared_visual(deck, piece)
    if visual is None:
        draw_text_slides(deck, titles, list(lead) + visual_fallback(deck, piece) + list(piece.after))
        return
    if visual.kind == "figure" and visual.data in deck.figures:
        draw_photo_slide(deck, titles, list(lead) + list(visual.after), visual)
        return
    figure = visual.kind == "figure"
    above = visual.kind in ("equation", "flow") or (visual.kind == "chart" and visual.data["type"] == "waterfall"
                                                     and len(visual.data["datasets"][0]["values"]) > 4)
    side, room, shown = False, 0.0, []
    if above:
        room = lead_above(deck, titles, lead)
        shown = lead if room else []
    else:
        side = bool(lead) and lead_fits(deck, lead, side_text_width, body_height)
        shown = lead if side else []
        if lead and not side:
            draw_text_slides(deck, titles, lead)
    slide = deck.new_slide(next(titles))
    top = body_top
    if side:
        items, size = fitted_items(deck, list(shown), side_text_width, body_height, "Full text")
        write_items(deck, slide, items, side_margin, body_top, side_text_width, size)
    elif room:
        top += write_items(deck, slide, shown, side_margin, body_top, text_width, comfortable_size) + 0.25
    box = visual_box(side, 8.4 if figure else None)
    below = stack_height(deck, list(visual.after), text_width, comfortable_size) + 0.2 if visual.after else 0.0
    box = (box[0], top, box[2], body_top + body_height - top - below)
    if visual.after:
        write_items(deck, slide, list(visual.after), side_margin, box[1] + box[3] + 0.1, text_width, comfortable_size)
    if visual.kind == "flow" and draw_flow_diagram(deck, slide, visual.data, (box[0], box[1] + 0.15, box[2], box[3] - 0.3)):
        return
    if visual.kind == "flow":
        visual = Piece("picture", landscape_diagram(deck, piece.data), piece.caption)
    {"chart": place_chart, "equation": place_equation, "figure": place_figure}.get(
        visual.kind, lambda deck, slide, piece, box: place_picture(deck, slide, piece.data, box, f"Diagram: {piece.caption or 'diagram'}",
                                                                   piece.caption))(deck, slide, visual, box)


def take_opening(parts):
    first = next((part for part in parts if isinstance(part, Item)), None)
    if first and first is parts[0] and first.kind == "paragraph" and len(first.source) <= opening_limit:
        parts.pop(0)
        return first.source
    return ""


def draw_sections(deck, sections, draw_designed):
    for section in sections:
        parts = list(section.parts)
        continued = not section.title and bool(deck.section_title)
        if section.title:
            deck.section_title = section.title
        title = deck.section_title or deck.title or "Overview"
        if section.level == 1 and section.title:
            opening = take_opening(parts)
            layout = "cover" if deck.slide_count == 0 else "divider"
            slots = {"title": literal(section.title), **({"subtitle" if layout == "cover" else "lead": opening} if opening else {})}
            draw_designed(deck, Block(layout, slots))
        elif section.title and not parts:
            draw_designed(deck, Block("divider", {"title": literal(section.title)}))
        draw_parts(deck, title_stream(title, continued), parts)


def draw_flow(deck, markdown, draw_designed):
    deck.draw_designed = draw_designed
    draw_sections(deck, read_sections(deck, markdown), draw_designed)
