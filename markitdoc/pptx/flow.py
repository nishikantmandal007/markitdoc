import math
import re
from dataclasses import replace

from PIL import Image
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

import logging
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
                                 soft_white, split_to_fit, stack_height, text_width, visual_left, visual_width, white,
                                 write_column, write_items, write_text)
from markitdoc.pptx.photos import (add_image, contained, full_bleed, half_bleed, image_ratio, overlay, photo_for,
                                   side_title)
from markitdoc.utils.helpers import mono_font
from markitdoc.pptx.flow_reader import Piece, break_piece, read_sections
from markitdoc.pptx.tables import add_table, max_bullets, max_lead_above, table_pages
from markitdoc.pptx.charts import place_chart

logger = logging.getLogger(__name__)
equation_zoom = 2.0
caption_height, credit_height = 0.5, 0.3
code_sizes, code_leading, code_padding = (16, 14), 1.25, 0.25
opening_limit = 220


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
