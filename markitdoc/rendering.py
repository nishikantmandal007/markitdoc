import logging
import re
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from markitdoc.docx.render import DOCUMENT_PHOTO_RATIOS, render_docx
from markitdoc.errors import EmptyDocumentError, UnsupportedFormatError
from markitdoc.markup.blocks import as_flow
from markitdoc.markup.fields import field_values, with_fields
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.models.document import Document, parse_document
from markitdoc.models.front_matter import front_matter_yaml
from markitdoc.models.references import number_document, resolve_document
from markitdoc.options import Options, options_in_use, using_options
from markitdoc.pdf.checks import page_problems
from markitdoc.pdf.render import render_pdf
from markitdoc.pptx.render import SLIDE_PHOTO_RATIOS, render_pptx
from markitdoc.themes.stylesheet import load_stylesheet
from markitdoc.themes.themes import theme_for
from markitdoc.visuals.images import find_images

logger = logging.getLogger(__name__)

FORMATS = ("pdf", "pptx", "docx")
TRUE_WORDS = ("true", "yes", "on", True)
PAGE_REFERENCE_PASSES = 2


# the stylesheet of a document: its theme, style files and front matter layered
def stylesheet_for(markdown, theme):
    return load_stylesheet(front_matter_yaml(markdown) or {}, theme, options_in_use().style_folders)


# photos for designed blocks and markdown figures, when the document asks for them
def images_for(document, require_images, ratio_of=None):
    if not require_images:
        return {}, ()
    ratio_of = ratio_of or {name: layout.image_ratio for name, layout in LAYOUTS.items()}
    wanted = {index: block.slots["image"] for index, block in enumerate(document.blocks)
              if block.slots.get("image") and ratio_of.get(block.layout)}
    ratios = {index: ratio_of[document.blocks[index].layout] for index in wanted}
    for block in document.blocks:
        for caption in re.findall(r"!\[([^\]]+)\]\([^)]*\)", block.body if block.layout == "flow" else ""):
            wanted[("figure", caption)], ratios[("figure", caption)] = caption, 1.5
    found = find_images(wanted, ratios) if wanted else {}
    return {key: (image.path, image.caption, image.short_credit, image.source) for key, image in found.items()}, ()


# is most of the document's text in Devanagari script?
def written_in_devanagari(document):
    text = " ".join(block.body + " ".join(block.slots.values()) for block in document.blocks)
    letters = [character for character in text if character.isalpha()]
    return bool(letters) and sum("ऀ" <= character <= "ॿ" for character in letters) / len(letters) > 0.5


# a parsed document to a PDF, drawn again once when page references need the pages recorded by the first drawing
def render_laid_out_pdf(document, output_path, template, markdown=""):
    started = time.perf_counter()
    theme = theme_for(document.meta, template)
    styles = stylesheet_for(markdown, theme)
    document, numbering = number_document(with_fields(document, field_values(styles, document.meta)), styles)
    pages = {}
    for _ in range(PAGE_REFERENCE_PASSES if numbering.wants_pages else 1):
        found = {}
        draw_pdf(resolve_document(document, numbering, "pdf", pages), output_path, theme, styles, numbering, found)
        if found == pages:
            break
        pages = found
    logger.info("Rendered PDF: %d blocks, %.1f s", len(document.blocks), time.perf_counter() - started)
    return output_path


# one drawing of a parsed document to a PDF, falling back to plain text for pages that do not fit their design; recorded pages go to found
def draw_pdf(document, output_path, theme, styles, numbering, found):
    started = time.perf_counter()
    wants_images = document.meta.get("images") in TRUE_WORDS
    if not document.meta.get("lang") and written_in_devanagari(document):
        document = Document({**document.meta, "lang": "hi"}, document.blocks)
    tightened, sparse = {}, set()
    images, credits = images_for(document, wants_images)
    problems = page_problems(document, theme, wants_images, tightened, credits, sparse)
    for _, message in problems:
        logger.warning("PDF page problem (designed pages fall back to text, bad visuals are skipped): %s", message)
    broken = {index for index, _ in problems if document.blocks[index].layout != "flow"} | sparse
    if sparse:
        logger.info("Designed pages with too little content for a full page, printed as normal text: %s", sorted(sparse))
    document = Document(document.meta, tuple(
        as_flow(block) if index in broken
        else replace(block, slots={**block.slots, "tightness": tightened[index]}) if index in tightened else block
        for index, block in enumerate(document.blocks)))
    if tightened:
        logger.info("Tightened line spacing on %d pages to fit: %s", len(tightened), tightened)
    with tempfile.TemporaryDirectory() as work_folder:
        render_pdf(document, theme, output_path, Path(work_folder), images, credits, styles, numbering, found)
    logger.info("Drew PDF: %d blocks, theme %s, %d images, %d bytes, %.1f s, %d pages shown as text",
                len(document.blocks), theme.name, len(images), output_path.stat().st_size, time.perf_counter() - started, len(broken))


# a parsed document to a PowerPoint deck
def render_laid_out_pptx(document, output_path, template, author, markdown=""):
    started = time.perf_counter()
    theme = theme_for(document.meta, template)
    styles = stylesheet_for(markdown, theme)
    document, numbering = number_document(with_fields(document, field_values(styles, document.meta)), styles, inject=False)
    document = resolve_document(document, numbering, "pptx")
    images, _ = images_for(document, document.meta.get("images") in TRUE_WORDS, SLIDE_PHOTO_RATIOS)
    render_pptx(document, theme, output_path, images, author, styles, numbering)
    logger.info("Rendered PPTX: %d blocks, theme %s, %d images, %d bytes, %.1f s", len(document.blocks), theme.name, len(images),
                output_path.stat().st_size, time.perf_counter() - started)
    return output_path


# a parsed document to a Word file
def render_laid_out_docx(document, output_path, template, author, markdown=""):
    started = time.perf_counter()
    theme = theme_for(document.meta, template)
    styles = stylesheet_for(markdown, theme)
    document, numbering = number_document(with_fields(document, field_values(styles, document.meta)), styles)
    document = resolve_document(document, numbering, "docx")
    images, _ = images_for(document, document.meta.get("images") in TRUE_WORDS, DOCUMENT_PHOTO_RATIOS)
    render_docx(document, theme, output_path, images, author, styles, numbering)
    logger.info("Rendered DOCX: %d blocks, theme %s, %d images, %d bytes, %.1f s", len(document.blocks), theme.name, len(images),
                output_path.stat().st_size, time.perf_counter() - started)
    return output_path


# markdown to a PDF, PowerPoint or Word file at output; returns the written path
def render(markdown, output_format, output, template="default", author="", options=None):
    if output_format not in FORMATS:
        raise UnsupportedFormatError(f"Unsupported format {output_format!r}, expected one of {', '.join(FORMATS)}")
    if not markdown or not markdown.strip():
        raise EmptyDocumentError("The markdown is empty")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Rendering %s: %d characters, template %s, to %s", output_format, len(markdown), template, output_path)
    with using_options(options or Options()):
        if output_format == "docx":
            return render_laid_out_docx(parse_document(markdown), output_path, template, author, markdown)
        if output_format == "pptx":
            return render_laid_out_pptx(parse_document(markdown), output_path, template, author, markdown)
        return render_laid_out_pdf(parse_document(markdown), output_path, template, markdown)
