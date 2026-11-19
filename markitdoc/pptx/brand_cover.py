import re

from pptx.enum.text import PP_ALIGN
from pptx.util import Inches

from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import BODY_SIZES, SIDE_MARGIN, SLIDE_WIDTH, draw_footer, key_sentences, title_fit, write_text
from markitdoc.pptx.photos import add_image
from markitdoc.utils.helpers import long_date
from markitdoc.visuals.logos import logo_box

COVER_TITLE_SIZES = (40, 36, 32, 28)
COVER_WIDTH = SLIDE_WIDTH - 2 * SIDE_MARGIN
COVER_LOGO_TOP, COVER_LOGO_SIZE, COVER_STACK_TOP, COVER_STACK_BOTTOM = 0.4, 1.4, 2.0, 4.95
COVER_GAP, TAGLINE_HEIGHT, SUBTITLE_CAP = 0.22, 0.35, 20


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


# sets a slide shape top position in inches
def move(shape, top):
    shape.top = Inches(top)


# chooses a subtitle size that fits the cover area
def subtitle_size(deck, source, height):
    return next((size for size in BODY_SIZES if size <= SUBTITLE_CAP and deck.text_height(source, COVER_WIDTH, size) <= height), 14)


# draws the configured branded cover slide
def draw_brand_cover(deck, block):
    slots = block.slots if block else {}
    slide = deck.presentation.slides[0]
    deck.slide = slide
    tagline = shape_with_text(slide, deck.theme.tagline) if deck.theme.tagline else None
    logo = next((shape for shape in slide.shapes if shape.shape_type == 13 and shape.width == shape.height), None)
    remove_sample_text(slide, deck.theme.sample_texts)
    if logo is not None:
        logo.left, logo.top = Inches((SLIDE_WIDTH - COVER_LOGO_SIZE) / 2), Inches(COVER_LOGO_TOP)
        logo.width = logo.height = Inches(COVER_LOGO_SIZE)
    elif deck.theme.logo:
        width, height = logo_box(deck.theme.logo, COVER_LOGO_SIZE * 3, COVER_LOGO_SIZE)
        add_image(slide, str(deck.theme.logo), (SLIDE_WIDTH - width) / 2, COVER_LOGO_TOP, width, height, deck.theme.brand or "Logo", "Logo")
    title = slots.get("title") or deck.title
    kicker = slots.get("kicker", "")
    subtitle = slots.get("subtitle", "")
    fixed = COVER_STACK_TOP + (0.45 if kicker else 0) + COVER_GAP + (TAGLINE_HEIGHT + COVER_GAP if tagline is not None else 0)
    for sizes in (COVER_TITLE_SIZES[index:] for index in range(len(COVER_TITLE_SIZES))):
        size, shown = title_fit(deck, title, COVER_WIDTH, sizes, 2, "B")
        title_room = deck.text_height(shown, COVER_WIDTH, size, "B", 1.12)
        if not subtitle or deck.text_height(subtitle, COVER_WIDTH, 14) <= COVER_STACK_BOTTOM - fixed - title_room:
            break
    top = COVER_STACK_TOP
    if kicker:
        write_text(deck, slide, literal(kicker.upper()), SIDE_MARGIN, top, COVER_WIDTH, 14, "mood", bold=True, align=PP_ALIGN.CENTER, name="Kicker")
        top += 0.45
    write_text(deck, slide, shown, SIDE_MARGIN, top, COVER_WIDTH, size, "mood", heading=True, leading=1.12, align=PP_ALIGN.CENTER, name="Title")
    top += title_room + COVER_GAP
    if tagline is not None:
        move(tagline, top)
        top += TAGLINE_HEIGHT + COVER_GAP
    if subtitle:
        height = COVER_STACK_BOTTOM - top
        size = subtitle_size(deck, subtitle, height)
        if deck.text_height(subtitle, COVER_WIDTH, size) > height:
            deck.note(f"Subtitle: {subtitle}")
            subtitle = key_sentences(deck, subtitle, COVER_WIDTH, height, size)
        write_text(deck, slide, subtitle, SIDE_MARGIN, top, COVER_WIDTH, size, "body", align=PP_ALIGN.CENTER, name="Subtitle")
    draw_footer(deck, slide)
    date = long_date(deck.meta.get("date", ""))
    if date:
        write_text(deck, slide, literal(date), SLIDE_WIDTH - SIDE_MARGIN - 3.7, 6.45, 3.7, 14, "muted", align=PP_ALIGN.RIGHT, name="Date")
