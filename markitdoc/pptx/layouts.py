import math
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

import logging
from markitdoc.utils.constants import PLATFORM_CREATOR, PLATFORM_KEYWORDS
from markitdoc.models.document import Document
from markitdoc.markup.blocks import as_flow, balanced, paragraphs, prepared
from markitdoc.utils.helpers import creation_date, lifted, long_date
from markitdoc.pptx.brand_cover import draw_brand_cover
from markitdoc.markup.inline import literal, plain_text
from markitdoc.pptx.deck import (Deck, Item, add_badge, write_column, add_rect, body_height, body_sizes, body_top,
                                 comfortable_size, content_width, fitted_items, key_sentences, place_title, side_margin,
                                 slide_height, slide_width, soft_white, split_to_fit, stack_height, text_width, tint,
                                 title_fit, white, write_items, write_text)
from markitdoc.pptx.package import save_presentation
from markitdoc.pptx.photos import (add_fade, full_bleed, half_bleed, overlay, side_title, add_image, photo_for,
                                   send_to_back)
from markitdoc.pptx.flow import draw_flow, draw_text_slides, title_stream
from markitdoc.themes.themes import Theme
from markitdoc.visuals.gantt import gantt_plan, unit_name
from markitdoc.pptx.titles import draw_group, draw_lead, fit_text, lead_room, max_per_slide, plan_group, slide_titles
from markitdoc.pptx.grids import draw_feature, draw_figures, draw_summary

logger = logging.getLogger(__name__)
cover_sizes, divider_sizes = (48, 44, 40, 36, 32, 28), (44, 40, 36, 32, 28)
quote_sizes = (36, 32, 28, 26, 24, 22, 20)
row_presets = ((24, 20), (22, 18), (20, 16), (18, 15), (16, 14))
column_presets = ((22, 18), (20, 16), (18, 16), (16, 14))
comparison_presets = ((22, 0), (20, 0), (18, 0), (16, 0), (14, 0))
photo_fades = ((0, 0.25, 0.35, 0.0), (0.4, 0.8, 0.0, 0.85), (0.8, 1.0, 0.85, 0.92))
required_slots = {"cover": "title", "summary": "title", "divider": "title", "chapter": "title", "figures": "title", "keypoints": "title",
                  "matrix": "title", "quote": "quote", "comparison": "title", "process": "title", "timeline": "title", "feature": "title",
                  "closing": "title"}
needs_items = {"figures": 1, "keypoints": 1, "matrix": 4, "comparison": 1, "process": 1, "timeline": 1}
slide_photo_ratios = {"cover": 16 / 9, "divider": 16 / 9, "quote": 16 / 9, "closing": 16 / 9, "chapter": 8 / 9, "feature": 8 / 9}


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


def fitting_preset(presets, height_of, group, available):
    return next((preset for preset in presets if height_of(group, preset) <= available), None)


def split_rows(deck, items, cap, height_of, presets, available):
    return split_to_fit(list(items), lambda group: len(group) <= cap and fitting_preset(presets, height_of, group, available) is not None)


def keypoint_height(deck, group, preset):
    head, text = preset
    width = content_width - 1.6
    return len(group) * (max(max(0.9, deck.text_height(item[0], width, head, "B") + 0.06 + deck.text_height(item[1], width, text) + 0.36)
                             for item in group) + 0.2)


def draw_keypoints(deck, block, image):
    slots = block.slots
    room = body_height - lead_room(deck, slots.get("lead", ""))
    titles = slide_titles(slots["title"])
    start = 0
    for number, group in enumerate(split_rows(deck, block.items, max_per_slide["keypoints"], lambda g, p: keypoint_height(deck, g, p),
                                              row_presets, room)):
        slide = deck.new_slide(next(titles))
        top = draw_lead(deck, slide, slots.get("lead", "") if number == 0 else "", body_top)
        preset = fitting_preset(row_presets, lambda g, p: keypoint_height(deck, g, p), group, room) or row_presets[-1]
        head, text = preset
        top += max(0.0, room - keypoint_height(deck, group, preset)) * 0.3
        width = content_width - 1.6
        used = max(max(0.9, deck.text_height(item[0], width, head, "B") + 0.06 + deck.text_height(item[1], width, text) + 0.36) for item in group)
        for index, item in enumerate(group, start + 1):
            add_rect(deck, slide, side_margin, top, content_width, used, "surface", "Point card")
            add_badge(deck, slide, side_margin + 0.3, top + (used - 0.6) / 2, 0.6, str(index))
            after = write_text(deck, slide, item[0], side_margin + 1.2, top + 0.18, width, head, "ink", bold=True, name="Heading")
            write_text(deck, slide, item[1], side_margin + 1.2, top + 0.24 + after, width, text, "body", name="Detail")
            top += used + 0.2
        start += len(group)


def horizontal_height(deck, group, preset):
    width = (content_width - 0.3 * (len(group) - 1)) / len(group)
    return (1.0 + max(deck.text_height(item[0], width, preset[0], "B") for item in group) + 0.08
            + max(deck.text_height(item[-1], width, preset[1]) if item[-1] else 0 for item in group))


def draw_process(deck, block, image):
    slots = block.slots
    items = [item for item in block.items if item and item[0]]
    room = body_height - lead_room(deck, slots.get("lead", ""))
    titles = slide_titles(slots["title"])
    start = 0
    short = all(len(plain_text(item[0]).split()) <= 3 and len(plain_text(item[-1]).split()) <= 6 for item in items)
    for number, group in enumerate(split_rows(deck, items, 8 if short else max_per_slide["process"], lambda g, p: horizontal_height(deck, g, p),
                                              column_presets, room)):
        slide = deck.new_slide(next(titles))
        top = draw_lead(deck, slide, slots.get("lead", "") if number == 0 else "", body_top)
        preset = fitting_preset(column_presets, lambda g, p: horizontal_height(deck, g, p), group, room) or column_presets[-1]
        top += max(0.0, room - horizontal_height(deck, group, preset)) * 0.35
        width = (content_width - 0.3 * (len(group) - 1)) / len(group)
        heading_size = preset[0]
        while heading_size > 14 and any(deck.lines(word, width, heading_size, "B") > 1 for item in group for word in plain_text(item[0]).split()):
            heading_size -= 1
        preset = (heading_size, min(preset[1], heading_size))
        heading_room = max(deck.text_height(item[0], width, preset[0], "B") for item in group)
        for index, item in enumerate(group):
            left = side_margin + index * (width + 0.3)
            chevron = add_rect(deck, slide, left, top, width + 0.22, 0.7, tint(deck, "mood", 0.5 * index / max(1, len(group) - 1)), "Step",
                               MSO_SHAPE.PENTAGON if index == 0 else MSO_SHAPE.CHEVRON)
            frame = chevron.text_frame
            frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
            frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            paragraph = frame.paragraphs[0]
            paragraph.alignment = PP_ALIGN.CENTER
            run = paragraph.add_run()
            run.text = f"{start + index + 1:02d}"
            run.font.size, run.font.bold, run.font.name = Pt(20), True, deck.heading_font
            run.font.color.rgb = deck.color(white)
            write_text(deck, slide, item[0], left, top + 0.95, width, preset[0], "ink", bold=True, name="Step heading")
            if item[-1]:
                write_text(deck, slide, item[-1], left, top + 0.95 + heading_room + 0.08, width, preset[1], "body", name="Step text")
        start += len(group)


def draw_gantt(deck, block, plan):
    slots = block.slots
    unit, first, last, periods = plan
    slide = deck.new_slide(slots["title"])
    top = draw_lead(deck, slide, slots.get("lead", ""), body_top)
    label_width, columns = 3.6, last - first + 1
    grid_left = side_margin + label_width + 0.2
    column = (content_width - label_width - 0.2) / columns
    header = 0.45
    row = min(0.85, (body_top + body_height - top - header) / len(periods))
    every = max(1, math.ceil(columns / 12))
    for index in range(columns):
        if index % every == 0:
            write_text(deck, slide, unit_name(unit, first + index), grid_left + index * column, top, column * every, 13, "muted", bold=True,
                       name="Gantt period")
        add_rect(deck, slide, grid_left + index * column, top + header, 0.01, row * len(periods), "rule", "Gantt grid")
    for position, (item, found) in enumerate(zip(block.items, periods)):
        y = top + header + position * row
        if position % 2 == 0:
            add_rect(deck, slide, side_margin, y, content_width, row, "surface", "Gantt band")
        size = 16 if deck.lines(item[1], label_width - 0.2, 16, "B") <= 2 else 14
        write_text(deck, slide, item[1], side_margin + 0.15, y + (row - deck.text_height(item[1], label_width - 0.2, size, "B")) / 2,
                   label_width - 0.2, size, "ink", bold=True, name="Gantt task")
        bar = add_rect(deck, slide, grid_left + (found[1] - first) * column + 0.04, y + row * 0.22, (found[2] - found[1] + 1) * column - 0.08,
                       row * 0.56, "mood", "Gantt bar", MSO_SHAPE.ROUNDED_RECTANGLE)
        bar.adjustments[0] = 0.3
        detail = item[2] if len(item) > 2 else ""
        if detail:
            deck.note(f"{plain_text(item[1])}: {plain_text(detail)}")


def draw_timeline(deck, block, image):
    slots = block.slots
    items = [item for item in block.items if item and item[0]]
    plan = gantt_plan(items) if len(items) <= 8 else None
    if plan:
        draw_gantt(deck, replace(block, items=tuple(items)), plan)
        return
    room = body_height - lead_room(deck, slots.get("lead", ""))
    titles = slide_titles(slots["title"])

    def height_of(group, preset):
        width = (content_width - 0.3 * (len(group) - 1)) / len(group)
        return (0.95 + max(deck.text_height(item[1], width, preset[0], "B") for item in group) + 0.08
                + max(deck.text_height(item[-1], width, preset[1]) if len(item) > 2 and item[-1] else 0 for item in group))

    for number, group in enumerate(split_rows(deck, items, max_per_slide["timeline"], height_of, column_presets, room)):
        slide = deck.new_slide(next(titles))
        top = draw_lead(deck, slide, slots.get("lead", "") if number == 0 else "", body_top)
        preset = fitting_preset(column_presets, height_of, group, room) or column_presets[-1]
        top += max(0.0, room - height_of(group, preset)) * 0.35
        width = (content_width - 0.3 * (len(group) - 1)) / len(group)
        heading_room = max(deck.text_height(item[1], width, preset[0], "B") for item in group)
        add_rect(deck, slide, side_margin, top + 0.63, content_width, 0.04, tint(deck, "mood", 0.6), "Axis")
        for index, item in enumerate(group):
            left = side_margin + index * (width + 0.3)
            pill = add_rect(deck, slide, left, top, min(width, 0.4 + len(item[0]) * 0.12), 0.42, "mood", "When", MSO_SHAPE.ROUNDED_RECTANGLE)
            pill.text_frame.margin_top = pill.text_frame.margin_bottom = 0
            pill.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            run = pill.text_frame.paragraphs[0].add_run()
            run.text = plain_text(item[0])
            run.font.size, run.font.bold, run.font.name = Pt(14), True, deck.body_font
            run.font.color.rgb = deck.color(white)
            add_rect(deck, slide, left + 0.12, top + 0.55, 0.2, 0.2, "mood", "Marker", MSO_SHAPE.OVAL)
            write_text(deck, slide, item[1], left, top + 0.95, width, preset[0], "ink", bold=True, name="Event")
            if len(item) > 2 and item[-1]:
                write_text(deck, slide, item[-1], left, top + 0.95 + heading_room + 0.08, width, preset[1], "body", name="Description")


def draw_comparison(deck, block, image):
    slots = block.slots
    column = (content_width - 0.4) / 2
    takeaway = slots.get("takeaway", "")
    band = deck.text_height(takeaway, content_width - 0.6, 18, "B") + 0.4 if takeaway else 0
    inner = column - 0.6
    base = body_height - 1.1

    def height_of(group, preset):
        return sum(max(deck.text_height(item[0], inner, preset[0]), deck.text_height(item[1], inner, preset[0])) + 0.14 for item in group)

    def fits(group, room):
        return len(group) <= max_per_slide["comparison"] and fitting_preset(comparison_presets, height_of, group, room) is not None

    def room_for(position, count, lead_space):
        return base - (lead_space if position == 0 else 0) - (band + 0.2 if band and position == count - 1 else 0)

    def packed(lead_space):
        groups = [[]]
        for item in block.items:
            if groups[-1] and not fits(groups[-1] + [item], base - (lead_space if len(groups) == 1 else 0)):
                groups.append([])
            groups[-1].append(item)
        if band and len(groups[-1]) > 1 and not fits(groups[-1], room_for(len(groups) - 1, len(groups), lead_space)):
            groups.append([groups[-1].pop()])
        return groups

    lead = slots.get("lead", "")
    lead_space = lead_room(deck, lead)
    groups = packed(lead_space)
    if len(groups) > 1 and lead and len(packed(0)) == 1:
        deck.note(f"Lead: {lead}")
        groups, lead, lead_space = packed(0), "", 0
    titles = slide_titles(slots["title"])
    for number, group in enumerate(groups):
        slide = deck.new_slide(next(titles))
        top = draw_lead(deck, slide, lead if number == 0 else "", body_top)
        size = (fitting_preset(comparison_presets, height_of, group, room_for(number, len(groups), lead_space)) or comparison_presets[-1])[0]
        rows = height_of(group, (size,))
        for side, heading in enumerate((slots["left"], slots["right"])):
            left = side_margin + side * (column + 0.4)
            add_rect(deck, slide, left, top, column, 0.95 + rows + 0.15, "surface", "Column card")
            add_rect(deck, slide, left, top, column, 0.7, "night" if side == 0 else "mood", "Column header")
            heading_size = 20 if deck.lines(heading, inner, 20, "B") == 1 else 16
            write_text(deck, slide, heading, left + 0.3, top + 0.35 - heading_size * 0.6 / 72, inner, heading_size, white, heading=True,
                       name="Column heading")
        top += 0.95
        for item in group:
            used = max(deck.text_height(item[0], inner, size), deck.text_height(item[1], inner, size))
            for side in (0, 1):
                write_text(deck, slide, item[side], side_margin + side * (column + 0.4) + 0.3, top, inner, size, "body", name="Comparison text")
            top += used + 0.14
        if takeaway and number == len(groups) - 1:
            add_rect(deck, slide, side_margin, body_top + body_height - band, content_width, band, "surface", "Takeaway band")
            write_text(deck, slide, takeaway, side_margin + 0.3, body_top + body_height - band + 0.2, content_width - 0.6, 18, "ink", bold=True,
                       name="Takeaway")


def draw_matrix(deck, block, image):
    slots = block.slots
    slide = deck.new_slide(slots["title"])
    top = draw_lead(deck, slide, slots.get("lead", ""), body_top)
    gap = 0.3
    width, height = (content_width - gap) / 2, (body_top + body_height - top - gap) / 2
    for index, item in enumerate(block.items[:4]):
        left, cell_top = side_margin + (index % 2) * (width + gap), top + (index // 2) * (height + gap)
        add_rect(deck, slide, left, cell_top, width, height, tint(deck, "mood", (0.86, 0.92, 0.92, 0.96)[index]), "Quadrant")
        add_rect(deck, slide, left, cell_top, 0.07, height, "mood", "Quadrant accent")
        inner = width - 0.6
        used = write_text(deck, slide, item[0], left + 0.35, cell_top + 0.2, inner, 20, "ink", heading=True, name="Quadrant label")
        text, size = fit_text(deck, item[1], inner, height - used - 0.45, f"{item[0]}", cap=18)
        write_text(deck, slide, text, left + 0.35, cell_top + 0.3 + used, inner, size, "body", name="Quadrant text")


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


drawers = {"cover": draw_cover, "divider": draw_divider, "quote": draw_quote, "closing": draw_closing, "summary": draw_summary,
           "figures": draw_figures, "keypoints": draw_keypoints, "process": draw_process, "timeline": draw_timeline,
           "comparison": draw_comparison, "matrix": draw_matrix, "chapter": draw_chapter, "feature": draw_feature}


def drawable(block):
    slot = required_slots.get(block.layout)
    return (slot is not None and bool(block.slots.get(slot)) and len([item for item in block.items if item and item[0]]) >= needs_items.get(block.layout, 0)
            and (block.layout != "comparison" or bool(block.slots.get("left") and block.slots.get("right"))))


def draw_designed(deck, block, image=None):
    drawers[block.layout](deck, block, image)


def draw_block(deck, index, block):
    before = deck.slide_count
    try:
        if block.layout == "flow":
            draw_flow(deck, block.body, draw_designed)
        elif drawable(block):
            drawers[block.layout](deck, block, deck.photos_by_block.get(index))
        else:
            logger.warning("Slide block %d (%s) is incomplete, shown as plain slides", index + 1, block.layout)
            draw_flow(deck, as_flow(block).body, draw_designed)
    except Exception:
        logger.exception("Slide block %d (%s) failed to draw; shown as plain slides", index + 1, block.layout)
        deck.drop_slides_after(before)
        draw_flow(deck, as_flow(block).body, draw_designed)


def deck_title(blocks, meta):
    first = blocks[0]
    return (meta.get("title") or first.slots.get("title") or next((line.lstrip("# ").strip() for line in first.body.splitlines()
                                                                if line.startswith("# ")), "") or "Presentation")


def draw_notes_slide(deck):
    if deck.footnotes:
        items = [Item(f"{text}", "number", 0, number) for number, (_, text) in enumerate(deck.footnotes, 1)]
        draw_text_slides(deck, title_stream("Notes"), items)


def stamp_metadata(deck, user_email, title):
    properties = deck.presentation.core_properties
    moment = creation_date(deck.meta.get("date"))
    properties.author = user_email or deck.theme.brand or ""
    properties.last_modified_by = properties.author
    properties.title = title
    properties.subject = str(deck.meta.get("subject", "")) or title
    properties.created = properties.modified = moment.replace(tzinfo=None)
    properties.revision = 1
    properties.comments = PLATFORM_CREATOR
    properties.keywords = PLATFORM_KEYWORDS
    properties.category = "generated-document"


def render_pptx(document: Document, theme: Theme, output_path: Path, images=None, user_email=""):
    started = time.perf_counter()
    blocks = balanced([prepared(block) for block in document.blocks], theme)
    with tempfile.TemporaryDirectory() as work_folder:
        deck = Deck(theme, document.meta, Path(work_folder), images or {})
        deck.title = plain_text(deck_title(blocks, document.meta))
        first = 0
        if deck.branded:
            cover = blocks[0] if blocks[0].layout == "cover" and drawable(blocks[0]) else None
            draw_brand_cover(deck, cover)
            first = 1 if cover else 0
        for index, block in enumerate(blocks[first:], first):
            draw_block(deck, index, block)
        draw_notes_slide(deck)
        deck.flush_notes()
        for slide in deck.presentation.slides:
            add_fade(slide)
        stamp_metadata(deck, user_email, deck.title)
        save_presentation(deck.presentation, output_path)
    logger.info("PPTX rendered: %d blocks, %d slides, theme %s, %d images, %.1f s", len(blocks), deck.slide_count, theme.name,
                len(images or {}), time.perf_counter() - started)
    return output_path

