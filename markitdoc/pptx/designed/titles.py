from dataclasses import dataclass

from pptx.enum.text import MSO_ANCHOR

from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import (
    BODY_SIZES,
    COMFORTABLE_SIZE,
    SIDE_MARGIN,
    STANDARD_SIZE,
    TEXT_WIDTH,
    key_sentences,
    place_title,
    title_fit,
    write_text,
)

COLUMN_GAP, ROW_GAP, SUBTITLE_WIDTH = 0.4, 0.45, 9.6
MAX_PER_SLIDE = {"keypoints": 4, "process": 5, "timeline": 6, "figures": 6, "comparison": 7}


@dataclass(frozen=True)
class TitleGroup:
    kicker: str
    title: str
    title_size: int
    title_height: float
    subtitle: str
    subtitle_size: int
    subtitle_height: float

    # returns the total height of the title group
    @property
    def total(self):
        return (0.5 if self.kicker else 0) + self.title_height + (0.35 + self.subtitle_height if self.subtitle else 0)


# yields the supplied title followed by continuation titles
def slide_titles(source):
    yield source
    while True:
        yield f"{source} (cont.)"


# chooses a text size or shortens the text to fit its box
def fit_text(deck, source, width, height, label, cap=STANDARD_SIZE, style=""):
    size = next((size for size in BODY_SIZES if size <= cap and deck.text_height(source, width, size, style) <= height), None)
    if size:
        return source, size
    if label:
        deck.note(f"{label}: {source}")
    return key_sentences(deck, source, width, height, COMFORTABLE_SIZE - 2), COMFORTABLE_SIZE - 2


# fits lead text to its standard slide box
def lead_text(deck, source):
    return fit_text(deck, source, TEXT_WIDTH, 1.3, "Lead") if source else ("", 0)


# measures the space needed for the slide lead text
def lead_room(deck, source):
    if not source:
        return 0.0
    shown, size = fit_text(deck, source, TEXT_WIDTH, 1.3, "")
    return deck.text_height(shown, TEXT_WIDTH, size) + 0.35


# draws fitted lead text and returns the next available position
def draw_lead(deck, slide, source, top):
    shown, size = lead_text(deck, source)
    return top + write_text(deck, slide, shown, SIDE_MARGIN, top, TEXT_WIDTH, size, "body", name="Lead") + 0.35 if source else top


# fits a title group and measures its total height
def plan_group(deck, kicker, title, subtitle, sizes, width):
    size, shown = title_fit(deck, title, width, sizes, 3, "B")
    height = deck.text_height(shown, width, size, "B", 1.12)
    text, text_size = fit_text(deck, subtitle, min(width, SUBTITLE_WIDTH), 1.4, "Subtitle", cap=22) if subtitle else ("", 0)
    sub_height = deck.text_height(text, min(width, SUBTITLE_WIDTH), text_size) if subtitle else 0
    return TitleGroup(kicker, shown, size, height, text, text_size, sub_height)


# draws the kicker, title, and subtitle for an opener
def draw_group(deck, slide, group, left, top, width, roles):
    title_role, kicker_role, subtitle_role = roles
    if group.kicker:
        write_text(deck, slide, literal(group.kicker.upper()), left, top, width, 14, kicker_role, bold=True, name="Kicker")
        top += 0.5
    place_title(deck, slide, group.title, title_role, left, top, width, group.title_height, (group.title_size,), 3, MSO_ANCHOR.TOP)
    if group.subtitle:
        write_text(deck, slide, group.subtitle, left, top + group.title_height + 0.35, min(width, SUBTITLE_WIDTH), group.subtitle_size,
                   subtitle_role, name="Subtitle")
