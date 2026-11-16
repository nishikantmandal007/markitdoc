import math
import re

from pptx.util import Inches, Pt

from markitdoc.markup.blocks import paragraphs
from markitdoc.markup.inline import plain_text
from markitdoc.pptx.deck import (
    Item,
    add_rect,
    body_height,
    body_top,
    content_width,
    fitted_items,
    side_margin,
    slide_width,
    soft_white,
    split_to_fit,
    text_width,
    tint,
    white,
    write_column,
    write_items,
    write_text,
)
from markitdoc.pptx.designed.titles import column_gap, draw_lead, fit_text, lead_room, max_per_slide, row_gap, slide_titles
from markitdoc.pptx.photos import half_bleed, side_title

figure_presets = ((60, 20, 18), (52, 20, 16), (44, 18, 16), (40, 18, 14), (32, 16, 14))


def resolved_preset(deck, items, width, preset):
    value_size, label_size, note_size = preset
    while value_size > 18 and any(deck.lines(item[0], width, value_size, "B") > 1 for item in items):
        value_size -= 2
    return value_size, label_size, note_size


def column_height(deck, item, width, preset):
    value_size, label_size, note_size = preset
    note = item[2] if len(item) > 2 else ""
    return (deck.text_height(item[0], width, value_size, "B", 1.15) + 0.12 + deck.text_height(item[1], width, label_size, "B")
            + (0.1 + deck.text_height(note, width, note_size) if note else 0))


def draw_progress_ring(deck, slide, left, top, size, share, dark):
    thickness = size * 0.13
    ring_band(deck, slide, left, top, size, thickness, 1.0, tint(deck, "mood", 0.45 if dark else 0.85), "Progress track")
    if share > 0:
        ring_band(deck, slide, left, top, size, thickness, min(share, 0.9999), white if dark else "mood", "Progress")


def ring_band(deck, slide, left, top, size, thickness, share, role, name):
    steps = max(8, int(120 * share))
    outer, inner = size / 2, size / 2 - thickness
    centre_x, centre_y = left + size / 2, top + size / 2
    angles = [-math.pi / 2 + 2 * math.pi * share * step / steps for step in range(steps + 1)]
    points = [(centre_x + outer * math.cos(angle), centre_y + outer * math.sin(angle)) for angle in angles]
    points += [(centre_x + inner * math.cos(angle), centre_y + inner * math.sin(angle)) for angle in reversed(angles)]
    builder = slide.shapes.build_freeform(Inches(points[0][0]), Inches(points[0][1]), scale=1.0)
    builder.add_line_segments([(Inches(x), Inches(y)) for x, y in points[1:]], close=True)
    shape = builder.convert_to_shape()
    shape.name = name
    shape.fill.solid()
    shape.fill.fore_color.rgb = deck.color(role)
    shape.line.fill.background()


def percent_share(value):
    found = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%\s*", plain_text(value))
    return float(found.group(1)) / 100 if found and float(found.group(1)) <= 100 else None


def draw_column(deck, slide, item, preset, left, top, width, dark=False, value_width=None):
    value_size, label_size, note_size = preset
    used = write_text(deck, slide, item[0], left, top, value_width or width, value_size, white if dark else "mood", heading=True, leading=1.15,
                      name="Figure value")
    top += max(used, (width - value_width) if value_width else 0) + 0.12
    top += write_text(deck, slide, item[1], left, top, width, label_size, white if dark else "ink", bold=True, name="Figure label")
    if len(item) > 2 and item[2]:
        write_text(deck, slide, item[2], left, top + 0.1, width, note_size, soft_white if dark else "body", name="Figure note")


def figure_rows(items, columns):
    return [items[start:start + columns] for start in range(0, len(items), columns)]


def grid_plan(deck, items, height, width=content_width, columns=None):
    columns = columns or (len(items) if len(items) <= 5 else 3)
    rows = figure_rows(list(items), columns)
    column_width = (width - column_gap * (columns - 1)) / columns
    inner = column_width - 0.6

    def row_height(row, preset):
        return max(column_height(deck, item, inner, preset) for item in row) + 0.6

    def total(preset):
        return sum(row_height(row, preset) for row in rows) + row_gap * (len(rows) - 1)

    resolved = [resolved_preset(deck, items, inner, preset) for preset in figure_presets]
    preset = next((preset for preset in resolved if total(preset) <= height), resolved[-1])
    return rows, column_width, inner, preset, row_height, total(preset)


def draw_figure_grid(deck, slide, items, top, height, left=side_margin, width=content_width, columns=None):
    rows, column_width, inner, preset, row_height, total = grid_plan(deck, items, height, width, columns)
    top += max(0.0, height - total) * 0.4
    for number, row in enumerate(rows):
        card = row_height(row, preset)
        for position, item in enumerate(row):
            card_left = left + position * (column_width + column_gap)
            dark = number == 0 and position == 0 and len(items) >= 3
            shape = add_rect(deck, slide, card_left, top, column_width, card, "night" if dark else "paper", "Figure card")
            shape.line.color.rgb, shape.line.width = deck.color(tint(deck, "mood", 0.7)), Pt(0.75)
            share = percent_share(item[0])
            ring = min(1.0, card - 0.6, inner * 0.38) if share is not None else 0
            if ring and deck.lines(item[0], inner - ring - 0.2, preset[0], "B") > 1:
                ring = 0
            draw_column(deck, slide, item, preset, card_left + 0.3, top + 0.3, inner, dark, inner - ring - 0.2 if ring >= 0.7 else None)
            if ring >= 0.7:
                draw_progress_ring(deck, slide, card_left + column_width - 0.3 - ring, top + 0.3, ring, share, dark)
        top += card + row_gap
    return top


def draw_summary(deck, block, image):
    slots = block.slots
    slide = deck.new_slide(slots["title"])
    top = draw_lead(deck, slide, slots.get("lead", ""), body_top)
    items = [item for item in block.items if item and item[0]]
    body = [Item(text) for text in paragraphs(slots.get("body", ""))]
    reserve = 1.6 if body else 0
    if items:
        top = draw_figure_grid(deck, slide, items[:4], top, body_height - (top - body_top) - reserve)
    if body:
        shown, size = fitted_items(deck, body, text_width, max(0.6, body_top + body_height - top), "Summary text")
        write_items(deck, slide, shown, side_margin, top, text_width, size)


def draw_figures(deck, block, image):
    slots = block.slots
    items = [item for item in block.items if item and item[0]]
    room = body_height - lead_room(deck, slots.get("lead", ""))
    groups = split_to_fit(items, lambda group: len(group) <= max_per_slide["figures"] and grid_plan(deck, group, room)[-1] <= room)
    titles = slide_titles(slots["title"])
    for number, group in enumerate(groups):
        slide = deck.new_slide(next(titles))
        top = draw_lead(deck, slide, slots.get("lead", "") if number == 0 else "", body_top)
        top = draw_figure_grid(deck, slide, group, top, body_height - (top - body_top))
        body = [Item(text) for text in paragraphs(slots.get("body", ""))] if number == len(groups) - 1 else []
        if body:
            shown, size = fitted_items(deck, body, text_width, max(0.6, body_top + body_height - top), "Figures text")
            write_items(deck, slide, shown, side_margin, top, text_width, size)


def draw_text_column(deck, slide, slots, paragraph_items, left, width, height):
    top = body_top
    if slots.get("lead"):
        lead, size = fit_text(deck, slots["lead"], width, 1.6, "Lead", cap=22)
        top += write_text(deck, slide, lead, left, top, width, size, "ink", name="Lead") + 0.25
    quote_room = deck.text_height(slots["quote"], width - 0.4, 18) + 0.4 if slots.get("quote") else 0
    items = [Item(text) for text in paragraph_items]
    shown, size = fitted_items(deck, items, width, max(0.8, body_top + height - top - quote_room), "Full text")
    top += write_items(deck, slide, shown, left, top, width, size)
    return top


def draw_feature(deck, block, image):
    slots = block.slots
    items = [item for item in block.items if item and item[0]][:3]
    texts = paragraphs(slots.get("body", ""))
    if image:
        slide = deck.new_slide(slots["title"], footer=False, standard=False)
        left, width = half_bleed(deck, slide, image, slots.get("image", "Photograph"))
        top = side_title(deck, slide, slots["title"], left, width)
        row = 1.75 if items else 0
        write_column(deck, slide, [Item(text) for text in texts], left, top, width, 6.9 - row - (0.25 if items else 0))
        if items:
            draw_figure_grid(deck, slide, items, 6.9 - row, row, left, width, len(items))
        return
    slide = deck.new_slide(slots["title"])
    width = 6.9 if items else text_width
    draw_text_column(deck, slide, {"lead": ""}, texts, side_margin, width, body_height)
    rail = (body_height - 0.3 * (len(items) - 1)) / len(items) if items else 0
    for index, item in enumerate(items):
        top = body_top + index * (rail + 0.3)
        left = slide_width - side_margin - 4.4
        add_rect(deck, slide, left, top, 4.4, rail, "surface", "Figure card")
        add_rect(deck, slide, left, top, 0.07, rail, "mood", "Figure accent")
        size = 40
        while size > 28 and deck.lines(item[0], 3.8, size, "B") > 1:
            size -= 2
        write_text(deck, slide, item[0], left + 0.35, top + 0.2, 3.8, size, "mood", heading=True, leading=1.15, name="Figure value")
        write_text(deck, slide, item[1], left + 0.35, top + 0.3 + size * 1.15 / 72, 3.8, 16, "body", name="Figure label")
