import io
from dataclasses import replace
from pathlib import Path

from fpdf.enums import MethodReturnValue, XPos, YPos
from PIL import Image, ImageDraw

from markitdoc.markup.elements import image_size
from markitdoc.models.attributes import parse_attributes
from markitdoc.options import options_in_use
from markitdoc.pdf.flow.pages import BODY_SIZE, FlowPages, measured
from markitdoc.pdf.pages import escaped
from markitdoc.themes.theme_constants import IMAGE_SIDES

FLOAT_GAP = 5
FLOAT_WRAPS = ("paragraph_open", "bullet_list_open", "ordered_list_open")
BLOCK_TOKENS = ("fence", "hr", "code_block", "math_block")
PLACEHOLDER_SHARE = 0.5
PLACEHOLDER_WIDTH = 0.6
CAPTION_SCALE = 0.85


# draws one page segment of a box or paragraph frame: fill, rounded corners and the border edges that belong to this segment
def draw_frame(pdf: FlowPages, left, width, top, bottom, look, first=True, last=True):
    height, radius = bottom - top, look.radius or 0
    corners = tuple(name for name, shown in (("TOP_LEFT", first), ("TOP_RIGHT", first), ("BOTTOM_LEFT", last), ("BOTTOM_RIGHT", last))
                    if shown) if radius else ()
    edges = {side: edge for side, edge in (look.borders or {}).items() if (first or side != "top") and (last or side != "bottom")}
    with pdf.local_context():
        if look.fill:
            pdf.set_fill_color(*look.fill)
            pdf.rect(left, top, width, height, "F", round_corners=corners or False, corner_radius=radius)
        if len(edges) == 4 and len(set(edges.values())) == 1:
            line, rgb = edges["top"]
            pdf.set_draw_color(*rgb)
            pdf.set_line_width(line)
            pdf.rect(left + line / 2, top + line / 2, width - line, height - line, "D", round_corners=corners or False,
                     corner_radius=max(radius - line / 2, 0))
            return
        for side, (line, rgb) in edges.items():
            pdf.set_fill_color(*rgb)
            pdf.rect(*{"top": (left, top, width, line), "bottom": (left, bottom - line, width, line), "left": (left, top, line, height),
                       "right": (left + width - line, top, line, height)}[side], "F")


# the vertical extent of drawn content on each page it covers, found by drawing it on a measuring probe: (extents, height, overflowed)
def page_extents(pdf: FlowPages, draw):
    extents = []

    def run(probe):
        top = [probe.get_y()]

        def ending(y):
            extents.append((top[0], min(y, probe.page_break_trigger)))
            top[0] = probe.t_margin

        probe.page_ends.append(ending)
        draw(probe)
        probe.page_ends.remove(ending)
        extents.append((top[0], probe.get_y()))

    height, overflowed = measured(pdf, run)
    return extents, height, overflowed


# ends the wrap of text around a floated image, moving below the image when asked
def end_float(pdf: FlowPages, move_down):
    bottom, page, margins = pdf.floating
    pdf.floating = None
    pdf.set_left_margin(margins[0])
    pdf.set_right_margin(margins[1])
    if move_down and pdf.page_no() == page:
        pdf.set_y(max(pdf.get_y(), bottom))
    pdf.set_x(pdf.l_margin)


# checks a top-level token against a floated image: other blocks than paragraphs and lists move below it, text past its end stops wrapping
def float_check(pdf: FlowPages, token):
    if not pdf.floating or token.level != 0 or not (token.type.endswith("_open") or token.type in BLOCK_TOKENS):
        return
    if token.type not in FLOAT_WRAPS:
        end_float(pdf, True)
    elif pdf.page_no() != pdf.floating[1] or pdf.get_y() >= pdf.floating[0]:
        end_float(pdf, False)


# a copy of the image with its corners rounded to a radius in mm at a drawn width in mm, as PNG bytes
def rounded_png(path, radius, width):
    with Image.open(path) as picture:
        picture = picture.convert("RGBA")
    mask = Image.new("L", picture.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *picture.size), radius=radius / width * picture.width, fill=255)
    picture.putalpha(mask)
    data = io.BytesIO()
    picture.save(data, "PNG")
    data.seek(0)
    return data


# draws an image written with a file path, floated to a side or centred, with its caption; a missing file shows a framed placeholder
def add_picture(pdf: FlowPages, found):
    alt, source, written = found.group(1), found.group(2), found.group(3) or ""
    attributes = parse_attributes(written)
    look = pdf.styles.look("figure", attributes.classes, attributes.values, context=pdf.context)
    folders = options_in_use().style_folders
    path = (Path(folders[0]) if folders else Path()) / source
    natural = image_size(path)
    asked = pdf.styles.length(look.width, pdf.area) if look.width else None
    width = min(asked or (natural[0] if natural else pdf.area * PLACEHOLDER_WIDTH), pdf.area)
    height = width * natural[1] / natural[0] if natural else width * PLACEHOLDER_SHARE
    caption = str(attributes.values.get("caption", ""))
    side = str(attributes.values.get("side", "")).lower()
    pdf.set_font("Brand", "I", BODY_SIZE * pdf.scale * CAPTION_SCALE)
    caption_height = len(pdf.multi_cell(width, BODY_SIZE * pdf.scale * 0.45, escaped(caption), markdown=True, dry_run=True,
                                        output=MethodReturnValue.LINES)) * BODY_SIZE * pdf.scale * 0.45 + 1.5 if caption else 0
    if pdf.will_page_break(height + caption_height + 2):
        pdf.add_page()
    left = pdf.l_margin + (pdf.area - width if side == "right" else 0 if side == "left" else (pdf.area - width) / 2)
    top = pdf.get_y()
    if natural:
        pdf.image(rounded_png(path, look.radius, width) if look.radius else str(path), x=left, y=top, w=width, h=height, alt_text=alt)
        frame = replace(look, fill=None)
    else:
        frame = replace(look, fill=look.fill or pdf.theme.rgb("surface"), borders=look.borders or pdf.styles.edges_of({"border": "thin"}))
        draw_frame(pdf, left, width, top, top + height, frame)
        pdf.set_font("Brand", "", BODY_SIZE * pdf.scale * 0.9)
        pdf.set_text_color(*pdf.theme.rgb("muted"))
        pdf.set_xy(left + 2, top + height / 2 - 3)
        pdf.multi_cell(width - 4, 5, escaped(alt or source), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if natural and frame.borders:
        draw_frame(pdf, left, width, top, top + height, frame)
    if caption:
        pdf.set_font("Brand", "I", BODY_SIZE * pdf.scale * CAPTION_SCALE)
        pdf.set_text_color(*pdf.theme.rgb("muted"))
        pdf.set_xy(left, top + height + 1.5)
        pdf.multi_cell(width, BODY_SIZE * pdf.scale * 0.45, escaped(caption), markdown=True, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    bottom = top + height + caption_height
    if side in IMAGE_SIDES:
        margins = (pdf.l_margin, pdf.r_margin)
        pdf.floating = (bottom + 2, pdf.page_no(), margins)
        if side == "right":
            pdf.set_right_margin(pdf.r_margin + width + FLOAT_GAP)
        else:
            pdf.set_left_margin(pdf.l_margin + width + FLOAT_GAP)
        pdf.set_xy(pdf.l_margin, top)
        return
    pdf.set_xy(pdf.l_margin, bottom + 3)
