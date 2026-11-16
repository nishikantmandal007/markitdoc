import re

from markitdoc.markup.inline import plain_text
from markitdoc.pptx.deck import add_rect, content_width, side_margin, white, write_text

card_gap, card_presets, panel_width = 0.3, ((22, 18), (20, 16), (18, 15), (16, 14)), 4.3
leading_figure = re.compile(r"^\s*([~≈<>+\-−]?[$€£¥]?\d[\d.,]*\s?(?:%|[kKmMbBxX]\b|bn\b|tn\b|pts?\b|bps\b)?\+?)\s*(.*)$")
card_pattern = re.compile(r"^\*\*(.+?)\*\*\s*(?:—|–|:|-)\s*(.+)$")


def card_pairs(items):
    pairs = [card_pattern.match(item.source.strip()) for item in items]
    if not 2 <= len(items) <= 6 or not all(item.listed and item.level == 0 for item in items) or not all(pairs):
        return None
    return [(match.group(1), match.group(2)) for match in pairs]


def card_columns(pairs):
    return 3 if len(pairs) in (5, 6) else len(pairs)


def card_preset(deck, pairs, height, columns=None):
    columns = columns or card_columns(pairs)
    rows = (len(pairs) + columns - 1) // columns
    width = (content_width - card_gap * (columns - 1)) / columns - 0.6
    for head, text in card_presets:
        needed = max(deck.text_height(head_text, width, head, "B") + 0.15 + deck.text_height(detail, width, text) for head_text, detail in pairs)
        if (needed + 0.8) * rows + card_gap * (rows - 1) <= height:
            return head, text, needed + 1.45
    return None


def figure_cards(pairs):
    found = [leading_figure.match(plain_text(head)) for head, _ in pairs]
    if not all(found):
        return None
    return tuple((match.group(1), match.group(2).strip(" -—:") or match.group(1), detail) for match, (_, detail) in zip(found, pairs))


def card_layouts(deck, pairs, height, preset):
    layouts = {"columns": preset} if preset else {}
    if stacked_fits(deck, pairs, height):
        layouts["rows"] = None
    grid = card_preset(deck, pairs, height, 2) if len(pairs) == 4 else None
    if grid:
        layouts["grid"] = grid
    return layouts


def draw_cards(deck, slide, pairs, top, height, preset):
    layouts = card_layouts(deck, pairs, height, preset)
    names = list(layouts)
    turn = deck.card_turn % len(names)
    pick = next((name for name in names[turn:] + names[:turn] if name != deck.last_cards), names[0])
    deck.card_turn += 1
    deck.last_cards = pick
    if pick == "rows":
        return draw_card_rows(deck, slide, pairs, top, height)
    head, text, card_height = layouts[pick]
    card_height -= 0.65
    columns = 2 if pick == "grid" else card_columns(pairs)
    rows = (len(pairs) + columns - 1) // columns
    width = (content_width - card_gap * (columns - 1)) / columns
    heading_room = max(deck.text_height(head_text, width - 0.6, head, "B") for head_text, _ in pairs)
    top += max(0.0, height - card_height * rows - card_gap * (rows - 1)) * 0.45
    for index, (head_text, detail) in enumerate(pairs):
        left = side_margin + (index % columns) * (width + card_gap)
        card_top = top + (index // columns) * (card_height + card_gap)
        add_rect(deck, slide, left, card_top, width, card_height, "surface", "Card")
        add_rect(deck, slide, left, card_top, width, 0.06, "mood", "Card accent")
        write_text(deck, slide, head_text, left + 0.3, card_top + 0.4, width - 0.6, head, "ink", bold=True, name="Card heading")
        write_text(deck, slide, detail, left + 0.3, card_top + 0.55 + heading_room, width - 0.6, text, "body", name="Card text")
    return top + card_height * rows + card_gap * (rows - 1)


def draw_takeaway(deck, slide, items, bottom):
    source = " ".join(item.source for item in items)
    height = deck.text_height(source, content_width - 0.6, 16, "B") + 0.4
    add_rect(deck, slide, side_margin, bottom - height, content_width, height, "surface", "Takeaway band")
    add_rect(deck, slide, side_margin, bottom - height, 0.07, height, "mood", "Takeaway accent")
    write_text(deck, slide, source, side_margin + 0.35, bottom - height + 0.2, content_width - 0.7, 16, "ink", bold=True, name="Takeaway")
    return height


def stacked_fits(deck, pairs, height, width=content_width):
    return sum(row_height_of(deck, head_text, detail, width) for head_text, detail in pairs) + card_gap * (len(pairs) - 1) <= height


def row_widths(width):
    head = min(3.4, width * 0.36)
    return head, width - head - 1.2


def row_height_of(deck, head_text, detail, width=content_width):
    head, text = row_widths(width)
    return max(deck.text_height(head_text, head, 18, "B"), deck.text_height(detail, text, 16)) + 0.44


def draw_card_rows(deck, slide, pairs, top, height, left=side_margin, width=content_width):
    head, text = row_widths(width)
    total = sum(row_height_of(deck, head_text, detail, width) for head_text, detail in pairs) + card_gap * (len(pairs) - 1)
    top += max(0.0, height - total) * 0.45
    for head_text, detail in pairs:
        row = row_height_of(deck, head_text, detail, width)
        add_rect(deck, slide, left, top, width, row, "surface", "Card")
        add_rect(deck, slide, left, top, 0.07, row, "mood", "Card accent")
        write_text(deck, slide, head_text, left + 0.4, top + 0.22, head, 18, "ink", bold=True, name="Card heading")
        write_text(deck, slide, detail, left + head + 0.8, top + 0.22, text, 16, "body", name="Card text")
        top += row + card_gap
    return top


def panel_fits(deck, lead_text, pairs, height):
    return deck.text_height(lead_text, panel_width - 0.8, 22) + 0.9 <= height and stacked_fits(deck, pairs, height, content_width - panel_width - card_gap)


def draw_panel(deck, slide, lead_text, pairs, top, height):
    deck.last_cards = "panel"
    add_rect(deck, slide, side_margin, top, panel_width, height, "night", "Statement panel")
    add_rect(deck, slide, side_margin, top, panel_width, 0.07, "mood", "Panel accent")
    used = deck.text_height(lead_text, panel_width - 0.8, 22)
    write_text(deck, slide, lead_text, side_margin + 0.4, top + (height - used) / 2, panel_width - 0.8, 22, white, name="Statement")
    left = side_margin + panel_width + card_gap
    draw_card_rows(deck, slide, pairs, top, height, left, content_width - panel_width - card_gap)
