import logging
import math
import re

from PIL import Image
from pptx.enum.text import PP_ALIGN

from markitdoc.markup.inline import inline_maths, literal
from markitdoc.pptx.deck import BODY_HEIGHT, BODY_TOP, CONTENT_WIDTH, SLIDE_WIDTH, VISUAL_LEFT, VISUAL_WIDTH, Item, write_text
from markitdoc.pptx.diagrams import flow_graph
from markitdoc.pptx.flow.reader import Piece
from markitdoc.pptx.photos import add_image, contained, image_ratio, photo_credit, photo_for
from markitdoc.visuals.diagrams import diagram_as_text, render_diagram
from markitdoc.visuals.equations import equation_png, mathtext_ready
from markitdoc.visuals.infographics import render_infographic

logger = logging.getLogger(__name__)

EQUATION_ZOOM = 2.0
CAPTION_HEIGHT, CREDIT_HEIGHT = 0.5, 0.3
CODE_SIZES, CODE_LEADING, CODE_PADDING = (16, 14), 1.25, 0.25


# estimates wrapped line counts for a code sample at a font size
def code_layout(deck, lines, size, width):
    deck.measurer.set_font("Mono", "", size)
    capacity = max(10, int(width * 25.4 * 0.93 / deck.measurer.get_string_width("M")))
    return [max(1, math.ceil(len(line) / capacity)) for line in lines]


# splits code lines into slide-sized groups
def code_chunks(deck, lines, size, room):
    counts = code_layout(deck, lines, size, CONTENT_WIDTH - 2 * CODE_PADDING)
    limit = max(1, int(room / (size * CODE_LEADING / 72)))
    chunks, current, used = [], [], 0
    for line, count in zip(lines, counts):
        if current and used + count > limit:
            chunks.append(current)
            current, used = [], 0
        current.append(line)
        used += count
    chunks.append(current)
    return chunks, counts, limit


# chooses the more readable orientation for a flowchart image
def landscape_diagram(deck, source):
    path = render_diagram(source, deck.theme)
    direction = re.match(r"\s*(flowchart|graph)\s+(TB|TD|BT|LR|RL)\b", source)
    if not path or not direction:
        return path
    turned = render_diagram(source[:direction.start(2)] + ("LR" if direction.group(2) in ("TB", "TD", "BT") else "TB")
                            + source[direction.end(2):], deck.theme)
    return max((path, turned) if turned else (path,), key=lambda option: diagram_scale(option))


# measures how well a diagram image fits slide content
def diagram_scale(path):
    with Image.open(path) as picture:
        return min(CONTENT_WIDTH / picture.width, (BODY_HEIGHT - 0.4) / picture.height)


# converts infographic labels and descriptions into slide bullet items
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


# chooses the position and size for a slide visual
def visual_box(side, width_limit=None):
    if side:
        return VISUAL_LEFT, BODY_TOP, VISUAL_WIDTH, BODY_HEIGHT
    width = width_limit or CONTENT_WIDTH
    return (SLIDE_WIDTH - width) / 2, BODY_TOP, width, BODY_HEIGHT


# adds a fitted picture and optional caption to the slide
def place_picture(deck, slide, path, box, alt, caption=""):
    left, top, width, height = box
    room = height - (CAPTION_HEIGHT if caption else 0)
    add_image(slide, str(path), *contained(image_ratio(path), left, top, width, room), alt)
    if caption:
        write_text(deck, slide, literal(caption), left, top + room + 0.1, width, 14, "muted", italic=True, align=PP_ALIGN.CENTER, name="Caption")


# centers a rendered equation image inside its slide box
def place_equation(deck, slide, piece, box):
    left, top, width, height = box
    stream, (natural_width, natural_height) = equation_png(deck, piece.data)
    scale = min(EQUATION_ZOOM, width * 0.9 / (natural_width / 25.4), height * 0.8 / (natural_height / 25.4))
    drawn_width, drawn_height = natural_width / 25.4 * scale, natural_height / 25.4 * scale
    add_image(slide, stream, left + (width - drawn_width) / 2, top + (height - drawn_height) / 2, drawn_width, drawn_height,
              f"Equation: {piece.data}")


# adds a photo to the slide with its caption and credit
def place_figure(deck, slide, piece, box):
    path, caption, credit, source = deck.figures[piece.data]
    left, top, width, height = box
    photo_height = height - CAPTION_HEIGHT - CREDIT_HEIGHT
    add_image(slide, photo_credit, photo_for(deck, path, width, photo_height), left, top, width, photo_height, caption or "Photograph")
    write_text(deck, slide, literal(caption), left, top + photo_height + 0.08, width, 14, "muted", italic=True, name="Caption")
    photo_credit(deck, slide, credit, source, left, top + photo_height + CAPTION_HEIGHT, width, 10, "muted", PP_ALIGN.LEFT)


# prepares a visual piece for slide rendering
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


# turns an unsupported visual into readable slide content
def visual_fallback(deck, piece):
    if piece.kind == "diagram":
        lines = diagram_as_text(piece.data)
        return [Item(line, "bullet") for line in lines] or [Item(piece.data.strip(), "paragraph")]
    if piece.kind == "infographic":
        return infographic_items(piece.data)
    if piece.kind == "equation":
        return [Item(literal(inline_maths(mathtext_ready(piece.data))))]
    return []
