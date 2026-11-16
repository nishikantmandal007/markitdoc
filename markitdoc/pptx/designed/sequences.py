import math
from dataclasses import replace

from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

from markitdoc.markup.inline import plain_text
from markitdoc.pptx.deck import (
    add_badge,
    add_rect,
    body_height,
    body_top,
    content_width,
    side_margin,
    split_to_fit,
    tint,
    white,
    write_text,
)
from markitdoc.pptx.designed.titles import draw_lead, fit_text, lead_room, max_per_slide, slide_titles
from markitdoc.visuals.gantt import gantt_plan, unit_name

row_presets = ((24, 20), (22, 18), (20, 16), (18, 15), (16, 14))
column_presets = ((22, 18), (20, 16), (18, 16), (16, 14))
comparison_presets = ((22, 0), (20, 0), (18, 0), (16, 0), (14, 0))


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
