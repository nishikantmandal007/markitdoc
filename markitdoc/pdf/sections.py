import io

from markitdoc.models.catalogue import content_limit, content_width, margin, page_width
from markitdoc.models.document import Block
from markitdoc.pdf.pages import PdfPages, faint_white, white
from markitdoc.utils.helpers import lifted
from markitdoc.visuals.icons import icon_svg, strip_icon


def page_heading(pdf, block, label, top=22):
    pdf.kicker(margin, top, label)
    end = pdf.write_at(margin, top + 8, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B", line_height=1.15)
    if block.slots.get("lead"):
        end = pdf.write_at(margin, end + 4, content_width, block.slots["lead"], pdf.slot_size(block, "lead"), role="body", line_height=1.45, rich=True)
    return end


def draw_figures(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "Key figures")
    count = len(block.items)
    columns = 2 if count == 4 else 3
    rows = (count + columns - 1) // columns
    gap, top = 8, end + 12
    body_height = pdf.text_height(block.slots.get("body", ""), content_width, 10, 1.6) + 10 if block.slots.get("body") else 0
    cell_height = min(78, (content_limit - top - body_height) / rows)
    width = (content_width - gap * (columns - 1)) / columns
    bottom, overflow = top, 0
    shift = 9 if any(strip_icon(item[0])[0] for item in block.items) else 0
    for index, (value, label, *note) in enumerate(block.items):
        icon, value = strip_icon(value)
        x, y = margin + (index % columns) * (width + gap), top + (index // columns) * cell_height
        pdf.bar(x, y, width, 0.8, role="mood")
        if icon:
            pdf.image(io.BytesIO(icon_svg(icon, pdf.theme.rgb("mood"))), x=x, y=y + 4, w=7, h=7)
        size = pdf.fitting_size(value, width, 34, 18)
        pdf.write_at(x, y + 6 + shift, width, value, size, "B", "mood", line_height=1.0)
        label_end = pdf.write_at(x, y + 22 + shift, width, label, 10.5, "B", line_height=1.3)
        note_end = pdf.write_at(x, label_end + 1.5, width, note[0] if note else "", 9, role="body", line_height=1.45)
        overflow = max(overflow, note_end + 4 - (y + cell_height))
        bottom = max(bottom, note_end)
    end = max(bottom, top + rows * cell_height - 10) + max(overflow, 0)
    if block.slots.get("body"):
        end = pdf.write_at(margin, end + 8, content_width, block.slots["body"], pdf.slot_size(block, "body"), role="body", line_height=1.6, rich=True)
    pdf.folio("Key figures")
    return end, content_limit


def draw_keypoints(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "Key findings")
    points = [(*strip_icon(heading), text) for heading, text in block.items]
    heights = [pdf.text_height(heading, 130, 13, 1.25, "B") + pdf.text_height(text, 130, 10, 1.55) + 3 for _, heading, text in points]
    base_gap = 10 * pdf.tightness ** 3
    spare = max(0, content_limit - end - 14 - sum(heights) - base_gap * len(heights))
    gap = base_gap + min(4, spare / max(len(heights), 1))
    y = end + 12
    for number, (icon, heading, text) in enumerate(points, 1):
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, y, page_width - margin, y)
        if icon:
            pdf.image(io.BytesIO(icon_svg(icon, pdf.theme.rgb("mood"))), x=margin, y=y + 5, w=11, h=11)
        else:
            pdf.write_at(margin, y + 5, 30, f"{number:02d}", 26, "B", "mood", line_height=1.0)
        heading_end = pdf.write_at(margin + 40, y + 5, 130, heading, 13, "B", line_height=1.25)
        y = pdf.write_at(margin + 40, heading_end + 2, 130, text, 10, role="body", line_height=1.55, rich=True) + gap
    pdf.folio("Key findings")
    return y - gap, content_limit


def draw_matrix(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "At a glance")
    gap, top = 6, end + 12
    width = (content_width - gap) / 2
    height = min(96, (content_limit - top - gap) / 2)
    mood = pdf.theme.rgb("mood")
    tones = (mood, lifted(mood, 0.25), lifted(mood, 0.45), pdf.theme.rgb("muted"))
    bottom, overflow = top, 0
    for index, (label, text) in enumerate(block.items[:4]):
        x, y = margin + (index % 2) * (width + gap), top + (index // 2) * (height + gap)
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(x, y, width, height, "F")
        pdf.bar(x, y, width, 1.4, rgb=tones[index])
        label_end = pdf.write_at(x + 7, y + 8, width - 14, label, 14, "B", line_height=1.2)
        text_end = pdf.write_at(x + 7, label_end + 3, width - 14, text, 10, role="body", line_height=1.5, rich=True)
        overflow = max(overflow, text_end + 4 - (y + height))
        bottom = max(bottom, y + height)
    pdf.folio("At a glance")
    return bottom + max(overflow, 0), content_limit


def draw_comparison(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "Comparison")
    column, top = content_width / 2 - 3, end + 10
    for side, x, role in (("left", margin, "muted"), ("right", margin + column + 6, "mood")):
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        pdf.rect(x, top, column, 14, "F")
        pdf.bar(x, top, column, 1.2, role=role)
        pdf.write_at(x + 5, top + 4.5, column - 10, block.slots[side], 13, "B", role)
    takeaway = block.slots.get("takeaway", "")
    takeaway_height = pdf.text_height(takeaway, content_width - 14, 11, 1.45, "B") + 16 if takeaway else 0
    rows = [max(pdf.text_height(left, column - 10, 9.8, 1.45), pdf.text_height(right, column - 10, 9.8, 1.45)) for left, right in block.items]
    spare = max(0, content_limit - top - 18 - sum(rows) - 6 * len(rows) - takeaway_height)
    padding = 3 + min(2, spare / max(len(rows), 1) / 2)
    y = top + 18
    for left, right in block.items:
        ends = [pdf.write_at(x + 5, y + padding, column - 10, text, 9.8, role="body", line_height=1.45, rich=True)
                for text, x in ((left, margin), (right, margin + column + 6))]
        y = max(ends) + padding
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.line(margin, y, page_width - margin, y)
    if takeaway:
        pdf.set_fill_color(*pdf.theme.rgb("surface"))
        box_end = y + 8 + takeaway_height - 8
        pdf.rect(margin, y + 8, content_width, takeaway_height - 8, "F")
        pdf.bar(margin, y + 8, 1.4, takeaway_height - 8, role="mood")
        pdf.write_at(margin + 8, y + 12, content_width - 14, takeaway, 11, "B", line_height=1.45)
        y = box_end
    pdf.folio("Comparison")
    return y, content_limit


def draw_process(pdf: PdfPages, block: Block, image, work_folder):
    pdf.fill_page("paper")
    end = page_heading(pdf, block, "How it works")
    count = len(block.items)
    if block.slots.get("variant") == "horizontal" and count <= 4:
        width, top = content_width / count, end + 18
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.set_line_width(0.8)
        pdf.line(margin + width / 2, top + 7, margin + width * (count - 0.5), top + 7)
        bottom = top
        for index, (title, description) in enumerate(block.items):
            icon, title = strip_icon(title)
            center = margin + width * (index + 0.5)
            pdf.set_fill_color(*pdf.theme.rgb("mood"))
            pdf.ellipse(center - 7, top, 14, 14, "F")
            if icon:
                pdf.image(io.BytesIO(icon_svg(icon, white)), x=center - 4, y=top + 3, w=8, h=8)
            else:
                pdf.write_at(center - 7, top + 3.4, 14, str(index + 1), 13, "B", rgb=white, align="C", line_height=1.0)
            title_end = pdf.write_at(margin + width * index + 3, top + 22, width - 6, title, 12.5, "B", line_height=1.2, align="C")
            bottom = max(bottom, pdf.write_at(margin + width * index + 3, title_end + 3, width - 6, description, 9.6,
                                              role="body", line_height=1.5, align="C", rich=True))
        pdf.folio("Process")
        return bottom, content_limit
    heights = [pdf.text_height(description, content_width - 20, 9.8, 1.45) + 10 for _, description in block.items]
    top, axis = end + 12, margin + 7
    spare = max(0, content_limit - top - sum(heights))
    steps = [height + min(6, spare / max(count, 1)) for height in heights]
    pdf.set_draw_color(*pdf.theme.rgb("rule"))
    pdf.set_line_width(0.8)
    pdf.line(axis, top + 7, axis, top + sum(steps[:-1]) + 7)
    y = top
    for index, ((title, description), step) in enumerate(zip(block.items, steps)):
        icon, title = strip_icon(title)
        pdf.set_fill_color(*pdf.theme.rgb("mood"))
        pdf.ellipse(axis - 7, y, 14, 14, "F")
        if icon:
            pdf.image(io.BytesIO(icon_svg(icon, white)), x=axis - 4, y=y + 3, w=8, h=8)
        else:
            pdf.write_at(axis - 7, y + 3.4, 14, str(index + 1), 13, "B", rgb=white, align="C", line_height=1.0)
        title_end = pdf.write_at(axis + 13, y + 1, content_width - 20, title, 13, "B", line_height=1.2)
        bottom = pdf.write_at(axis + 13, max(y + 8, title_end + 1.5), content_width - 20, description, 9.8, role="body",
                              line_height=1.45, rich=True)
        y += step
    pdf.folio("Process")
    return bottom, content_limit


def draw_timeline(pdf: PdfPages, block: Block, image, work_folder):
    variant = block.slots.get("variant", "vertical")
    dark = variant == "dark"
    pdf.fill_page("night" if dark else "paper")
    tone = lifted(pdf.theme.rgb("mood"), 0.55) if dark else pdf.theme.rgb("mood")
    ink = white if dark else pdf.theme.rgb("ink")
    body = faint_white if dark else pdf.theme.rgb("body")
    pdf.kicker(margin, 22, "Timeline", on_dark=dark)
    end = pdf.write_at(margin, 30, content_width, block.slots["title"], pdf.slot_size(block, "title"), "B", rgb=ink, line_height=1.1)
    end = pdf.write_at(margin, end + 4, 150, block.slots.get("lead", ""), pdf.slot_size(block, "lead"),
                       rgb=(200, 206, 222) if dark else body, line_height=1.45)
    count = len(block.items)
    if variant == "horizontal" and count <= 5:
        width = content_width / count
        heights = [pdf.text_height(event, width - 8, 13, 1.25, "B") + pdf.text_height(description, width - 8, 10.5, 1.5) + 12
                   for _, event, description in block.items]
        axis = max(end + 40, (end + content_limit) / 2 - max(heights) / 2)
        pdf.set_draw_color(*pdf.theme.rgb("rule"))
        pdf.set_line_width(0.4)
        pdf.line(margin, axis, page_width - margin, axis)
        bottom = axis
        for index, (when, event, description) in enumerate(block.items):
            x = margin + index * width
            pdf.write_at(x, axis - 16, width - 6, when, 18, "B", rgb=tone, line_height=1.0)
            pdf.set_fill_color(*tone)
            pdf.ellipse(x, axis - 2, 4, 4, "F")
            event_end = pdf.write_at(x, axis + 8, width - 8, event, 13, "B", rgb=ink, line_height=1.25)
            bottom = max(bottom, pdf.write_at(x, event_end + 2.5, width - 8, description, 10.5, rgb=body, line_height=1.5, rich=True))
        pdf.folio("Timeline", on_dark=dark)
        return bottom, content_limit
    top, axis, text_x = end + 14, margin + 34, margin + 42
    text_width = page_width - margin - text_x
    pdf.set_draw_color(*((70, 82, 120) if dark else pdf.theme.rgb("rule")))
    pdf.set_line_width(0.4)
    y, marks = top, []
    for when, event, description in block.items:
        marks.append(y)
        pdf.write_at(margin, y - 0.6, 30, when, 10.5, "B", rgb=tone, align="R", line_height=1.2)
        event_end = pdf.write_at(text_x, y - 0.8, text_width, event, 12, "B", rgb=ink, line_height=1.25)
        y = pdf.write_at(text_x, event_end + 1.5, text_width, description, 10, rgb=body, line_height=1.5, rich=True) + 9
    pdf.line(axis, marks[0] + 2, axis, marks[-1] + 2)
    for mark in marks:
        pdf.set_fill_color(*(pdf.theme.rgb("night") if dark else pdf.theme.rgb("paper")))
        pdf.set_draw_color(*tone)
        pdf.set_line_width(0.6)
        pdf.ellipse(axis - 1.9, mark + 0.1, 3.8, 3.8, "DF")
    pdf.folio("Timeline", on_dark=dark)
    return y - 9, content_limit
