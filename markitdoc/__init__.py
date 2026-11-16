import logging

from markitdoc.errors import EmptyDocumentError, MarkitDocError, RenderError, ThemeError, UnsupportedFormatError
from markitdoc.guide.contract import guide
from markitdoc.models.document import Block, Document, parse_document
from markitdoc.options import Options
from markitdoc.rendering import FORMATS, render
from markitdoc.themes.brands import BrandHooks, register_brand
from markitdoc.themes.themes import Theme, available_themes, load_theme

logging.getLogger("markitdoc").addHandler(logging.NullHandler())
