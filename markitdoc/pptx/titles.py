from dataclasses import dataclass
from pptx.enum.text import MSO_ANCHOR

from markitdoc.markup.inline import literal
from markitdoc.pptx.deck import (body_sizes, comfortable_size, key_sentences, place_title, side_margin, standard_size,
                                 text_width, title_fit, write_text)

column_gap, row_gap, subtitle_width = 0.4, 0.45, 9.6
max_per_slide = {"keypoints": 4, "process": 5, "timeline": 6, "figures": 6, "comparison": 7}


@dataclass(frozen=True)
class TitleGroup:
    kicker: str
    title: str
    title_size: int
    title_height: float
    subtitle: str
    subtitle_size: int
    subtitle_height: float

    @property
    def total(self):
        return (0.5 if self.kicker else 0) + self.title_height + (0.35 + self.subtitle_height if self.subtitle else 0)


def slide_titles(source):
    yield source
    while True:
        yield f"{source} (cont.)"


def fit_text(deck, source, width, height, label, cap=standard_size, style=""):
    size = next((size for size in body_sizes if size <= cap and deck.text_height(source, width, size, style) <= height), None)
    if size:
        return source, size
    deck.note(f"{label}: {source}")
    return key_sentences(deck, source, width, height, comfortable_size - 2), comfortable_size - 2


def lead_text(deck, source):
    return fit_text(deck, source, text_width, 1.3, "Lead") if source else ("", 0)


def lead_room(deck, source):
    shown, size = lead_text(deck, source)
    return deck.text_height(shown, text_width, size) + 0.35 if source else 0.0


def draw_lead(deck, slide, source, top):
    shown, size = lead_text(deck, source)
    return top + write_text(deck, slide, shown, side_margin, top, text_width, size, "body", name="Lead") + 0.35 if source else top


def plan_group(deck, kicker, title, subtitle, sizes, width):
    size, shown = title_fit(deck, title, width, sizes, 3, "B")
    height = deck.text_height(shown, width, size, "B", 1.12)
    text, text_size = fit_text(deck, subtitle, min(width, subtitle_width), 1.4, "Subtitle", cap=22) if subtitle else ("", 0)
    sub_height = deck.text_height(text, min(width, subtitle_width), text_size) if subtitle else 0
    return TitleGroup(kicker, shown, size, height, text, text_size, sub_height)


def draw_group(deck, slide, group, left, top, width, roles):
    title_role, kicker_role, subtitle_role = roles
    if group.kicker:
        write_text(deck, slide, literal(group.kicker.upper()), left, top, width, 14, kicker_role, bold=True, name="Kicker")
        top += 0.5
    place_title(deck, slide, group.title, title_role, left, top, width, group.title_height, (group.title_size,), 3, MSO_ANCHOR.TOP)
    if group.subtitle:
        write_text(deck, slide, group.subtitle, left, top + group.title_height + 0.35, min(width, subtitle_width), group.subtitle_size,
                   subtitle_role, name="Subtitle")
