import logging
import re
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from markitdoc.docx.render import DOCUMENT_PHOTO_RATIOS, render_docx
from markitdoc.errors import EmptyDocumentError, UnsupportedFormatError
from markitdoc.markup.blocks import as_flow
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.models.document import Document, parse_document
from markitdoc.models.front_matter import front_matter_yaml, language_version
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


# the stylesheet of a language v2 document, None for version 1 documents which keep today's rendering
def stylesheet_for(document, markdown, theme):
    if language_version(document.meta) != 2:
        return None
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


# a parsed document to a PDF, falling back to plain text for pages that do not fit their design
def render_laid_out_pdf(document, output_path, template, markdown=""):
    started = time.perf_counter()
    theme = theme_for(document.meta, template)
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
        render_pdf(document, theme, output_path, Path(work_folder), images, credits, stylesheet_for(document, markdown, theme))
    logger.info("Rendered PDF: %d blocks, theme %s, %d images, %d bytes, %.1f s, %d pages shown as text",
                len(document.blocks), theme.name, len(images), output_path.stat().st_size, time.perf_counter() - started, len(broken))
    return output_path


# a parsed document to a PowerPoint deck
def render_laid_out_pptx(document, output_path, template, author):
    started = time.perf_counter()
    theme = theme_for(document.meta, template)
    images, _ = images_for(document, document.meta.get("images") in TRUE_WORDS, SLIDE_PHOTO_RATIOS)
    render_pptx(document, theme, output_path, images, author)
    logger.info("Rendered PPTX: %d blocks, theme %s, %d images, %d bytes, %.1f s", len(document.blocks), theme.name, len(images),
                output_path.stat().st_size, time.perf_counter() - started)
    return output_path


# a parsed document to a Word file
def render_laid_out_docx(document, output_path, template, author, markdown=""):
    started = time.perf_counter()
    theme = theme_for(document.meta, template)
    images, _ = images_for(document, document.meta.get("images") in TRUE_WORDS, DOCUMENT_PHOTO_RATIOS)
    render_docx(document, theme, output_path, images, author, stylesheet_for(document, markdown, theme))
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
            return render_laid_out_pptx(parse_document(markdown), output_path, template, author)
        return render_laid_out_pdf(parse_document(markdown), output_path, template, markdown)
