from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from markitdoc.pptx.deck import CONTENT_WIDTH, SIDE_MARGIN, configure_frame, fill_items, fitted_items, stack_height, write_items
from markitdoc.themes.theme_constants import POINT_MM

MM_PER_INCH = 25.4
BOX_PADDING_MM = 5
BOX_MIN_ROOM = 0.8


# draws a styled box as a rounded rectangle with the look's fill, border and padding, holding the items; returns its height
def place_box(deck, slide, look, items, top, room):
    pad = (BOX_PADDING_MM if look.padding is None else look.padding) / MM_PER_INCH
    width = min(CONTENT_WIDTH, deck.styles.length(look.width, CONTENT_WIDTH * MM_PER_INCH) / MM_PER_INCH) if look.width else CONTENT_WIDTH
    shown, size = fitted_items(deck, list(items), width - 2 * pad, max(BOX_MIN_ROOM, room - 2 * pad), "Full text")
    height = min(room, stack_height(deck, shown, width - 2 * pad, size) + 2 * pad)
    rounded = bool(look.radius)
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE, Inches(SIDE_MARGIN), Inches(top),
                                   Inches(width), Inches(height))
    shape.name = "Box"
    shape._element.remove(shape._element.find(qn("p:style")))
    if rounded:
        shape.adjustments[0] = min(0.5, look.radius / (min(width, height) * MM_PER_INCH))
    if look.fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = deck.color(look.fill)
    else:
        shape.fill.background()
    if look.borders:
        line, rgb = max(look.borders.values(), key=lambda edge: edge[0])
        shape.line.color.rgb, shape.line.width = deck.color(rgb), Pt(line / POINT_MM)
    else:
        shape.line.fill.background()
    configure_frame(shape.text_frame, MSO_ANCHOR.TOP, pad)
    fill_items(deck, shape.text_frame, shown, size)
    return height


# draws items as side-by-side text frames whose widths follow the column weights, at one text size; returns the tallest frame
def place_columns(deck, slide, weights, gap, columns, top, room):
    gap = gap / MM_PER_INCH
    total = CONTENT_WIDTH - gap * (len(columns) - 1)
    widths = [total * weight / sum(weights) for weight in weights]
    fitted = [fitted_items(deck, list(items), width, room, "Full text") for items, width in zip(columns, widths)]
    size, left, tallest = min(found[1] for found in fitted), SIDE_MARGIN, 0
    for (shown, _), width in zip(fitted, widths):
        tallest = max(tallest, write_items(deck, slide, shown, left, top, width, size, name="Column"))
        left += width + gap
    return tallest
