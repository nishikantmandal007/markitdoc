from pathlib import Path

from lxml import etree
from PIL import Image
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches

from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import add_rect, place_title, side_margin, slide_height, slide_width, soft_white, title_sizes, write_text
from markitdoc.visuals.photos import fitted_image

photo_width_limit = 2400


def send_to_back(slide, picture):
    slide.shapes._spTree.insert(2, picture._element)


def add_image(slide, source, left, top, width, height, alt, name="Picture"):
    picture = slide.shapes.add_picture(source, Inches(left), Inches(top), Inches(width), Inches(height))
    picture.name = name
    picture._element.nvPicPr.cNvPr.set("descr", alt)
    return picture


def image_ratio(source):
    with Image.open(source) as picture:
        return picture.width / picture.height


def contained(ratio, left, top, width, height):
    drawn_width, drawn_height = (width, width / ratio) if width / height < ratio else (height * ratio, height)
    return left + (width - drawn_width) / 2, top + (height - drawn_height) / 2, drawn_width, drawn_height


def overlay(deck, top, bottom, start=0.0):
    return ((start, 1.0, top, bottom, deck.theme.rgb("night")),)


def full_bleed(deck, slide, image, fades, alt):
    picture = add_image(slide, photo_for(deck, image[0], slide_width, slide_height, fades), 0, 0, slide_width, slide_height, alt,
                        "Background photo")
    send_to_back(slide, picture)
    write_text(deck, slide, literal(image[2]), slide_width - side_margin - 6, 7.05, 6, 10, soft_white, align=PP_ALIGN.RIGHT, name="Credit")


def half_bleed(deck, slide, image, alt):
    side = deck.photo_side
    deck.photo_side = "left" if side == "right" else "right"
    half = slide_width / 2
    left = half if side == "right" else 0
    add_image(slide, photo_for(deck, image[0], half, slide_height, overlay(deck, 0.0, 0.6, 0.82)), left, 0, half, slide_height, alt,
              "Side photo")
    write_text(deck, slide, literal(image[2]), left + 0.3, 7.05, half - 0.6, 10, soft_white, align=PP_ALIGN.RIGHT, name="Credit")
    return (side_margin if side == "right" else half + 0.6), half - 1.2


def side_title(deck, slide, title, left, width, role="ink"):
    size, height = place_title(deck, slide, title, role, left, 0.65, width, 2.2, title_sizes + (22, 20), 4, MSO_ANCHOR.TOP)
    add_rect(deck, slide, left, 0.65 + height + 0.18, 1.2, 0.04, "mood", "Title rule")
    return 0.65 + height + 0.55


def photo_for(deck, path, width, height, fades=()):
    fitted = Path(fitted_image(Path(path), width * 100, height * 100, deck.work_folder, fades, deck.photos, deck.theme))
    with Image.open(fitted) as picture:
        if picture.width > photo_width_limit:
            picture.resize((photo_width_limit, round(picture.height * photo_width_limit / picture.width)), Image.LANCZOS).save(
                fitted, "JPEG", quality=88)
    return str(fitted)


def add_fade(slide):
    element = slide._element
    transition = etree.Element(qn("p:transition"), spd="fast")
    etree.SubElement(transition, qn("p:fade"))
    anchor = element.find(qn("p:clrMapOvr"))
    (anchor if anchor is not None else element.find(qn("p:cSld"))).addnext(transition)
