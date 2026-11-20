from pathlib import Path

from lxml import etree
from PIL import Image
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches

from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import SIDE_MARGIN, SLIDE_HEIGHT, SLIDE_WIDTH, SOFT_WHITE, TITLE_SIZES, add_rect, place_title, write_text
from markitdoc.visuals.photo_fit import fitted_image

PHOTO_WIDTH_LIMIT = 2400


# moves a picture behind other slide content
def send_to_back(slide, picture):
    slide.shapes._spTree.insert(2, picture._element)


# adds a picture to a slide and sets its description
def add_image(slide, source, left, top, width, height, alt, name="Picture"):
    picture = slide.shapes.add_picture(source, Inches(left), Inches(top), Inches(width), Inches(height))
    picture.name = name
    picture._element.nvPicPr.cNvPr.set("descr", alt)
    return picture


# returns an image width-to-height ratio
def image_ratio(source):
    with Image.open(source) as picture:
        return picture.width / picture.height


# fits an image inside a box without changing its proportions
def contained(ratio, left, top, width, height):
    drawn_width, drawn_height = (width, width / ratio) if width / height < ratio else (height * ratio, height)
    return left + (width - drawn_width) / 2, top + (height - drawn_height) / 2, drawn_width, drawn_height


# adds a translucent color overlay to a slide image
def overlay(deck, top, bottom, start=0.0):
    return ((start, 1.0, top, bottom, deck.theme.rgb("night")),)


# links small photo credit text to its attribution while preserving its colour over the image
def photo_credit(deck, slide, credit, source, left, top, width, size, role, align=PP_ALIGN.RIGHT):
    write_text(deck, slide, literal(credit), left, top, width, size, role, align=align, name="Credit")
    slide.shapes[-1].click_action.hyperlink.address = source


# places an image across the full slide with an optional overlay
def full_bleed(deck, slide, image, fades, alt):
    picture = add_image(slide, photo_for(deck, image[0], SLIDE_WIDTH, SLIDE_HEIGHT, fades), 0, 0, SLIDE_WIDTH, SLIDE_HEIGHT, alt,
                        "Background photo")
    send_to_back(slide, picture)
    photo_credit(deck, slide, image[2], image[3], SLIDE_WIDTH - SIDE_MARGIN - 6, 7.05, 6, 10, SOFT_WHITE)


# places an image beside a text area on the slide
def half_bleed(deck, slide, image, alt):
    side = deck.photo_side
    deck.photo_side = "left" if side == "right" else "right"
    half = SLIDE_WIDTH / 2
    left = half if side == "right" else 0
    add_image(slide, photo_for(deck, image[0], half, SLIDE_HEIGHT, overlay(deck, 0.0, 0.6, 0.82)), left, 0, half, SLIDE_HEIGHT, alt,
              "Side photo")
    photo_credit(deck, slide, image[2], image[3], left + 0.3, 7.05, half - 0.6, 10, SOFT_WHITE)
    return (SIDE_MARGIN if side == "right" else half + 0.6), half - 1.2


# places a slide title within the available text column
def side_title(deck, slide, title, left, width, role="ink"):
    size, height = place_title(deck, slide, title, role, left, 0.65, width, 2.2, TITLE_SIZES + (22, 20), 4, MSO_ANCHOR.TOP)
    add_rect(deck, slide, left, 0.65 + height + 0.18, 1.2, 0.04, "mood", "Title rule")
    return 0.65 + height + 0.55


# returns the photo assigned to a designed block
def photo_for(deck, path, width, height, fades=()):
    fitted = Path(fitted_image(Path(path), width * 100, height * 100, deck.work_folder, fades, deck.photos, deck.theme))
    with Image.open(fitted) as picture:
        if picture.width > PHOTO_WIDTH_LIMIT:
            picture.resize((PHOTO_WIDTH_LIMIT, round(picture.height * PHOTO_WIDTH_LIMIT / picture.width)), Image.LANCZOS).save(
                fitted, "JPEG", quality=88)
    return str(fitted)


# adds a vertical color fade to a slide image
def add_fade(slide):
    element = slide._element
    transition = etree.Element(qn("p:transition"), spd="fast")
    etree.SubElement(transition, qn("p:fade"))
    anchor = element.find(qn("p:clrMapOvr"))
    (anchor if anchor is not None else element.find(qn("p:cSld"))).addnext(transition)
