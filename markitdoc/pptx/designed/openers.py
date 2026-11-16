from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

from markitdoc.markup.blocks import paragraphs
from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import (
    Item,
    add_rect,
    body_height,
    body_sizes,
    body_top,
    comfortable_size,
    content_width,
    fitted_items,
    key_sentences,
    place_title,
    side_margin,
    slide_height,
    slide_width,
    soft_white,
    stack_height,
    text_width,
    tint,
    title_fit,
    white,
    write_column,
    write_items,
    write_text,
)
from markitdoc.pptx.designed.titles import draw_group, fit_text, plan_group
from markitdoc.pptx.photos import add_image, full_bleed, half_bleed, overlay, photo_for, send_to_back, side_title
from markitdoc.utils.helpers import lifted, long_date

cover_sizes, divider_sizes = (48, 44, 40, 36, 32, 28), (44, 40, 36, 32, 28)
quote_sizes = (36, 32, 28, 26, 24, 22, 20)
photo_fades = ((0, 0.25, 0.35, 0.0), (0.4, 0.8, 0.0, 0.85), (0.8, 1.0, 0.85, 0.92))


def draw_cover(deck, block, image):
    slots = block.slots
    photo = image is not None and slots.get("variant") != "light"
    dark = photo or slots.get("variant") != "light"
    slide = deck.new_slide(slots["title"], "night" if dark else "paper", False, standard=False)
    group = plan_group(deck, slots.get("kicker", ""), slots["title"], slots.get("subtitle", ""), cover_sizes, 11.2)
    if photo:
        night = deck.theme.rgb("night")
        fades = tuple((*fade, night) for fade in photo_fades)
        picture = add_image(slide, photo_for(deck, image[0], slide_width, slide_height, fades), 0, 0, slide_width, slide_height,
                            slots.get("image", "Photograph"), "Cover photo")
        send_to_back(slide, picture)
        write_text(deck, slide, literal(image[2]), slide_width - side_margin - 6, 7.05, 6, 10, soft_white, align=PP_ALIGN.RIGHT, name="Credit")
        draw_group(deck, slide, group, side_margin, max(0.9, 6.6 - group.total), 11.2,
                   (white, lifted(deck.theme.rgb("mood"), 0.55), soft_white))
        return
    roles = (white, lifted(deck.theme.rgb("mood"), 0.55), soft_white) if dark else ("ink", "mood", "body")
    draw_group(deck, slide, group, side_margin, max(1.0, (6.3 - group.total) / 2 + 0.1), 11.2, roles)
    add_rect(deck, slide, side_margin, 6.55, content_width, 0.015, tint(deck, "mood", 0.4) if dark else "rule", "Cover rule")
    write_text(deck, slide, literal(long_date(deck.meta.get("date", ""))), side_margin, 6.7, 6, 14, soft_white if dark else "muted", name="Date")
    write_text(deck, slide, literal(deck.theme.brand or ""), slide_width - side_margin - 6, 6.7, 6, 14, soft_white if dark else "muted",
               align=PP_ALIGN.RIGHT, name="Brand")


def draw_divider(deck, block, image):
    slots = block.slots
    dark = image is not None or slots.get("variant") != "light"
    slide = deck.new_slide(slots["title"], "night" if dark else "paper", False, standard=False)
    if image:
        full_bleed(deck, slide, image, overlay(deck, 0.62, 0.78), slots.get("image", "Photograph"))
    items = [Item(item[0], "bullet") for item in block.items if item and item[0]]
    width = 6.9 if items else 11.2
    group = plan_group(deck, slots.get("number", ""), slots["title"], slots.get("lead", ""), divider_sizes, width)
    draw_group(deck, slide, group, side_margin, max(1.0, (6.3 - group.total) / 2 + 0.1), width,
               (white, lifted(deck.theme.rgb("mood"), 0.55), soft_white) if dark else ("ink", "mood", "body"))
    if items:
        shown, size = fitted_items(deck, items, 4.0, body_height, "Sections")
        write_items(deck, slide, shown, slide_width - side_margin - 4.0, 2.2, 4.0, size, soft_white if dark else "body", "Sections")


def draw_quote(deck, block, image):
    slots = block.slots
    dark = image is not None or slots.get("variant") == "dark"
    slide = deck.new_slide(slots["quote"], "night" if dark else "paper", False, standard=False)
    if image:
        full_bleed(deck, slide, image, overlay(deck, 0.66, 0.66), slots.get("image", "Photograph"))
    role = white if dark else "ink"
    width, room = 10.4, 3.4
    size = next((size for size in quote_sizes if deck.text_height(slots["quote"], width, size, "", 1.15) <= room), quote_sizes[-1])
    shown = slots["quote"]
    if deck.text_height(shown, width, size, "", 1.15) > room:
        deck.note(f"Quote: {shown}")
        shown = key_sentences(deck, shown, width, room, size)
    height = deck.text_height(shown, width, size, "", 1.15)
    by = literal("— " + slots["quote_by"]) if slots.get("quote_by") else ""
    context, context_size = fit_text(deck, slots["context"], 9.0, 1.4, "Context", cap=18) if slots.get("context") else ("", 0)
    context_height = deck.text_height(context, 9.0, context_size) if context else 0
    total = 1.0 + height + (0.4 + 0.45 if by else 0) + (0.3 + context_height if context else 0)
    top = max(0.5, (slide_height - total) / 2 - 0.15)
    write_text(deck, slide, "“", side_margin, top, 1.4, 120, "mood", heading=True, leading=0.9, name="Quote mark")
    place_title(deck, slide, shown, role, 1.5, top + 1.0, width, height, (size,), 9, MSO_ANCHOR.TOP, bold=False, italic=True)
    top += 1.0 + height + 0.4
    if by:
        write_text(deck, slide, by, 1.5, top, width, 18, lifted(deck.theme.rgb("mood"), 0.55) if dark else "mood", bold=True,
                   name="Attribution")
        top += 0.75
    if context:
        write_text(deck, slide, context, 1.5, top, 9.0, context_size, soft_white if dark else "body", name="Context")


def draw_closing(deck, block, image):
    slots = block.slots
    slide = deck.new_slide(slots["title"], "night", False, standard=False)
    if image:
        full_bleed(deck, slide, image, overlay(deck, 0.55, 0.82), slots.get("image", "Photograph"))
    quote, quote_size = fit_text(deck, slots["quote"], 10.4, 1.9, "Quote", cap=28) if slots.get("quote") else ("", 0)
    quote_height = deck.text_height(quote, 10.4, quote_size) if quote else 0
    by = literal("— " + slots["quote_by"]) if quote and slots.get("quote_by") else ""
    size, shown = title_fit(deck, slots["title"], 11.2, divider_sizes, 2, "B")
    height = deck.text_height(shown, 11.2, size, "B", 1.12)
    items = [Item(text) for text in paragraphs(slots.get("body", ""))]
    lead_in = (quote_height + 0.15 + (0.35 if by else 0) + 0.5) if quote else 0
    body_room = max(1.0, 3.6 - height - lead_in)
    shown_items, body_size = fitted_items(deck, items, 9.6, body_room, "Closing text") if items else ([], 0)
    body_height_used = stack_height(deck, shown_items, 9.6, body_size) if items else 0
    total = lead_in + height + 0.6 + body_height_used
    top = max(0.8, (slide_height - total) / 2 - 0.1)
    if quote:
        used = write_text(deck, slide, quote, side_margin, top, 10.4, quote_size, lifted(deck.theme.rgb("mood"), 0.55), italic=True, name="Quote")
        if by:
            write_text(deck, slide, by, side_margin, top + used + 0.15, 10.4, 16, soft_white, bold=True, name="Attribution")
        top += lead_in
    place_title(deck, slide, shown, white, side_margin, top, 11.2, height, (size,), 2, MSO_ANCHOR.TOP)
    add_rect(deck, slide, side_margin, top + height + 0.2, 1.2, 0.04, "mood", "Title rule")
    if items:
        write_items(deck, slide, shown_items, side_margin, top + height + 0.6, 9.6, body_size, soft_white)


def draw_chapter(deck, block, image):
    slots = block.slots
    title = f"{slots['number']} — {slots['title']}" if slots.get("number") else slots["title"]
    texts = paragraphs(slots.get("body", ""))
    if image:
        slide = deck.new_slide(title, footer=False, standard=False)
        left, width = half_bleed(deck, slide, image, slots.get("image", "Photograph"))
        top = side_title(deck, slide, title, left, width)
        if slots.get("quote"):
            deck.note(f"Quote: {slots['quote']}")
        write_column(deck, slide, [Item(text) for text in ([slots["lead"]] if slots.get("lead") else []) + texts], left, top, width, 6.9)
        return
    slide = deck.new_slide(title)
    end = draw_two_columns(deck, slide, slots, texts)
    if slots.get("quote"):
        draw_pull_quote(deck, slide, slots["quote"], end)


def draw_two_columns(deck, slide, slots, texts):
    top = body_top
    if slots.get("lead"):
        lead, size = fit_text(deck, slots["lead"], text_width, 1.3, "Lead")
        top += write_text(deck, slide, lead, side_margin, top, text_width, size, "ink", name="Lead") + 0.3
    quote_room = deck.text_height(slots["quote"], text_width - 0.4, 18) + 0.5 if slots.get("quote") else 0
    column = (content_width - 0.6) / 2
    half = (len(texts) + 1) // 2
    halves = [[Item(text) for text in texts[:half]], [Item(text) for text in texts[half:]]]
    room = max(0.8, body_top + body_height - top - quote_room)
    size = next((size for size in body_sizes if size <= comfortable_size
                 and all(stack_height(deck, items, column, size) <= room for items in halves if items)), None)
    if size is None:
        deck.note("Full text: " + " ".join(texts))
        halves = [[Item(key_sentences(deck, item.source, column, room / max(1, len(items)), 16)) for item in items] for items in halves]
        size = 16
    end = top
    for index, items in enumerate(halves):
        if items:
            end = max(end, top + write_items(deck, slide, items, side_margin + index * (column + 0.6), top, column, size))
    return end


def draw_pull_quote(deck, slide, quote, after):
    top = max(after + 0.2, body_top + body_height - 1.0)
    shown, size = fit_text(deck, quote, text_width - 0.4, body_top + body_height - top, "Quote", cap=18)
    height = write_text(deck, slide, shown, side_margin + 0.4, top, text_width - 0.4, size, "ink", italic=True, name="Pull quote")
    add_rect(deck, slide, side_margin, top, 0.07, height, "mood", "Quote rule")
