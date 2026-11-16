from pptx.enum.text import PP_ALIGN
from pptx.util import Inches

from markitdoc.utils.helpers import long_date
from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import body_sizes, draw_footer, key_sentences, side_margin, slide_width, title_fit, write_text

cover_title_sizes = (40, 36, 32, 28)
cover_width = slide_width - 2 * side_margin
cover_logo_top, cover_logo_size, cover_stack_top, cover_stack_bottom = 0.4, 1.4, 2.0, 4.95
cover_gap, tagline_height, subtitle_cap = 0.22, 0.35, 20


def shape_with_text(slide, start):
    return next((shape for shape in slide.shapes if shape.has_text_frame and shape.text_frame.text.strip().startswith(start)), None)


def remove_sample_text(slide, sample_texts):
    for start in sample_texts:
        shape = shape_with_text(slide, start)
        if shape is not None:
            shape._element.getparent().remove(shape._element)


def move(shape, top):
    shape.top = Inches(top)


def subtitle_size(deck, source, height):
    return next((size for size in body_sizes if size <= subtitle_cap and deck.text_height(source, cover_width, size) <= height), 14)


def draw_brand_cover(deck, block):
    slots = block.slots if block else {}
    slide = deck.presentation.slides[0]
    deck.slide = slide
    tagline = shape_with_text(slide, deck.theme.tagline) if deck.theme.tagline else None
    logo = next(shape for shape in slide.shapes if shape.shape_type == 13 and shape.width == shape.height)
    remove_sample_text(slide, deck.theme.sample_texts)
    logo.left, logo.top = Inches((slide_width - cover_logo_size) / 2), Inches(cover_logo_top)
    logo.width = logo.height = Inches(cover_logo_size)
    title = slots.get("title") or deck.title
    kicker = slots.get("kicker", "")
    subtitle = slots.get("subtitle", "")
    fixed = cover_stack_top + (0.45 if kicker else 0) + cover_gap + (tagline_height + cover_gap if tagline is not None else 0)
    for sizes in (cover_title_sizes[index:] for index in range(len(cover_title_sizes))):
        size, shown = title_fit(deck, title, cover_width, sizes, 2, "B")
        title_room = deck.text_height(shown, cover_width, size, "B", 1.12)
        if not subtitle or deck.text_height(subtitle, cover_width, 14) <= cover_stack_bottom - fixed - title_room:
            break
    top = cover_stack_top
    if kicker:
        write_text(deck, slide, literal(kicker.upper()), side_margin, top, cover_width, 14, "mood", bold=True, align=PP_ALIGN.CENTER, name="Kicker")
        top += 0.45
    write_text(deck, slide, shown, side_margin, top, cover_width, size, "mood", heading=True, leading=1.12, align=PP_ALIGN.CENTER, name="Title")
    top += title_room + cover_gap
    if tagline is not None:
        move(tagline, top)
        top += tagline_height + cover_gap
    if subtitle:
        height = cover_stack_bottom - top
        size = subtitle_size(deck, subtitle, height)
        if deck.text_height(subtitle, cover_width, size) > height:
            deck.note(f"Subtitle: {subtitle}")
            subtitle = key_sentences(deck, subtitle, cover_width, height, size)
        write_text(deck, slide, subtitle, side_margin, top, cover_width, size, "body", align=PP_ALIGN.CENTER, name="Subtitle")
    draw_footer(deck, slide)
    date = long_date(deck.meta.get("date", ""))
    if date:
        write_text(deck, slide, literal(date), slide_width - side_margin - 3.7, 6.45, 3.7, 14, "muted", align=PP_ALIGN.RIGHT, name="Date")
