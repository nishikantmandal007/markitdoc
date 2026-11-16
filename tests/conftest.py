from pathlib import Path

from markitdoc.themes import register_brand

register_brand(Path(__file__).parent / "fixtures" / "brand")
