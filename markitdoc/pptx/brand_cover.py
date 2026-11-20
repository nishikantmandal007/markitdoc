import re

from pptx.enum.shapes import MSO_SHAPE_TYPE

from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import CONTENT_WIDTH, SIDE_MARGIN, add_rect, draw_footer, title_fit, write_text
from markitdoc.pptx.designed.titles import fit_text
from markitdoc.pptx.photos import add_image
from markitdoc.utils.helpers import long_date
from markitdoc.visuals.logos import logo_box, logo_ratio, logo_row

COVER_TITLE_SIZES = (52, 48, 44, 40, 36, 32)
COVER_WIDTH = 11.3
COVER_LOGO_TOP, COVER_LOGO_HEIGHT, COVER_STACK_TOP = 0.55, 0.55, 1.68
PARTNER_ROW_HEIGHT, PARTNER_GAP, PARTNER_TOP = 0.44, 0.34, 5.55
COVER_RULE_TOP = 6.55


# finds the first slide shape whose text starts with a value
def shape_with_text(slide, start):
    wanted = letters_of(start)
    return next((shape for shape in slide.shapes if shape.has_text_frame and letters_of(shape.text_frame.text).startswith(wanted)), None)


# the letters and digits of a text in lower case, so punctuation and spacing differences between a theme file and a master match
def letters_of(text):
    return re.sub(r"\W+", "", text).lower()


# removes template shapes that contain sample text
def remove_sample_text(slide, sample_texts):
    for start in sample_texts:
        shape = shape_with_text(slide, start)
        if shape is not None:
            shape._element.getparent().remove(shape._element)


# adds brand marks and address below the main cover composition
def company_details(deck, slide):
    ratios = [logo_ratio(path) for path in deck.theme.partners]
    height = PARTNER_ROW_HEIGHT
    places = logo_row(ratios, CONTENT_WIDTH, height, PARTNER_GAP)
    while places and places[-1][1] + height > COVER_RULE_TOP - PARTNER_TOP - 0.12:
        height *= 0.85
        places = logo_row(ratios, CONTENT_WIDTH, height, PARTNER_GAP * height / PARTNER_ROW_HEIGHT)
    for path, (x, top, width, height) in zip(deck.theme.partners, places):
        add_image(slide, str(path), SIDE_MARGIN + x, PARTNER_TOP + top, width, height, "Partner logo", "Partner logo")
    if deck.theme.address:
        write_text(deck, slide, literal("  ·  ".join(deck.theme.address)), SIDE_MARGIN, 5.14, CONTENT_WIDTH, 9.5, "muted", name="Address")


# uses the same title-led company cover with or without the registered master
def draw_brand_cover(deck, block, slide=None):
    slots = block.slots if block else {}
    tagline = deck.theme.tagline
    if slide is None:
        slide = deck.presentation.slides[0]
        deck.slide = slide
        remove_sample_text(slide, (*deck.theme.sample_texts, *((tagline,) if tagline else ())))
        for shape in list(slide.shapes):
            if (deck.theme.logo and shape.shape_type == MSO_SHAPE_TYPE.PICTURE and shape.top.inches < 3
                    or deck.theme.partners and shape.top.inches >= 5 and shape.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.FREEFORM)):
                shape._element.getparent().remove(shape._element)
    if deck.theme.logo:
        width, height = logo_box(deck.theme.logo, 2.2, COVER_LOGO_HEIGHT)
        add_image(slide, str(deck.theme.logo), SIDE_MARGIN, COVER_LOGO_TOP, width, height, deck.theme.brand or "Logo", "Logo")
    title = slots.get("title") or deck.title
    top = COVER_STACK_TOP
    if kicker := slots.get("kicker"):
        write_text(deck, slide, literal(kicker.upper()), SIDE_MARGIN, top, COVER_WIDTH, 13, "mood", bold=True, name="Kicker")
        top += 0.37
    size, shown = title_fit(deck, title, COVER_WIDTH, COVER_TITLE_SIZES, 2, "B")
    top += write_text(deck, slide, shown, SIDE_MARGIN, top, COVER_WIDTH, size, "ink",
                      heading=True, leading=1.12, name="Title") + 0.20
    if subtitle := slots.get("subtitle"):
        subtitle, size = fit_text(deck, subtitle, COVER_WIDTH, max(0.55, 4.82 - top), "Subtitle", cap=18)
        top += write_text(deck, slide, subtitle, SIDE_MARGIN, top, COVER_WIDTH, size, "body", name="Subtitle") + 0.18
    if tagline:
        write_text(deck, slide, literal(tagline), SIDE_MARGIN, min(top, 4.85), COVER_WIDTH, 11, "mood", name="Tagline")
    if slots.get("variant") == "company" or deck.branded:
        company_details(deck, slide)
    add_rect(deck, slide, SIDE_MARGIN, COVER_RULE_TOP, CONTENT_WIDTH, 0.015, "rule", "Cover rule")
    if date := long_date(deck.meta.get("date", "")):
        write_text(deck, slide, literal(date), SIDE_MARGIN, 6.66, 4, 11, "muted", name="Date")
    draw_footer(deck, slide)
