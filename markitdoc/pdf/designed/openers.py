from dataclasses import replace

from markitdoc.markup.blocks import paragraphs
from markitdoc.models.catalogue import CONTENT_LIMIT, CONTENT_WIDTH, MARGIN, PAGE_HEIGHT, PAGE_WIDTH, TEXT_WIDTH, Box
from markitdoc.models.document import Block
from markitdoc.pdf.pages import SOFT_WHITE, WHITE, PdfPages
from markitdoc.pdf.photos import placed
from markitdoc.utils.helpers import lifted, long_date


# draws the cover title and subtitle in the chosen colors
def cover_text(pdf, block, on_dark, top):
    pdf.bar(MARGIN, top - 8, rgb=lifted(pdf.theme.rgb("mood"), 0.55) if on_dark else pdf.theme.rgb("mood"))
    end = pdf.write_at(MARGIN, top, CONTENT_WIDTH, block.slots["title"], pdf.slot_size(block, "title"), "B",
                       rgb=WHITE if on_dark else pdf.theme.rgb("ink"), line_height=1.08)
    return pdf.write_at(MARGIN, end + 6, 150, block.slots["subtitle"], pdf.slot_size(block, "subtitle"), rgb=SOFT_WHITE if on_dark else pdf.theme.rgb("body"),
                        line_height=1.4)


# draws a designed cover page from the block content
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
        pdf.rect(0, 0, PAGE_WIDTH, 150, "F")
        pdf.glow(PAGE_WIDTH - 20, 40, 190, clip=(0, 0, PAGE_WIDTH, 150))
        pdf.brand_mark(MARGIN, 18, on_dark=False)
        pdf.kicker(MARGIN, 112, kicker)
        cover_text(pdf, block, on_dark=False, top=128)
        y = PAGE_HEIGHT - 40 - len(pdf.theme.address) * 4.6
        for line in pdf.theme.address:
            y = pdf.write_at(MARGIN, y, 90, line, 8.5, role="body", line_height=1.35)
        pdf.partner_strip(PAGE_HEIGHT - 30)
        return 0, PAGE_HEIGHT
    if variant == "light":
        pdf.fill_page("paper")
        pdf.brand_mark(MARGIN, 18, on_dark=False)
        pdf.kicker(MARGIN, 40, kicker)
        cover_text(pdf, block, on_dark=False, top=118)
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(MARGIN, PAGE_HEIGHT - 40, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 40)
        pdf.write_at(MARGIN, PAGE_HEIGHT - 34, CONTENT_WIDTH / 2, long_date(getattr(pdf, "meta_date", "")), 9, role="muted")
        pdf.write_at(PAGE_WIDTH / 2, PAGE_HEIGHT - 34, CONTENT_WIDTH / 2, pdf.theme.brand or "", 9, role="muted", align="R")
        return 0, PAGE_HEIGHT
    if variant == "split":
        pdf.fill_page("paper")
        pdf.set_fill_color(*pdf.theme.rgb("night"))
        pdf.rect(0, 0, 76, PAGE_HEIGHT, "F")
        if image:
            placed(pdf, image, 0, 0, 76, PAGE_HEIGHT, work_folder, description=block.slots.get("image", "Photograph"))
        else:
            pdf.glow(38, 200, 160, clip=(0, 0, 76, PAGE_HEIGHT))
        pdf.brand_mark(88, 20, on_dark=False)
        pdf.kicker(88, 100, kicker)
        pdf.bar(88, 110, role="mood")
        size = 32
        while size > 20 and pdf.line_count(block.slots["title"], Box(104, size, 0, "B")) > 4:
            size -= 2
        end = pdf.write_at(88, 118, 104, block.slots["title"], size, "B", line_height=1.1)
        pdf.write_at(88, end + 6, 104, block.slots["subtitle"], pdf.slot_size(block, "subtitle"), role="body", line_height=1.45)
        return 0, PAGE_HEIGHT
    night = pdf.theme.rgb("night")
    pdf.fill_page("night")
    if variant == "photo":
        fades = ((0, 0.3, 0.7, 0.0, night), (0.38, 0.62, 0.0, 0.93, night), (0.62, 1.0, 0.93, 0.97, night))
        placed(pdf, image, 0, 0, PAGE_WIDTH, PAGE_HEIGHT, work_folder, fades, block.slots.get("image", "Photograph"))
    else:
        pdf.glow(PAGE_WIDTH - 30, 70, 230)
    pdf.brand_mark(MARGIN, 16, on_dark=True)
    pdf.kicker(MARGIN, 34 if pdf.theme.logo else 20, kicker, on_dark=True)
    cover_text(pdf, block, on_dark=True, top=PAGE_HEIGHT - 100 if variant == "photo" else 112)
    return 0, PAGE_HEIGHT


# draws an executive summary page with key figures
def draw_summary(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    pdf.kicker(MARGIN, 22, "Executive summary")
    end = pdf.write_at(MARGIN, 30, CONTENT_WIDTH, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    end = pdf.write_at(MARGIN, end + 4, CONTENT_WIDTH, block.slots["lead"], pdf.slot_size(block, "lead"), line_height=1.45, rich=True)
    count, gap, top = len(block.items), 5, end + 9
    width = (CONTENT_WIDTH - gap * (count - 1)) / max(count, 1)
    card = max([30] + [20 + pdf.text_height(label, width - 8, 8.5, 1.3) for _, label in block.items])
    for index, (value, label) in enumerate(block.items):
        x = MARGIN + index * (width + gap)
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(x, top, width, card, "F")
        pdf.bar(x, top, 1.2, card, role="mood")
        size = pdf.fitting_size(value, width - 8, 20)
        pdf.write_at(x + 5, top + 5 + (20 - size) * 0.18, width - 8, value, size, "B", "mood", line_height=1.0)
        pdf.write_at(x + 5, top + 16, width - 8, label, 8.5, role="muted", line_height=1.3)
    y = top + card + 10
    for paragraph in paragraphs(block.slots["body"]):
        y = pdf.write_at(MARGIN, y, TEXT_WIDTH, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True) + 3
    pdf.folio("Executive summary")
    return y, CONTENT_LIMIT


# draws a section divider page with its number, title, and lead
def draw_divider(pdf: PdfPages, block: Block, image, work_folder):
    dark = block.slots.get("variant") == "dark"
    pdf.fill_page("night" if dark else "surface")
    if dark:
        pdf.glow(PAGE_WIDTH - 10, PAGE_HEIGHT - 60, 260, rings=70)
    else:
        pdf.bar(0, 0, 6, PAGE_HEIGHT, role="mood")
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    pdf.write_at(MARGIN, 64, 80, block.slots.get("number", ""), pdf.slot_size(block, "number"), "B", rgb=tone, line_height=1.0)
    pdf.bar(MARGIN, 96, rgb=tone)
    end = pdf.write_at(MARGIN, 104, CONTENT_WIDTH, block.slots["title"], pdf.slot_size(block, "title"), "B",
                       rgb=WHITE if dark else pdf.theme.rgb("ink"), line_height=1.1)
    end = pdf.write_at(MARGIN, end + 6, 150, block.slots.get("lead", ""), pdf.slot_size(block, "lead"), rgb=SOFT_WHITE if dark else pdf.theme.rgb("body"),
                       line_height=1.45)
    if block.items:
        y = max(end + 18, 190)
        pdf.write_at(MARGIN, y, 120, "IN THIS PART", 7.5, "B", rgb=tone)
        y += 7
        for number, (entry,) in enumerate(block.items, 1):
            pdf.set_draw_color(*((70, 82, 120) if dark else pdf.theme.rgb("rule")))
            pdf.line(MARGIN, y, MARGIN + 120, y)
            pdf.write_at(MARGIN, y + 2.5, 10, f"{number:02d}", 9, "B", rgb=tone)
            y = pdf.write_at(MARGIN + 12, y + 2.5, 108, entry, 10, rgb=SOFT_WHITE if dark else pdf.theme.rgb("ink")) + 2.5
        end = y
    return end, CONTENT_LIMIT


# estimates how much vertical space chapter text needs
def chapter_text_height(pdf, block):
    column = CONTENT_WIDTH / 2 - 4
    tallest = max((pdf.text_height(part, column, 9.6, 1.55) for part in paragraphs(block.slots["body"])), default=0)
    quote = pdf.text_height(block.slots.get("quote", ""), CONTENT_WIDTH - 6, 12.5, 1.4, "I") + 8 if block.slots.get("quote") else 0
    lead = pdf.text_height(block.slots.get("lead", ""), CONTENT_WIDTH, 12.5, 1.45) + 5
    title = pdf.text_height(block.slots["title"], CONTENT_WIDTH - 22, 21, 1.15)
    return title + lead + tallest + quote + 30


# adds a chapter heading, image, body, and optional quote
def draw_chapter(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    plain = not image and block.slots.get("variant") != "band"
    room = CONTENT_LIMIT - chapter_text_height(pdf, block)
    band = 0 if plain else max(36, min(108 if image else 72, room))
    if image:
        placed(pdf, image, 0, 0, PAGE_WIDTH, band, work_folder, ((0.6, 1.0, 0.0, 0.35, (0, 0, 0)),), block.slots.get("image", "Photograph"))
    elif not plain:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(0, 0, PAGE_WIDTH, band, "F")
        pdf.bar(0, band - 1.4, PAGE_WIDTH, 1.4, role="mood")
    number = block.slots.get("number", "")
    top = band + 10 if band else 26
    if number:
        pdf.write_at(MARGIN, top, 40, number, 30, "B", "mood", line_height=1.0)
    title_x = MARGIN + 22 if number else MARGIN
    title_end = pdf.write_at(title_x, top + 0.5, PAGE_WIDTH - MARGIN - title_x, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    lead_end = pdf.write_at(MARGIN, max(title_end, top + 12) + 5, CONTENT_WIDTH, block.slots.get("lead", ""), pdf.slot_size(block, "lead"),
                            line_height=1.45, rich=True)
    column_width, top = CONTENT_WIDTH / 2 - 4, lead_end + 6
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.line(MARGIN, top - 2, PAGE_WIDTH - MARGIN, top - 2)
    left, right = (paragraphs(block.slots["body"]) + [""])[:2]
    body_size = pdf.slot_size(block, "body")
    left_end = pdf.write_at(MARGIN, top + 2, column_width, left, body_size, role="body", line_height=1.55, rich=True)
    right_end = pdf.write_at(MARGIN + column_width + 8, top + 2, column_width, right, body_size, role="body", line_height=1.55, rich=True)
    end = max(left_end, right_end)
    if block.slots.get("quote"):
        quote_top = end + 8 * pdf.tightness ** 3
        end = pdf.write_at(MARGIN + 6, quote_top, CONTENT_WIDTH - 6, block.slots["quote"], pdf.slot_size(block, "quote"), "I", line_height=1.4)
        pdf.bar(MARGIN, quote_top, 1.2, end - quote_top, role="mood")
    pdf.folio(f"Chapter {number}" if number else "Chapter")
    return end, CONTENT_LIMIT


# draws a quote page with its optional context and attribution
def draw_quote(pdf: PdfPages, block: Block, image, work_folder):
    dark = block.slots.get("variant") == "dark"
    pdf.fill_page("night" if dark else "surface")
    if dark:
        pdf.glow(30, PAGE_HEIGHT - 40, 220, rings=70)
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    height = (pdf.text_height(block.slots["quote"], CONTENT_WIDTH - 10, 26, 1.3, "I")
              + pdf.text_height(block.slots.get("context", ""), pdf.slot_size(block, "context"), 10.5, 1.55) + 50)
    top = max(50, (PAGE_HEIGHT - height) / 2)
    pdf.write_at(MARGIN, top - 34, 40, "“", 110, "B", rgb=tone, line_height=0.8)
    end = pdf.write_at(MARGIN + 10, top, CONTENT_WIDTH - 10, block.slots["quote"], pdf.slot_size(block, "quote"), "I",
                       rgb=WHITE if dark else pdf.theme.rgb("ink"), line_height=1.3)
    if block.slots.get("quote_by"):
        pdf.bar(MARGIN + 10, end + 8, rgb=tone)
        end = pdf.write_at(MARGIN + 10, end + 13, 150, block.slots["quote_by"], pdf.slot_size(block, "quote_by"), "B", rgb=tone)
    if block.slots.get("context"):
        end = pdf.write_at(MARGIN + 10, end + 8, 130, block.slots["context"], pdf.slot_size(block, "context"),
                           rgb=SOFT_WHITE if dark else pdf.theme.rgb("body"), line_height=1.55)
    return end, CONTENT_LIMIT


# draws a feature page with an image, body text, and related figures
def draw_feature(pdf: PdfPages, block: Block, image, work_folder):
    if not image and not block.items:
        story = replace(block, layout="chapter", slots={**block.slots, "variant": "plain"})
        return draw_chapter(pdf, story, None, work_folder)
    pdf.fill_page("paper")
    image_left = block.slots.get("variant", "left") == "left"
    panel = 92 if image else 64
    panel_x = 0 if image_left else PAGE_WIDTH - panel
    if image:
        placed(pdf, image, panel_x, 0, panel, PAGE_HEIGHT, work_folder, description=block.slots.get("image", "Photograph"))
    else:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(panel_x, 0, panel, PAGE_HEIGHT, "F")
        pdf.bar(panel_x + (panel - 1.2 if image_left else 0), 0, 1.2, PAGE_HEIGHT, role="mood")
        y = (PAGE_HEIGHT - 46 * len(block.items)) / 2
        for figure, label in block.items:
            size = pdf.fitting_size(figure, panel - 20, 30, 16)
            pdf.write_at(panel_x + 10, y, panel - 20, figure, size, "B", "mood", line_height=1.0)
            pdf.write_at(panel_x + 10, y + 14, panel - 20, label, 9, role="muted", line_height=1.35)
            y += 46
    x = panel + 12 if image_left else MARGIN
    width = PAGE_WIDTH - panel - 12 - MARGIN
    pdf.kicker(x, 22, "Feature")
    end = pdf.write_at(x, 30, width, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    for paragraph in paragraphs(block.slots["body"]):
        end = pdf.write_at(x, end + 5, width, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True)
    if image and block.items and end + 10 + 25 * len(block.items) > CONTENT_LIMIT:
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
    return end, CONTENT_LIMIT


# adds the closing content and any available contact details
def draw_closing(pdf: PdfPages, block: Block, image, work_folder, credits=()):
    pdf.fill_page("paper")
    company = block.slots.get("variant") == "company" and pdf.theme.address
    bottom = PAGE_HEIGHT - 19
    if company:
        company_top = PAGE_HEIGHT - 36 - 16 - len(pdf.theme.address) * 5
        pdf.brand_mark(MARGIN, company_top, on_dark=False)
        for index, line in enumerate(pdf.theme.address):
            pdf.write_at(MARGIN, company_top + 16 + index * 5, 120, line, 9, role="body")
        pdf.partner_strip(PAGE_HEIGHT - 34)
        bottom = company_top - 8
    if credits:
        credit_height = 6 + sum(pdf.text_height(credit, CONTENT_WIDTH, 7, 1.4) + 1.2 for credit in credits)
        y = bottom - credit_height
        pdf.write_at(MARGIN, y, 100, "IMAGE CREDITS", 7.5, "B", "mood")
        y += 6
        for credit in credits:
            y = pdf.write_at(MARGIN, y, CONTENT_WIDTH, credit, 7, role="muted", line_height=1.4) + 1.2
        bottom -= credit_height + 6
    text_height = (pdf.text_height(block.slots["title"], CONTENT_WIDTH, 17, 1.35, "B")
                   + sum(pdf.text_height(paragraph, TEXT_WIDTH, 10.5, 1.55) + 4 for paragraph in paragraphs(block.slots["body"])))
    end = 26 if block.slots.get("quote") else max(40, (bottom - text_height) / 2 - 10)
    if block.slots.get("quote"):
        pdf.write_at(MARGIN, 26, 30, "“", 90, "B", "mood", line_height=0.8)
        end = pdf.write_at(MARGIN + 4, 52, CONTENT_WIDTH - 8, block.slots["quote"], pdf.slot_size(block, "quote"), "I", line_height=1.3)
        if block.slots.get("quote_by"):
            end = pdf.write_at(MARGIN + 4, end + 5, 150, "— " + block.slots["quote_by"], pdf.slot_size(block, "quote_by"), "B", "muted")
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(MARGIN, end + 12, PAGE_WIDTH - MARGIN, end + 12)
        end += 20
    end = pdf.write_at(MARGIN, end, CONTENT_WIDTH, block.slots["title"], pdf.slot_size(block, "title"), "B")
    for paragraph in paragraphs(block.slots["body"]):
        end = pdf.write_at(MARGIN, end + 4, TEXT_WIDTH, paragraph, pdf.slot_size(block, "body"), role="body", line_height=1.55, rich=True)
    if not company:
        pdf.folio("Closing")
    return end, bottom
