import re
from dataclasses import replace

from markitdoc.markup.blocks import prepared, slot_pieces
from markitdoc.models.catalogue import CONTENT_LIMIT, LAYOUTS
from markitdoc.models.document import Document
from markitdoc.pdf.pages import PdfPages, shrink_steps
from markitdoc.pdf.photos import measuring_photo
from markitdoc.pdf.render import draw_block
from markitdoc.themes.themes import Theme

tightness_steps = (1.0, 0.92, 0.85)


# returns the validation messages for every page in the document
def problems_in(document: Document, theme: Theme | None = None) -> list[str]:
    return [message for _, message in page_problems(document, theme)]


# checks page content for layout, length, chart, diagram, and image problems
def page_problems(document: Document, theme: Theme | None = None, with_images: bool = False, fitted: dict | None = None,
                  credits=(), sparse: set | None = None) -> list[tuple[int, str]]:
    from markitdoc.markup.elements import chart_data
    from markitdoc.themes.themes import load_theme
    from markitdoc.visuals.diagrams import problems_in_diagram
    from markitdoc.visuals.infographics import problems_in_infographic
    measurer = PdfPages(theme or load_theme(None))
    measurer.add_page()
    found = []
    for index, block in enumerate(document.blocks):
        block = prepared(block)
        layout = LAYOUTS.get(block.layout)
        where = f"page {index + 1} ({block.layout})"
        if layout is None:
            found.append((index, f"page {index + 1}: unknown layout '{block.layout}', use one of {sorted(LAYOUTS)}"))
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
                    block.layout in ("quote", "closing") or (block.layout != "cover" and end < CONTENT_LIMIT * 0.7)):
                sparse.add(index)
            elif tightness < 1 and fitted is not None:
                fitted[index] = tightness
    return found


# extracts matching code fences from a markdown body
def fences(body, language):
    found = []
    for suffix, content in re.findall(rf"```{language}([^\n]*)\n(.*?)```", body, re.S):
        suffix = suffix.split("{")[0].strip()
        found.append((f"{language} {suffix}\n" if suffix else "") + content)
    return found
