import re

from markitdoc.markup.inline import plain_text
from markitdoc.pptx.deck import CONTENT_WIDTH, SIDE_MARGIN, WHITE, add_rect, write_text

CARD_GAP, CARD_PRESETS, PANEL_WIDTH = 0.3, ((22, 18), (20, 16), (18, 15), (16, 14)), 4.3
LEADING_FIGURE = re.compile(r"^\s*([~≈<>+\-−]?[$€£¥]?\d[\d.,]*\s?(?:%|[kKmMbBxX]\b|bn\b|tn\b|pts?\b|bps\b)?\+?)\s*(.*)$")
CARD_PATTERN = re.compile(r"^\*\*(.+?)\*\*\s*(?:—|–|:|-)\s*(.+)$")


# parses a short list of bold-label card pairs when its shape matches
def card_pairs(items):
    pairs = [CARD_PATTERN.match(item.source.strip()) for item in items]
    if not 2 <= len(items) <= 6 or not all(item.listed and item.level == 0 for item in items) or not all(pairs):
        return None
    return [(match.group(1), match.group(2)) for match in pairs]


# chooses the number of columns for a card grid
def card_columns(pairs):
    return 3 if len(pairs) in (5, 6) else len(pairs)


# chooses card text sizes that fit the available grid height
def card_preset(deck, pairs, height, columns=None):
    columns = columns or card_columns(pairs)
    rows = (len(pairs) + columns - 1) // columns
    width = (CONTENT_WIDTH - CARD_GAP * (columns - 1)) / columns - 0.6
    for head, text in CARD_PRESETS:
        needed = max(deck.text_height(head_text, width, head, "B") + 0.15 + deck.text_height(detail, width, text) for head_text, detail in pairs)
        if (needed + 0.8) * rows + CARD_GAP * (rows - 1) <= height:
            return head, text, needed + 1.45
    return None


# parses figure values from card headings
def figure_cards(pairs):
    found = [LEADING_FIGURE.match(plain_text(head)) for head, _ in pairs]
    if not all(found):
        return None
    return tuple((match.group(1), match.group(2).strip(" -—:") or match.group(1), detail) for match, (_, detail) in zip(found, pairs))


# returns card arrangements that fit the given space
def card_layouts(deck, pairs, height, preset):
    layouts = {"columns": preset} if preset else {}
    if stacked_fits(deck, pairs, height):
        layouts["rows"] = None
    grid = card_preset(deck, pairs, height, 2) if len(pairs) == 4 else None
    if grid:
        layouts["grid"] = grid
    return layouts


# chooses and draws a card arrangement for the slide
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
    width = (CONTENT_WIDTH - CARD_GAP * (columns - 1)) / columns
    heading_room = max(deck.text_height(head_text, width - 0.6, head, "B") for head_text, _ in pairs)
    top += max(0.0, height - card_height * rows - CARD_GAP * (rows - 1)) * 0.45
    for index, (head_text, detail) in enumerate(pairs):
        left = SIDE_MARGIN + (index % columns) * (width + CARD_GAP)
        card_top = top + (index // columns) * (card_height + CARD_GAP)
        add_rect(deck, slide, left, card_top, width, card_height, "surface", "Card")
        add_rect(deck, slide, left, card_top, width, 0.06, "mood", "Card accent")
        write_text(deck, slide, head_text, left + 0.3, card_top + 0.4, width - 0.6, head, "ink", bold=True, name="Card heading")
        write_text(deck, slide, detail, left + 0.3, card_top + 0.55 + heading_room, width - 0.6, text, "body", name="Card text")
    return top + card_height * rows + CARD_GAP * (rows - 1)


# draws a highlighted takeaway band at the bottom of a slide
def draw_takeaway(deck, slide, items, bottom):
    source = " ".join(item.source for item in items)
    height = deck.text_height(source, CONTENT_WIDTH - 0.6, 16, "B") + 0.4
    add_rect(deck, slide, SIDE_MARGIN, bottom - height, CONTENT_WIDTH, height, "surface", "Takeaway band")
    add_rect(deck, slide, SIDE_MARGIN, bottom - height, 0.07, height, "mood", "Takeaway accent")
    write_text(deck, slide, source, SIDE_MARGIN + 0.35, bottom - height + 0.2, CONTENT_WIDTH - 0.7, 16, "ink", bold=True, name="Takeaway")
    return height


# checks whether a stack of cards fits the available height
def stacked_fits(deck, pairs, height, width=CONTENT_WIDTH):
    return sum(row_height_of(deck, head_text, detail, width) for head_text, detail in pairs) + CARD_GAP * (len(pairs) - 1) <= height


# splits a card row into heading and detail widths
def row_widths(width):
    head = min(3.4, width * 0.36)
    return head, width - head - 1.2


# measures the height needed for a two-column card row
def row_height_of(deck, head_text, detail, width=CONTENT_WIDTH):
    head, text = row_widths(width)
    return max(deck.text_height(head_text, head, 18, "B"), deck.text_height(detail, text, 16)) + 0.44


# draws cards as stacked heading and detail rows
def draw_card_rows(deck, slide, pairs, top, height, left=SIDE_MARGIN, width=CONTENT_WIDTH):
    head, text = row_widths(width)
    total = sum(row_height_of(deck, head_text, detail, width) for head_text, detail in pairs) + CARD_GAP * (len(pairs) - 1)
    top += max(0.0, height - total) * 0.45
    for head_text, detail in pairs:
        row = row_height_of(deck, head_text, detail, width)
        add_rect(deck, slide, left, top, width, row, "surface", "Card")
        add_rect(deck, slide, left, top, 0.07, row, "mood", "Card accent")
        write_text(deck, slide, head_text, left + 0.4, top + 0.22, head, 18, "ink", bold=True, name="Card heading")
        write_text(deck, slide, detail, left + head + 0.8, top + 0.22, text, 16, "body", name="Card text")
        top += row + CARD_GAP
    return top


# checks whether a statement panel and cards fit together
def panel_fits(deck, lead_text, pairs, height):
    return deck.text_height(lead_text, PANEL_WIDTH - 0.8, 22) + 0.9 <= height and stacked_fits(deck, pairs, height, CONTENT_WIDTH - PANEL_WIDTH - CARD_GAP)


# draws a statement panel beside its supporting cards
def draw_panel(deck, slide, lead_text, pairs, top, height):
    deck.last_cards = "panel"
    add_rect(deck, slide, SIDE_MARGIN, top, PANEL_WIDTH, height, "night", "Statement panel")
    add_rect(deck, slide, SIDE_MARGIN, top, PANEL_WIDTH, 0.07, "mood", "Panel accent")
    used = deck.text_height(lead_text, PANEL_WIDTH - 0.8, 22)
    write_text(deck, slide, lead_text, SIDE_MARGIN + 0.4, top + (height - used) / 2, PANEL_WIDTH - 0.8, 22, WHITE, name="Statement")
    left = SIDE_MARGIN + PANEL_WIDTH + CARD_GAP
    draw_card_rows(deck, slide, pairs, top, height, left, CONTENT_WIDTH - PANEL_WIDTH - CARD_GAP)
