from dataclasses import replace

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

from markitdoc.markup.inline import literal, plain_text
from markitdoc.models.document import Block
from markitdoc.pptx.cards import card_pairs, card_preset, draw_cards, draw_panel, draw_takeaway, figure_cards, panel_fits
from markitdoc.pptx.deck import (
    Item,
    add_rect,
    add_textbox,
    body_height,
    body_top,
    comfortable_size,
    content_width,
    fitted_items,
    place_title,
    set_spacing,
    side_margin,
    side_text_width,
    slide_width,
    soft_white,
    split_to_fit,
    stack_height,
    text_width,
    white,
    write_column,
    write_items,
    write_text,
)
from markitdoc.pptx.diagrams import draw_flow as draw_flow_diagram
from markitdoc.pptx.flow.charts import place_chart
from markitdoc.pptx.flow.reader import Piece, break_piece, read_sections
from markitdoc.pptx.flow.tables import add_table, max_bullets, max_lead_above, table_pages
from markitdoc.pptx.flow.visuals import (
    code_chunks,
    code_layout,
    code_leading,
    code_padding,
    code_sizes,
    landscape_diagram,
    place_equation,
    place_figure,
    place_picture,
    prepared_visual,
    visual_box,
    visual_fallback,
)
from markitdoc.pptx.photos import add_image, full_bleed, half_bleed, overlay, photo_for, side_title
from markitdoc.utils.helpers import mono_font

opening_limit = 220


# yields a slide title and continuation titles
def title_stream(title, continued=False):
    if not continued:
        yield literal(title)
    while True:
        yield literal(title) + " (cont.)"


# counts the listed items in a slide group
def bullet_count(items):
    return sum(item.listed for item in items)


# moves a trailing subheading to the next slide group
def settled(groups):
    for position, group in enumerate(groups[:-1]):
        if group and group[-1].kind == "subheading" and len(group) > 1:
            groups[position + 1] = [group[-1]] + groups[position + 1]
            groups[position] = group[:-1]
    return groups


# draws text items across as many slides as needed
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


# checks whether lead text fits above a slide visual within its item limit
def lead_fits(deck, lead, width, height):
    return stack_height(deck, lead, width, comfortable_size) <= height and bullet_count(lead) <= max_bullets - 1


# attaches short paragraphs after equations when they fit
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


# checks whether a slide piece can join a photo gallery
def gallery_photo(deck, part):
    return isinstance(part, Piece) and part.kind == "figure" and part.data in deck.figures and not part.after


# groups nearby images and visuals for slide rendering
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


# renders slide content parts and batches adjacent photos into galleries
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


# draws several matched photos together on one slide
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


# draws a photo beside its related slide text
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


# chooses the slide renderer for a visual content piece
def draw_piece(deck, titles, lead, piece):
    drawer = {"table": draw_table, "code": draw_code, "steps": draw_steps}.get(piece.kind, draw_visual)
    drawer(deck, titles, lead, piece)


# renders a process visual with any fitting lead text
def draw_steps(deck, titles, lead, piece):
    lead_text = " ".join(plain_text(item.source) for item in lead)
    if lead and not lead_fits(deck, lead, text_width, 1.2):
        draw_text_slides(deck, titles, lead)
        lead_text = ""
    deck.draw_designed(deck, Block("process", {"title": next(titles), **({"lead": lead_text} if lead_text else {})}, piece.data))


# places lead text above a slide visual when it fits
def lead_above(deck, titles, lead):
    if not lead:
        return 0.0
    if stack_height(deck, lead, text_width, comfortable_size) <= max_lead_above and bullet_count(lead) <= 3:
        return stack_height(deck, lead, text_width, comfortable_size) + 0.25
    draw_text_slides(deck, titles, lead)
    return 0.0


# splits and draws a table across one or more slides
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


# splits and draws a code sample across slides
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


# renders a visual piece or falls back to readable slide text
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


# removes a short opening paragraph to use as a slide lead
def take_opening(parts):
    first = next((part for part in parts if isinstance(part, Item)), None)
    if first and first is parts[0] and first.kind == "paragraph" and len(first.source) <= opening_limit:
        parts.pop(0)
        return first.source
    return ""


# renders each parsed markdown section as slides
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


# draws a flowchart with positioned nodes and connectors
def draw_flow(deck, markdown, draw_designed):
    deck.draw_designed = draw_designed
    draw_sections(deck, read_sections(deck, markdown), draw_designed)
