import logging
import tempfile
import time
from pathlib import Path

from markitdoc.markup.blocks import as_flow, balanced, prepared
from markitdoc.markup.inline import plain_text
from markitdoc.models.document import Document
from markitdoc.pptx.brand_cover import draw_brand_cover
from markitdoc.pptx.deck import Deck, Item
from markitdoc.pptx.flow import draw_flow, draw_text_slides, title_stream
from markitdoc.pptx.grids import draw_feature, draw_figures, draw_summary
from markitdoc.pptx.openers import draw_chapter, draw_closing, draw_cover, draw_divider, draw_quote
from markitdoc.pptx.package import save_presentation
from markitdoc.pptx.photos import add_fade
from markitdoc.pptx.sequences import draw_comparison, draw_keypoints, draw_matrix, draw_process, draw_timeline
from markitdoc.themes.themes import Theme
from markitdoc.utils.constants import PLATFORM_CREATOR, PLATFORM_KEYWORDS
from markitdoc.utils.helpers import creation_date

logger = logging.getLogger(__name__)
required_slots = {"cover": "title", "summary": "title", "divider": "title", "chapter": "title", "figures": "title", "keypoints": "title",
                  "matrix": "title", "quote": "quote", "comparison": "title", "process": "title", "timeline": "title", "feature": "title",
                  "closing": "title"}
needs_items = {"figures": 1, "keypoints": 1, "matrix": 4, "comparison": 1, "process": 1, "timeline": 1}
slide_photo_ratios = {"cover": 16 / 9, "divider": 16 / 9, "quote": 16 / 9, "closing": 16 / 9, "chapter": 8 / 9, "feature": 8 / 9}


drawers = {"cover": draw_cover, "divider": draw_divider, "quote": draw_quote, "closing": draw_closing, "summary": draw_summary,
           "figures": draw_figures, "keypoints": draw_keypoints, "process": draw_process, "timeline": draw_timeline,
           "comparison": draw_comparison, "matrix": draw_matrix, "chapter": draw_chapter, "feature": draw_feature}


def drawable(block):
    slot = required_slots.get(block.layout)
    return (slot is not None and bool(block.slots.get(slot)) and len([item for item in block.items if item and item[0]]) >= needs_items.get(block.layout, 0)
            and (block.layout != "comparison" or bool(block.slots.get("left") and block.slots.get("right"))))


def draw_designed(deck, block, image=None):
    drawers[block.layout](deck, block, image)


def draw_block(deck, index, block):
    before = deck.slide_count
    try:
        if block.layout == "flow":
            draw_flow(deck, block.body, draw_designed)
        elif drawable(block):
            drawers[block.layout](deck, block, deck.photos_by_block.get(index))
        else:
            logger.warning("Slide block %d (%s) is incomplete, shown as plain slides", index + 1, block.layout)
            draw_flow(deck, as_flow(block).body, draw_designed)
    except Exception:
        logger.exception("Slide block %d (%s) failed to draw; shown as plain slides", index + 1, block.layout)
        deck.drop_slides_after(before)
        draw_flow(deck, as_flow(block).body, draw_designed)


def deck_title(blocks, meta):
    first = blocks[0]
    return (meta.get("title") or first.slots.get("title") or next((line.lstrip("# ").strip() for line in first.body.splitlines()
                                                                if line.startswith("# ")), "") or "Presentation")


def draw_notes_slide(deck):
    if deck.footnotes:
        items = [Item(f"{text}", "number", 0, number) for number, (_, text) in enumerate(deck.footnotes, 1)]
        draw_text_slides(deck, title_stream("Notes"), items)


def stamp_metadata(deck, user_email, title):
    properties = deck.presentation.core_properties
    moment = creation_date(deck.meta.get("date"))
    properties.author = user_email or deck.theme.brand or ""
    properties.last_modified_by = properties.author
    properties.title = title
    properties.subject = str(deck.meta.get("subject", "")) or title
    properties.created = properties.modified = moment.replace(tzinfo=None)
    properties.revision = 1
    properties.comments = PLATFORM_CREATOR
    properties.keywords = PLATFORM_KEYWORDS
    properties.category = "generated-document"


def render_pptx(document: Document, theme: Theme, output_path: Path, images=None, user_email=""):
    started = time.perf_counter()
    blocks = balanced([prepared(block) for block in document.blocks], theme)
    with tempfile.TemporaryDirectory() as work_folder:
        deck = Deck(theme, document.meta, Path(work_folder), images or {})
        deck.title = plain_text(deck_title(blocks, document.meta))
        first = 0
        if deck.branded:
            cover = blocks[0] if blocks[0].layout == "cover" and drawable(blocks[0]) else None
            draw_brand_cover(deck, cover)
            first = 1 if cover else 0
        for index, block in enumerate(blocks[first:], first):
            draw_block(deck, index, block)
        draw_notes_slide(deck)
        deck.flush_notes()
        for slide in deck.presentation.slides:
            add_fade(slide)
        stamp_metadata(deck, user_email, deck.title)
        save_presentation(deck.presentation, output_path)
    logger.info("PPTX rendered: %d blocks, %d slides, theme %s, %d images, %.1f s", len(blocks), deck.slide_count, theme.name,
                len(images or {}), time.perf_counter() - started)
    return output_path

