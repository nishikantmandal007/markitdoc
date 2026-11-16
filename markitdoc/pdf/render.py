import logging
import re
from pathlib import Path

from fpdf import ViewerPreferences
from mdit_py_plugins.container import container_plugin

from markitdoc.markup.blocks import as_flow, balanced, prepared
from markitdoc.markup.fields import field_values
from markitdoc.markup.inline import ANCHOR, UNNUMBERED, parser
from markitdoc.models.catalogue import SECTIONED_LAYOUTS, TRAILING_HEADINGS
from markitdoc.models.document import Document
from markitdoc.models.model_constants import FLOW_CONTAINERS, PAGE_SWITCH
from markitdoc.pdf.designed.openers import (
    draw_chapter,
    draw_closing,
    draw_cover,
    draw_divider,
    draw_feature,
    draw_quote,
    draw_summary,
)
from markitdoc.pdf.designed.sections import (
    draw_comparison,
    draw_figures,
    draw_keypoints,
    draw_matrix,
    draw_process,
    draw_timeline,
)
from markitdoc.pdf.pages import text_of
from markitdoc.themes.theme_constants import TEXT_SIZES
from markitdoc.themes.themes import Theme
from markitdoc.utils.helpers import creation_date

logger = logging.getLogger(__name__)


# whether a ::: line opens this container; any other name or bare attributes open a box
def opens(name, params):
    first = (re.findall(r"[\w-]+", params) or [""])[0]
    return first == name or (name == "box" and params.strip() != "" and first not in FLOW_CONTAINERS)


for container_name in FLOW_CONTAINERS:
    container_plugin(parser, container_name, validate=lambda params, *_, name=container_name: opens(name, params))


DRAWERS = {"cover": draw_cover, "summary": draw_summary, "divider": draw_divider, "chapter": draw_chapter,
           "figures": draw_figures, "keypoints": draw_keypoints, "matrix": draw_matrix, "quote": draw_quote,
           "comparison": draw_comparison, "process": draw_process, "timeline": draw_timeline, "feature": draw_feature}


# dispatches a designed block to its PDF page renderer
def draw_block(pdf, block, image, work_folder, credits):
    if block.layout == "closing":
        return draw_closing(pdf, block, image, work_folder, credits)
    return DRAWERS[block.layout](pdf, block, image, work_folder)


# renders a document as a PDF file
def render_pdf(document: Document, theme: Theme, output_path: Path, work_folder: Path, images=None, credits=(), styles=None,
               numbering=None, pages_out=None):
    from markitdoc.pdf.flow.pages import FlowPages
    from markitdoc.pdf.flow.render import fitted_spacing, queue_switch, render_flow, render_toc
    images = images or {}
    blocks = balanced([prepared(block) for block in document.blocks], theme)
    first = blocks[0]
    title = first.slots.get("title") or next((line.lstrip("# ").strip() for line in first.body.splitlines()
                                             if line.startswith("# ")), "Document")
    pdf = FlowPages(theme, title, document.meta.get("style") == "plain", text_of(document, theme) + str(credits)
                    + (str(styles.fields) + str([layer.data.get("pages") for layer in styles.layers]) if styles else ""))
    pdf.use_styles(styles)
    pdf.field_values = field_values(styles, document.meta) if styles else {}
    pdf.table_style = str(document.meta.get("tables", "lined")).lower()
    pdf.flow_images = {key[1]: path for key, path in images.items() if isinstance(key, tuple)}
    pdf.photos = str(document.meta.get("photos", "natural")).lower()
    pdf.work_folder = work_folder
    pdf.targets = frozenset(match.group(1) for block in blocks for line in block.body.splitlines()
                            if line.lstrip().startswith("#") and (match := ANCHOR.search(UNNUMBERED.sub("", line)))) | frozenset(numbering.targets if numbering else ())
    pdf.numbers = numbering.targets if numbering else {}
    pdf.numbering = str(document.meta.get("numbering", "")).lower() == "decimal" or bool(numbering and numbering.section_numbers)
    pdf.header_text, pdf.footer_text, pdf.classification, pdf.watermark = (str(document.meta.get(key, "")).strip().strip("'\"")
                                                                            for key in ("header", "footer", "classification", "watermark"))
    pdf.meta_date = str(document.meta.get("date", ""))
    pdf.lang = str(document.meta.get("lang", "en")) or "en"
    pdf.notes_at_page_bottom = str(document.meta.get("notes", "")).lower() == "page"
    pdf.set_lang(pdf.lang)
    pdf.scale = TEXT_SIZES.get(str(document.meta.get("text_size", "regular")).lower(), 1.0)
    pdf.set_title(title)
    pdf.set_author(str(document.meta.get("author", "")).strip("'\" ") or theme.brand or "")
    pdf.set_creation_date(creation_date(document.meta.get("date")))
    pdf.set_subject(str(document.meta.get("subject", "")) or title)
    pdf.viewer_preferences = ViewerPreferences(display_doc_title=True)
    toc_at = 1 if first.layout == "cover" and len(blocks) > 1 else 0
    wants_toc = document.meta.get("toc") in ("true", "yes", "on")
    for index, block in enumerate(blocks):
        fresh_page, text, switch = False, block.body, None
        first_line, _, rest = block.body.lstrip().partition("\n")
        if pdf.styles and block.layout == "flow" and (found := PAGE_SWITCH.match(first_line.strip())):
            text, switch = rest, found.group(1)
        if wants_toc and index == toc_at:
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=pdf.bottom)
            pdf.add_page()
            if switch:
                queue_switch(pdf, switch)
            pdf.decorate = block.layout == "flow"
            pdf.insert_toc_placeholder(render_toc, pages=1, allow_extra_pages=True)
            fresh_page = block.layout != "flow"
        if block.layout == "flow" and not text.strip():
            continue
        if block.layout == "flow":
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=pdf.bottom)
            after_toc = wants_toc and index == toc_at
            if switch and not after_toc:
                queue_switch(pdf, switch)
            if not after_toc and (index == 0 or blocks[index - 1].layout != "flow" or switch):
                pdf.add_page()
            next_is_designed = index + 1 < len(blocks) and blocks[index + 1].layout != "flow"
            body = TRAILING_HEADINGS.sub("", text.rstrip()) if next_is_designed else text
            if not body.strip():
                continue
            pdf.spacing = fitted_spacing(pdf, body) if next_is_designed else 1.0
            render_flow(pdf, body)
            pdf.spacing = 1.0
            continue
        pdf.decorate = False
        pdf.set_auto_page_break(False)
        if not fresh_page:
            pdf.add_page()
        if block.slots.get("title") and block.layout in SECTIONED_LAYOUTS:
            pdf.start_section(block.slots["title"].replace("**", "").replace("__", ""), level=0, strict=False)
        try:
            pdf.tightness = float(block.slots.get("tightness", 1.0))
            picture = images.get(index)
            pdf.photo_credit = picture[2:4] if picture else None
            with pdf.centred():
                draw_block(pdf, block, picture[0] if picture else None, work_folder, ())
            pdf.photo_credit = None
            pdf.tightness = 1.0
        except Exception:
            logger.exception("Page %d (%s) failed to draw; shown as text instead", index + 1, block.layout)
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=pdf.bottom)
            pdf.fill_page("paper")
            pdf.set_xy(pdf.l_margin, 24)
            render_flow(pdf, as_flow(block).body)
    pdf.output(str(output_path))
    if pages_out is not None:
        pages_out.update(pdf.target_pages)
    logger.info("PDF rendered: %d blocks, %d pages, theme %s, contents %s, %d images",
                len(blocks), pdf.pages_count, theme.name, "yes" if wants_toc else "no", len(images))
    return output_path
