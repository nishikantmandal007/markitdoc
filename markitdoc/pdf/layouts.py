import re
from pathlib import Path

from fpdf import ViewerPreferences
from mdit_py_plugins.container import container_plugin

import logging
from markitdoc.models.document import Document
from markitdoc.themes.theme_constants import TEXT_SIZES
from markitdoc.themes.themes import Theme
from markitdoc.markup.inline import anchor, parser
from markitdoc.utils.helpers import creation_date
from markitdoc.models.catalogue import sectioned_layouts, trailing_headings
from markitdoc.markup.blocks import as_flow, balanced, prepared
from markitdoc.pdf.sections import (draw_comparison, draw_figures, draw_keypoints, draw_matrix, draw_process,
                                    draw_timeline)
from markitdoc.pdf.openers import (draw_chapter, draw_closing, draw_cover, draw_divider, draw_feature, draw_quote,
                                   draw_summary)

logger = logging.getLogger(__name__)
for container_name in ("box", "sidebar", "columns"):
    container_plugin(parser, container_name, validate=lambda params, *_, name=container_name: name in re.findall(r"[\w-]+", params)[:1])


drawers = {"cover": draw_cover, "summary": draw_summary, "divider": draw_divider, "chapter": draw_chapter,
           "figures": draw_figures, "keypoints": draw_keypoints, "matrix": draw_matrix, "quote": draw_quote,
           "comparison": draw_comparison, "process": draw_process, "timeline": draw_timeline, "feature": draw_feature}


def draw_block(pdf, block, image, work_folder, credits):
    if block.layout == "closing":
        return draw_closing(pdf, block, image, work_folder, credits)
    return drawers[block.layout](pdf, block, image, work_folder)


def render_pdf(document: Document, theme: Theme, output_path: Path, work_folder: Path, images=None, credits=()):
    from markitdoc.pdf.flow import FlowPages, fitted_spacing, render_flow, render_toc
    images = images or {}
    blocks = balanced([prepared(block) for block in document.blocks], theme)
    first = blocks[0]
    title = first.slots.get("title") or next((line.lstrip("# ").strip() for line in first.body.splitlines()
                                             if line.startswith("# ")), "Document")
    pdf = FlowPages(theme, title, document.meta.get("style") == "plain")
    pdf.table_style = str(document.meta.get("tables", "lined")).lower()
    pdf.flow_images = {key[1]: path for key, path in images.items() if isinstance(key, tuple)}
    pdf.photos = str(document.meta.get("photos", "natural")).lower()
    pdf.work_folder = work_folder
    pdf.targets = frozenset(match.group(1) for block in blocks for line in block.body.splitlines()
                            if line.lstrip().startswith("#") and (match := anchor.search(line)))
    pdf.numbering = str(document.meta.get("numbering", "")).lower() == "decimal"
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
        fresh_page = False
        if wants_toc and index == toc_at:
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=22)
            pdf.add_page()
            pdf.decorate = block.layout == "flow"
            pdf.insert_toc_placeholder(render_toc, pages=1, allow_extra_pages=True)
            fresh_page = block.layout != "flow"
        if block.layout == "flow" and not block.body.strip():
            continue
        if block.layout == "flow":
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=22)
            if not (wants_toc and index == toc_at) and (index == 0 or blocks[index - 1].layout != "flow"):
                pdf.add_page()
            next_is_designed = index + 1 < len(blocks) and blocks[index + 1].layout != "flow"
            body = trailing_headings.sub("", block.body.rstrip()) if next_is_designed else block.body
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
        if block.slots.get("title") and block.layout in sectioned_layouts:
            pdf.start_section(block.slots["title"].replace("**", "").replace("__", ""), level=0, strict=False)
        try:
            pdf.tightness = float(block.slots.get("tightness", 1.0))
            picture = images.get(index)
            pdf.photo_credit = picture[2:4] if picture else None
            draw_block(pdf, block, picture[0] if picture else None, work_folder, ())
            pdf.photo_credit = None
            pdf.tightness = 1.0
        except Exception:
            logger.exception("Page %d (%s) failed to draw; shown as text instead", index + 1, block.layout)
            pdf.decorate = True
            pdf.set_auto_page_break(True, margin=22)
            pdf.fill_page("paper")
            pdf.set_xy(pdf.l_margin, 24)
            render_flow(pdf, as_flow(block).body)
    pdf.output(str(output_path))
    logger.info("PDF rendered: %d blocks, %d pages, theme %s, contents %s, %d images",
                len(blocks), pdf.pages_count, theme.name, "yes" if wants_toc else "no", len(images))
    return output_path
