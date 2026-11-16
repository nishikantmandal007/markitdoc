import logging
import math
import re

from PIL import Image
from pptx.enum.text import PP_ALIGN

from markitdoc.markup.inline import inline_maths, literal
from markitdoc.pptx.deck import Item, body_height, body_top, content_width, slide_width, visual_left, visual_width, write_text
from markitdoc.pptx.diagrams import flow_graph
from markitdoc.pptx.flow_reader import Piece
from markitdoc.pptx.photos import add_image, contained, image_ratio, photo_for
from markitdoc.visuals.diagrams import diagram_as_text, render_diagram
from markitdoc.visuals.equations import equation_png, mathtext_ready
from markitdoc.visuals.infographics import render_infographic

logger = logging.getLogger(__name__)

equation_zoom = 2.0
caption_height, credit_height = 0.5, 0.3
code_sizes, code_leading, code_padding = (16, 14), 1.25, 0.25


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
