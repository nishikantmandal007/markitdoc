import re
from dataclasses import replace
from pathlib import Path

from fpdf import ViewerPreferences
from mdit_py_plugins.container import container_plugin

import logging
from markitdoc.models.document import Document
from markitdoc.themes.theme_constants import TEXT_SIZES
from markitdoc.themes.themes import Theme
from markitdoc.markup.inline import anchor, parser
from markitdoc.utils.helpers import creation_date
from markitdoc.models.catalogue import content_limit, layouts, sectioned_layouts, trailing_headings
from markitdoc.markup.blocks import as_flow, balanced, prepared, slot_pieces
from markitdoc.pdf.pages import PdfPages, shrink_steps
from markitdoc.pdf.photos import measuring_photo
from markitdoc.pdf.sections import (draw_comparison, draw_figures, draw_keypoints, draw_matrix, draw_process,
                                    draw_timeline)
from markitdoc.pdf.openers import (draw_chapter, draw_closing, draw_cover, draw_divider, draw_feature, draw_quote,
                                   draw_summary)

logger = logging.getLogger(__name__)
for container_name in ("box", "sidebar", "columns"):
    container_plugin(parser, container_name, validate=lambda params, *_, name=container_name: name in re.findall(r"[\w-]+", params)[:1])
tightness_steps = (1.0, 0.92, 0.85)


def problems_in(document: Document, theme: Theme | None = None) -> list[str]:
    return [message for _, message in page_problems(document, theme)]


def page_problems(document: Document, theme: Theme | None = None, with_images: bool = False, fitted: dict | None = None,
                  credits=(), sparse: set | None = None) -> list[tuple[int, str]]:
    from markitdoc.visuals.diagrams import problems_in_diagram
    from markitdoc.visuals.infographics import problems_in_infographic
    from markitdoc.pdf.flow import chart_data
    from markitdoc.themes.themes import load_theme
    measurer = PdfPages(theme or load_theme(None))
    measurer.add_page()
    found = []
    for index, block in enumerate(document.blocks):
        block = prepared(block)
        layout = layouts.get(block.layout)
        where = f"page {index + 1} ({block.layout})"
        if layout is None:
            found.append((index, f"page {index + 1}: unknown layout '{block.layout}', use one of {sorted(layouts)}"))
            continue
        if block.layout == "flow":
            if not block.body.strip():
                found.append((index, f"{where}: body is empty"))
            found += [(index, f"{where}: chart {number} has no labels or values")
                      for number, fence in enumerate(fences(block.body, "chart"), 1) if chart_data(fence) is None]
            found += [(index, f"{where}: infographic {number}: {problem}")
                      for number, fence in enumerate(fences(block.body, "infographic"), 1) for problem in problems_in_infographic(fence)]
            found += [(index, f"{where}: diagram {number}: {problem}")
                      for number, fence in enumerate(fences(block.body, "mermaid"), 1) for problem in problems_in_diagram(fence)]
            continue
        before = len(found)
        for slot, box in layout.boxes.items():
            text = block.slots.get(slot, "")
            if not text:
                if box.required:
                    found.append((index, f"{where}: {slot} is missing"))
                continue
            smallest = replace(box, size=round(box.size * shrink_steps[-1], 1))
            for piece in slot_pieces(block, slot):
                lines = measurer.line_count(piece, smallest)
                if lines > box.lines:
                    found.append((index, f"{where}: {slot} needs {lines} lines even at the smallest size, fits {box.lines} (shorten it)"))
                if measurer.line_count(piece, box) < box.min_lines:
                    found.append((index, f"{where}: {slot} is too short to fill its page (at least {box.min_lines} lines)"))
        low, high, limits = layout.items
        if limits and not low <= len(block.items) <= high:
            found.append((index, f"{where}: needs {low} to {high} items, has {len(block.items)}"))
        if len(found) == before:
            photo = measuring_photo if with_images and block.slots.get("image") and layout.image_ratio else None
            try:
                for tightness in tightness_steps:
                    measurer.add_page()
                    measurer.tightness = tightness
                    end, limit = draw_block(measurer, block, photo, None, credits)
                    if end <= limit + 1:
                        break
            except Exception as error:
                measurer.tightness = 1.0
                found.append((index, f"{where}: could not be drawn ({type(error).__name__})"))
                continue
            measurer.tightness = 1.0
            if end > limit + 1:
                found.append((index, f"{where}: content runs {end - limit:.0f} mm past the page (shorten it)"))
            elif sparse is not None and photo is None and not (theme and theme.address) and (
                    block.layout in ("quote", "closing") or (block.layout != "cover" and end < content_limit * 0.7)):
                sparse.add(index)
            elif tightness < 1 and fitted is not None:
                fitted[index] = tightness
    return found


def fences(body, language):
    found = []
    for suffix, content in re.findall(rf"```{language}([^\n]*)\n(.*?)```", body, re.S):
        suffix = suffix.split("{")[0].strip()
        found.append((f"{language} {suffix}\n" if suffix else "") + content)
    return found


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
