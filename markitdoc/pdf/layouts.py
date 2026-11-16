import re
from dataclasses import replace
from pathlib import Path

from fpdf import ViewerPreferences
from mdit_py_plugins.container import container_plugin

import logging
from markitdoc.models.document import Block, Document
from markitdoc.themes.theme_constants import TEXT_SIZES
from markitdoc.themes.themes import Theme
from markitdoc.markup.inline import anchor, parser
from markitdoc.utils.helpers import creation_date, lifted, long_date
from markitdoc.models.catalogue import (Box, content_limit, content_width, layouts, margin, page_height, page_width,
                                        sectioned_layouts, text_width, trailing_headings)
from markitdoc.markup.blocks import as_flow, balanced, paragraphs, prepared, slot_pieces
from markitdoc.pdf.pages import PdfPages, shrink_steps, soft_white, white
from markitdoc.pdf.photos import measuring_photo, placed
from markitdoc.pdf.sections import (draw_comparison, draw_figures, draw_keypoints, draw_matrix, draw_process,
                                    draw_timeline)

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


def cover_text(pdf, block, on_dark, top):
    pdf.bar(margin, top - 8, rgb=lifted(pdf.theme.rgb("mood"), 0.55) if on_dark else pdf.theme.rgb("mood"))
    end = pdf.write_at(margin, top, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B",
                       rgb=white if on_dark else pdf.theme.rgb("ink"), line_height=1.08)
    return pdf.write_at(margin, end + 6, 150, block.slots["subtitle"], pdf.slot_size(block, "subtitle"), rgb=soft_white if on_dark else pdf.theme.rgb("body"),
                        line_height=1.4)


def draw_cover(pdf: PdfPages, block: Block, image, work_folder):
    variant = block.slots.get("variant") or ("photo" if image else pdf.theme.cover if pdf.theme.cover in ("dark", "light") else "dark")
    if variant in ("photo", "split", "dark") and not image:
        variant = "light"
    if variant == "company" and not pdf.theme.address:
        variant = "light"
    kicker = block.slots.get("kicker", "")
    if variant == "company":
        pdf.fill_page("paper")
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(0, 0, page_width, 150, "F")
        pdf.glow(page_width - 20, 40, 190, clip=(0, 0, page_width, 150))
        pdf.brand_mark(margin, 18, on_dark=False)
        pdf.kicker(margin, 112, kicker)
        cover_text(pdf, block, on_dark=False, top=128)
        y = page_height - 40 - len(pdf.theme.address) * 4.6
        for line in pdf.theme.address:
            y = pdf.write_at(margin, y, 90, line, 8.5, role="body", line_height=1.35)
        pdf.partner_strip(page_height - 30)
        return 0, page_height
    if variant == "light":
        pdf.fill_page("paper")
        pdf.brand_mark(margin, 18, on_dark=False)
        pdf.kicker(margin, 40, kicker)
        cover_text(pdf, block, on_dark=False, top=118)
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, page_height - 40, page_width - margin, page_height - 40)
        pdf.write_at(margin, page_height - 34, content_width / 2, long_date(getattr(pdf, "meta_date", "")), 9, role="muted")
        pdf.write_at(page_width / 2, page_height - 34, content_width / 2, pdf.theme.brand or "", 9, role="muted", align="R")
        return 0, page_height
    if variant == "split":
        pdf.fill_page("paper")
        pdf.set_fill_color(*pdf.theme.rgb("night"))
        pdf.rect(0, 0, 76, page_height, "F")
        if image:
            placed(pdf, image, 0, 0, 76, page_height, work_folder, description=block.slots.get("image", "Photograph"))
        else:
            pdf.glow(38, 200, 160, clip=(0, 0, 76, page_height))
        pdf.brand_mark(88, 20, on_dark=False)
        pdf.kicker(88, 100, kicker)
        pdf.bar(88, 110, role="mood")
        size = 32
        while size > 20 and pdf.line_count(block.slots["title"], Box(104, size, 0, "B")) > 4:
            size -= 2
        end = pdf.write_at(88, 118, 104, block.slots["title"], size, "B", line_height=1.1)
        pdf.write_at(88, end + 6, 104, block.slots["subtitle"], pdf.slot_size(block, "subtitle"), role="body", line_height=1.45)
        return 0, page_height
    night = pdf.theme.rgb("night")
    pdf.fill_page("night")
    if variant == "photo":
        fades = ((0, 0.3, 0.7, 0.0, night), (0.38, 0.62, 0.0, 0.93, night), (0.62, 1.0, 0.93, 0.97, night))
        placed(pdf, image, 0, 0, page_width, page_height, work_folder, fades, block.slots.get("image", "Photograph"))
    else:
        pdf.glow(page_width - 30, 70, 230)
    pdf.brand_mark(margin, 16, on_dark=True)
    pdf.kicker(margin, 34 if pdf.theme.logo else 20, kicker, on_dark=True)
    cover_text(pdf, block, on_dark=True, top=page_height - 100 if variant == "photo" else 112)
    return 0, page_height


def draw_summary(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    pdf.kicker(margin, 22, "Executive summary")
    end = pdf.write_at(margin, 30, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    end = pdf.write_at(margin, end + 4, content_width, block.slots["lead"], pdf.slot_size(block, "lead"), line_height=1.45, rich=True)
    count, gap, top = len(block.items), 5, end + 9
    width = (content_width - gap * (count - 1)) / max(count, 1)
    card = max([30] + [20 + pdf.text_height(label, width - 8, 8.5, 1.3) for _, label in block.items])
    for index, (value, label) in enumerate(block.items):
        x = margin + index * (width + gap)
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(x, top, width, card, "F")
        pdf.bar(x, top, 1.2, card, role="mood")
        size = pdf.fitting_size(value, width - 8, 20)
        pdf.write_at(x + 5, top + 5 + (20 - size) * 0.18, width - 8, value, size, "B", "mood", line_height=1.0)
        pdf.write_at(x + 5, top + 16, width - 8, label, 8.5, role="muted", line_height=1.3)
    y = top + card + 10
    for paragraph in paragraphs(block.slots["body"]):
        y = pdf.write_at(margin, y, text_width, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True) + 3
    pdf.folio("Executive summary")
    return y, content_limit


def draw_divider(pdf: PdfPages, block: Block, image, work_folder):
    dark = block.slots.get("variant") == "dark"
    pdf.fill_page("night" if dark else "surface")
    if dark:
        pdf.glow(page_width - 10, page_height - 60, 260, rings=70)
    else:
        pdf.bar(0, 0, 6, page_height, role="mood")
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    pdf.write_at(margin, 64, 80, block.slots.get("number", ""), pdf.slot_size(block, "number"), "B", rgb=tone, line_height=1.0)
    pdf.bar(margin, 96, rgb=tone)
    end = pdf.write_at(margin, 104, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B",
                       rgb=white if dark else pdf.theme.rgb("ink"), line_height=1.1)
    end = pdf.write_at(margin, end + 6, 150, block.slots.get("lead", ""), pdf.slot_size(block, "lead"), rgb=soft_white if dark else pdf.theme.rgb("body"),
                       line_height=1.45)
    if block.items:
        y = max(end + 18, 190)
        pdf.write_at(margin, y, 120, "IN THIS PART", 7.5, "B", rgb=tone)
        y += 7
        for number, (entry,) in enumerate(block.items, 1):
            pdf.set_draw_color(*((70, 82, 120) if dark else pdf.theme.rgb("rule")))
            pdf.line(margin, y, margin + 120, y)
            pdf.write_at(margin, y + 2.5, 10, f"{number:02d}", 9, "B", rgb=tone)
            y = pdf.write_at(margin + 12, y + 2.5, 108, entry, 10, rgb=soft_white if dark else pdf.theme.rgb("ink")) + 2.5
        end = y
    return end, content_limit


def chapter_text_height(pdf, block):
    column = content_width / 2 - 4
    tallest = max((pdf.text_height(part, column, 9.6, 1.55) for part in paragraphs(block.slots["body"])), default=0)
    quote = pdf.text_height(block.slots.get("quote", ""), content_width - 6, 12.5, 1.4, "I") + 8 if block.slots.get("quote") else 0
    lead = pdf.text_height(block.slots.get("lead", ""), content_width, 12.5, 1.45) + 5
    title = pdf.text_height(block.slots["title"], content_width - 22, 21, 1.15)
    return title + lead + tallest + quote + 30


def draw_chapter(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    plain = not image and block.slots.get("variant") != "band"
    room = content_limit - chapter_text_height(pdf, block)
    band = 0 if plain else max(36, min(108 if image else 72, room))
    if image:
        placed(pdf, image, 0, 0, page_width, band, work_folder, ((0.6, 1.0, 0.0, 0.35, (0, 0, 0)),), block.slots.get("image", "Photograph"))
    elif not plain:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(0, 0, page_width, band, "F")
        pdf.bar(0, band - 1.4, page_width, 1.4, role="mood")
    number = block.slots.get("number", "")
    top = band + 10 if band else 26
    if number:
        pdf.write_at(margin, top, 40, number, 30, "B", "mood", line_height=1.0)
    title_x = margin + 22 if number else margin
    title_end = pdf.write_at(title_x, top + 0.5, page_width - margin - title_x, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    lead_end = pdf.write_at(margin, max(title_end, top + 12) + 5, content_width, block.slots.get("lead", ""), pdf.slot_size(block, "lead"),
                            line_height=1.45, rich=True)
    column_width, top = content_width / 2 - 4, lead_end + 6
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.line(margin, top - 2, page_width - margin, top - 2)
    left, right = (paragraphs(block.slots["body"]) + [""])[:2]
    body_size = pdf.slot_size(block, "body")
    left_end = pdf.write_at(margin, top + 2, column_width, left, body_size, role="body", line_height=1.55, rich=True)
    right_end = pdf.write_at(margin + column_width + 8, top + 2, column_width, right, body_size, role="body", line_height=1.55, rich=True)
    end = max(left_end, right_end)
    if block.slots.get("quote"):
        quote_top = end + 8 * pdf.tightness ** 3
        end = pdf.write_at(margin + 6, quote_top, content_width - 6, block.slots["quote"], pdf.slot_size(block, "quote"), "I", line_height=1.4)
        pdf.bar(margin, quote_top, 1.2, end - quote_top, role="mood")
    pdf.folio(f"Chapter {number}" if number else "Chapter")
    return end, content_limit


def draw_quote(pdf: PdfPages, block: Block, image, work_folder):
    dark = block.slots.get("variant") == "dark"
    pdf.fill_page("night" if dark else "surface")
    if dark:
        pdf.glow(30, page_height - 40, 220, rings=70)
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    height = (pdf.text_height(block.slots["quote"], content_width - 10, 26, 1.3, "I")
              + pdf.text_height(block.slots.get("context", ""), pdf.slot_size(block, "context"), 10.5, 1.55) + 50)
    top = max(50, (page_height - height) / 2)
    pdf.write_at(margin, top - 34, 40, "“", 110, "B", rgb=tone, line_height=0.8)
    end = pdf.write_at(margin + 10, top, content_width - 10, block.slots["quote"], pdf.slot_size(block, "quote"), "I",
                       rgb=white if dark else pdf.theme.rgb("ink"), line_height=1.3)
    if block.slots.get("quote_by"):
        pdf.bar(margin + 10, end + 8, rgb=tone)
        end = pdf.write_at(margin + 10, end + 13, 150, block.slots["quote_by"], pdf.slot_size(block, "quote_by"), "B", rgb=tone)
    if block.slots.get("context"):
        end = pdf.write_at(margin + 10, end + 8, 130, block.slots["context"], pdf.slot_size(block, "context"),
                           rgb=soft_white if dark else pdf.theme.rgb("body"), line_height=1.55)
    return end, content_limit


def draw_feature(pdf: PdfPages, block: Block, image, work_folder):
    if not image and not block.items:
        story = replace(block, layout="chapter", slots={**block.slots, "variant": "plain"})
        return draw_chapter(pdf, story, None, work_folder)
    pdf.fill_page("paper")
    image_left = block.slots.get("variant", "left") == "left"
    panel = 92 if image else 64
    panel_x = 0 if image_left else page_width - panel
    if image:
        placed(pdf, image, panel_x, 0, panel, page_height, work_folder, description=block.slots.get("image", "Photograph"))
    else:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(panel_x, 0, panel, page_height, "F")
        pdf.bar(panel_x + (panel - 1.2 if image_left else 0), 0, 1.2, page_height, role="mood")
        y = (page_height - 46 * len(block.items)) / 2
        for figure, label in block.items:
            size = pdf.fitting_size(figure, panel - 20, 30, 16)
            pdf.write_at(panel_x + 10, y, panel - 20, figure, size, "B", "mood", line_height=1.0)
            pdf.write_at(panel_x + 10, y + 14, panel - 20, label, 9, role="muted", line_height=1.35)
            y += 46
    x = panel + 12 if image_left else margin
    width = page_width - panel - 12 - margin
    pdf.kicker(x, 22, "Feature")
    end = pdf.write_at(x, 30, width, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    for paragraph in paragraphs(block.slots["body"]):
        end = pdf.write_at(x, end + 5, width, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True)
    if image and block.items and end + 10 + 25 * len(block.items) > content_limit:
        column = width / len(block.items)
        y, end = end + 10, end + 10
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(x, y, x + width, y)
        for index, (figure, label) in enumerate(block.items):
            left = x + index * column
            size = pdf.fitting_size(figure, column - 4, 16, 11)
            pdf.write_at(left, y + 4, column - 4, figure, size, "B", "mood", line_height=1.0)
            end = max(end, pdf.write_at(left, y + 12, column - 4, label, 8.5, role="muted", line_height=1.3))
    elif image:
        y = end + 10
        for figure, label in block.items:
            pdf.set_draw_color(*pdf.theme.rgb("rule"))
            pdf.line(x, y, x + width, y)
            pdf.write_at(x, y + 4, width, figure, 22, "B", "mood", line_height=1.0)
            y = pdf.write_at(x, y + 13, width, label, 9.5, role="muted", line_height=1.3) + 5
        end = y - 5
    pdf.folio("Feature", left=x, right=x + width)
    return end, content_limit


def draw_closing(pdf: PdfPages, block: Block, image, work_folder, credits=()):
    pdf.fill_page("paper")
    company = block.slots.get("variant") == "company" and pdf.theme.address
    bottom = page_height - 19
    if company:
        company_top = page_height - 36 - 16 - len(pdf.theme.address) * 5
        pdf.brand_mark(margin, company_top, on_dark=False)
        for index, line in enumerate(pdf.theme.address):
            pdf.write_at(margin, company_top + 16 + index * 5, 120, line, 9, role="body")
        pdf.partner_strip(page_height - 34)
        bottom = company_top - 8
    if credits:
        credit_height = 6 + sum(pdf.text_height(credit, content_width, 7, 1.4) + 1.2 for credit in credits)
        y = bottom - credit_height
        pdf.write_at(margin, y, 100, "IMAGE CREDITS", 7.5, "B", "mood")
        y += 6
        for credit in credits:
            y = pdf.write_at(margin, y, content_width, credit, 7, role="muted", line_height=1.4) + 1.2
        bottom -= credit_height + 6
    text_height = (pdf.text_height(block.slots["title"], content_width, 17, 1.35, "B")
                   + sum(pdf.text_height(paragraph, text_width, 10.5, 1.55) + 4 for paragraph in paragraphs(block.slots["body"])))
    end = 26 if block.slots.get("quote") else max(40, (bottom - text_height) / 2 - 10)
    if block.slots.get("quote"):
        pdf.write_at(margin, 26, 30, "“", 90, "B", "mood", line_height=0.8)
        end = pdf.write_at(margin + 4, 52, content_width - 8, block.slots["quote"], pdf.slot_size(block, "quote"), "I", line_height=1.3)
        if block.slots.get("quote_by"):
            end = pdf.write_at(margin + 4, end + 5, 150, "— " + block.slots["quote_by"], pdf.slot_size(block, "quote_by"), "B", "muted")
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, end + 12, page_width - margin, end + 12)
        end += 20
    end = pdf.write_at(margin, end, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B")
    for paragraph in paragraphs(block.slots["body"]):
        end = pdf.write_at(margin, end + 4, text_width, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True)
    if not company:
        pdf.folio("Closing")
    return end, bottom


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
