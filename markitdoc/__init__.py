import logging

from markitdoc.errors import EmptyDocumentError, MarkitDocError, RenderError, ThemeError, UnsupportedFormatError
from markitdoc.guide.contract import guide
from markitdoc.models.attributes import Attributes, parse_attributes
from markitdoc.models.checks import Finding, check_document
from markitdoc.models.document import Block, Document, parse_document
from markitdoc.options import Options
from markitdoc.rendering import FORMATS, render
from markitdoc.themes.brands import BrandHooks, brand_summary, register_brand, registered_brands
from markitdoc.themes.themes import Theme, available_themes, load_theme

logging.getLogger("markitdoc").addHandler(logging.NullHandler())
