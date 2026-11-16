from dataclasses import replace

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

from markitdoc.markup.inline import literal, plain_text
from markitdoc.models.document import Block
from markitdoc.pptx.cards import card_pairs, card_preset, draw_cards, draw_panel, draw_takeaway, figure_cards, panel_fits
from markitdoc.pptx.deck import (
    BODY_HEIGHT,
    BODY_TOP,
    COMFORTABLE_SIZE,
    CONTENT_WIDTH,
    SIDE_MARGIN,
    SIDE_TEXT_WIDTH,
    SLIDE_WIDTH,
    SOFT_WHITE,
    TEXT_WIDTH,
    WHITE,
    Item,
    add_rect,
    add_textbox,
    fitted_items,
    place_title,
    set_spacing,
    split_to_fit,
    stack_height,
    write_column,
    write_items,
    write_text,
)
from markitdoc.pptx.diagrams import draw_flow as draw_flow_diagram
from markitdoc.pptx.flow.charts import place_chart
from markitdoc.pptx.flow.reader import BREAK_PIECE, Piece, read_sections
from markitdoc.pptx.flow.tables import MAX_BULLETS, MAX_LEAD_ABOVE, add_table, table_pages
from markitdoc.pptx.flow.visuals import (
    CODE_LEADING,
    CODE_PADDING,
    CODE_SIZES,
    code_chunks,
    code_layout,
    landscape_diagram,
    place_equation,
    place_figure,
    place_picture,
    prepared_visual,
    visual_box,
    visual_fallback,
)
from markitdoc.pptx.photos import add_image, full_bleed, half_bleed, overlay, photo_for, side_title
from markitdoc.utils.helpers import MONO_FONT

OPENING_LIMIT = 220


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
        return bullet_count(group) <= MAX_BULLETS and stack_height(deck, group, TEXT_WIDTH, COMFORTABLE_SIZE) <= BODY_HEIGHT

    start = next((position for position, item in enumerate(items) if item.listed), len(items))
    end = len(items) - next((position for position, item in enumerate(reversed(items)) if item.listed), len(items))
    lead, middle, tail = items[:start], items[start:end], items[end:]
    pairs = card_pairs(middle) if middle else None
    tail_height = deck.text_height(" ".join(item.source for item in tail), CONTENT_WIDTH - 0.6, 16, "B") + 0.6 if tail else 0
    figures = figure_cards(pairs) if pairs else None
    if figures and tail_height < 1.4:
        lead_text = " ".join(plain_text(item.source) for item in lead)
        if lead_text and not lead_fits(deck, lead, TEXT_WIDTH, 1.2):
            draw_text_slides(deck, titles, lead)
            lead_text = ""
        deck.draw_designed(deck, Block("figures", {"title": next(titles), **({"lead": lead_text} if lead_text else {}),
                                                   **({"body": " || ".join(item.source for item in tail)} if tail else {})}, figures))
        return
    lead_text = " ".join(item.source for item in lead)
    if pairs and lead and all(not item.listed for item in lead) and deck.last_cards != "panel" and tail_height < 1.4:
        room = BODY_HEIGHT - tail_height
        if len(lead_text.split()) <= 45 and panel_fits(deck, lead_text, pairs, room):
            slide = deck.new_slide(next(titles))
            draw_panel(deck, slide, lead_text, pairs, BODY_TOP, room)
            if tail:
                draw_takeaway(deck, slide, tail, BODY_TOP + BODY_HEIGHT)
            return
    lead_height = stack_height(deck, lead, TEXT_WIDTH, COMFORTABLE_SIZE) + 0.3 if lead else 0
    room = BODY_HEIGHT - lead_height - tail_height
    preset = card_preset(deck, pairs, room) if pairs and lead_height < 1.6 and tail_height < 1.4 else None
    if preset:
        slide = deck.new_slide(next(titles))
        if lead:
            write_items(deck, slide, lead, SIDE_MARGIN, BODY_TOP, TEXT_WIDTH, COMFORTABLE_SIZE)
        draw_cards(deck, slide, pairs, BODY_TOP + lead_height, room, preset)
        if tail:
            draw_takeaway(deck, slide, tail, BODY_TOP + BODY_HEIGHT)
        return
    for group in settled(split_to_fit(list(items), fits)):
        slide = deck.new_slide(next(titles))
        shown, size = fitted_items(deck, group, TEXT_WIDTH, BODY_HEIGHT, "Full text")
        write_items(deck, slide, shown, SIDE_MARGIN, BODY_TOP, TEXT_WIDTH, size)


# checks whether lead text fits above a slide visual within its item limit
def lead_fits(deck, lead, width, height):
    return stack_height(deck, lead, width, COMFORTABLE_SIZE) <= height and bullet_count(lead) <= MAX_BULLETS - 1


# attaches short paragraphs after equations when they fit
def with_trailing_text(deck, parts):
    result = []
    for part in parts:
        last = result[-1] if result else None
        if isinstance(part, Item) and isinstance(last, Piece) and last.kind == "equation" and len(last.after) < 3 and not last.caption:
            trial = last.after + (part,)
            if stack_height(deck, list(trial), TEXT_WIDTH, COMFORTABLE_SIZE) <= 1.0:
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
        width, room = (TEXT_WIDTH, 1.1) if chart_like else (SLIDE_WIDTH / 2 - 1.2, 4.6)
        if following and stack_height(deck, following, width, COMFORTABLE_SIZE) <= room:
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
        if part is not BREAK_PIECE:
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
    width = (CONTENT_WIDTH - gap * (len(pieces) - 1)) / len(pieces)
    height = BODY_HEIGHT - 0.5
    for index, piece in enumerate(pieces):
        path, caption, credit, _ = deck.figures[piece.data]
        left = SIDE_MARGIN + index * (width + gap)
        add_image(slide, photo_for(deck, path, width, height, overlay(deck, 0.0, 0.6, 0.85)), left, BODY_TOP, width, height, caption or "Photograph")
        write_text(deck, slide, literal(credit), left + 0.15, BODY_TOP + height - 0.3, width - 0.3, 9, WHITE, align=PP_ALIGN.RIGHT, name="Credit")
        write_text(deck, slide, literal(caption), left, BODY_TOP + height + 0.1, width, 14, "muted", italic=True, name="Caption")


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
    place_title(deck, slide, title, WHITE, SIDE_MARGIN, 4.6, CONTENT_WIDTH, 1.6, (40, 36, 32, 28), 2, MSO_ANCHOR.BOTTOM)
    write_text(deck, slide, literal(caption), SIDE_MARGIN, 6.35, CONTENT_WIDTH - 6.5, 16, SOFT_WHITE, italic=True, name="Caption")


# chooses the slide renderer for a visual content piece
def draw_piece(deck, titles, lead, piece):
    drawer = {"table": draw_table, "code": draw_code, "steps": draw_steps}.get(piece.kind, draw_visual)
    drawer(deck, titles, lead, piece)


# renders a process visual with any fitting lead text
def draw_steps(deck, titles, lead, piece):
    lead_text = " ".join(plain_text(item.source) for item in lead)
    if lead and not lead_fits(deck, lead, TEXT_WIDTH, 1.2):
        draw_text_slides(deck, titles, lead)
        lead_text = ""
    deck.draw_designed(deck, Block("process", {"title": next(titles), **({"lead": lead_text} if lead_text else {})}, piece.data))


# places lead text above a slide visual when it fits
def lead_above(deck, titles, lead):
    if not lead:
        return 0.0
    if stack_height(deck, lead, TEXT_WIDTH, COMFORTABLE_SIZE) <= MAX_LEAD_ABOVE and bullet_count(lead) <= 3:
        return stack_height(deck, lead, TEXT_WIDTH, COMFORTABLE_SIZE) + 0.25
    draw_text_slides(deck, titles, lead)
    return 0.0


# splits and draws a table across one or more slides
def draw_table(deck, titles, lead, piece):
    lead_room = lead_above(deck, titles, lead)
    shown_lead = lead if lead_room else []
    caption_room = 0.4 if piece.caption else 0.0
    _, _, size, widths, header, pages, heights = table_pages(deck, piece.data, BODY_HEIGHT - lead_room - caption_room)
    start = 0
    for number, rows in enumerate(pages):
        slide = deck.new_slide(next(titles))
        top = BODY_TOP
        if number == 0 and shown_lead:
            top += write_items(deck, slide, shown_lead, SIDE_MARGIN, top, TEXT_WIDTH, COMFORTABLE_SIZE) + 0.25
        if piece.caption:
            write_text(deck, slide, literal(piece.caption), SIDE_MARGIN, top, CONTENT_WIDTH, 14, "muted", italic=True, name="Caption")
            top += caption_room
        rows_heights = heights[start:start + len(rows)]
        spare = BODY_TOP + BODY_HEIGHT - top - header - sum(rows_heights)
        rows_heights = [height + min(0.25, spare * 0.6 / len(rows)) for height in rows_heights] if spare > 0 else rows_heights
        add_table(deck, slide, piece.data, rows, widths, header, rows_heights, size, top)
        start += len(rows)


# splits and draws a code sample across slides
def draw_code(deck, titles, lead, piece):
    lead_room = lead_above(deck, titles, lead)
    lines = piece.data.expandtabs(4).split("\n")
    room = BODY_HEIGHT - lead_room - 2 * CODE_PADDING
    size = next((size for size in CODE_SIZES if len(code_chunks(deck, lines, size, room)[0]) == 1), CODE_SIZES[-1])
    chunks, _, _ = code_chunks(deck, lines, size, room)
    for number, chunk in enumerate(chunks):
        slide = deck.new_slide(next(titles))
        top = BODY_TOP
        if number == 0 and lead_room:
            top += write_items(deck, slide, lead, SIDE_MARGIN, top, TEXT_WIDTH, COMFORTABLE_SIZE) + 0.25
        used = sum(code_layout(deck, chunk, size, CONTENT_WIDTH - 2 * CODE_PADDING)) * size * CODE_LEADING / 72
        add_rect(deck, slide, SIDE_MARGIN, top, CONTENT_WIDTH, used + 2 * CODE_PADDING, "surface", "Code panel")
        frame = add_textbox(slide, SIDE_MARGIN + CODE_PADDING, top + CODE_PADDING, CONTENT_WIDTH - 2 * CODE_PADDING, used, "Code").text_frame
        for position, line in enumerate(chunk):
            paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
            set_spacing(paragraph, size, CODE_LEADING, 0)
            run = paragraph.add_run()
            run.text = line
            run.font.name, run.font.size, run.font.color.rgb = MONO_FONT, Pt(size), deck.color("ink")


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
        side = bool(lead) and lead_fits(deck, lead, SIDE_TEXT_WIDTH, BODY_HEIGHT)
        shown = lead if side else []
        if lead and not side:
            draw_text_slides(deck, titles, lead)
    slide = deck.new_slide(next(titles))
    top = BODY_TOP
    if side:
        items, size = fitted_items(deck, list(shown), SIDE_TEXT_WIDTH, BODY_HEIGHT, "Full text")
        write_items(deck, slide, items, SIDE_MARGIN, BODY_TOP, SIDE_TEXT_WIDTH, size)
    elif room:
        top += write_items(deck, slide, shown, SIDE_MARGIN, BODY_TOP, TEXT_WIDTH, COMFORTABLE_SIZE) + 0.25
    box = visual_box(side, 8.4 if figure else None)
    below = stack_height(deck, list(visual.after), TEXT_WIDTH, COMFORTABLE_SIZE) + 0.2 if visual.after else 0.0
    box = (box[0], top, box[2], BODY_TOP + BODY_HEIGHT - top - below)
    if visual.after:
        write_items(deck, slide, list(visual.after), SIDE_MARGIN, box[1] + box[3] + 0.1, TEXT_WIDTH, COMFORTABLE_SIZE)
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
    if first and first is parts[0] and first.kind == "paragraph" and len(first.source) <= OPENING_LIMIT:
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
