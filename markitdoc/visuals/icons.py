import json
import re
from functools import lru_cache

from markitdoc.utils.constants import ASSETS_FOLDER

ICONS_FOLDER = ASSETS_FOLDER / "icons"
ICON_NAMES = tuple(sorted(path.stem for path in ICONS_FOLDER.glob("*.svg")))
FEATURED_ICONS = tuple(line.strip() for line in (ICONS_FOLDER / "featured.txt").read_text().splitlines() if line.strip())
ICON_ALIASES = json.loads((ICONS_FOLDER / "aliases.json").read_text())
SHORTCODE = re.compile(r"^:([a-z0-9-]+):\s*")
LICENSE_COMMENT = re.compile(rb"<!--.*?-->\s*", re.S)


# returns a supported icon name after resolving aliases
def known_icon(name: str) -> str | None:
    name = ICON_ALIASES.get(name, name)
    return name if name in ICON_NAMES else None


# loads an icon and replaces its stroke with the requested color
@lru_cache(maxsize=None)
def icon_svg(name: str, rgb: tuple[int, int, int]) -> bytes | None:
    name = known_icon(name)
    if not name:
        return None
    color = "#%02x%02x%02x" % tuple(rgb)
    svg = re.sub(rb"\s+", b" ", LICENSE_COMMENT.sub(b"", (ICONS_FOLDER / f"{name}.svg").read_bytes()).strip())
    return svg.replace(b'stroke="currentColor"', f'stroke="{color}"'.encode())


# removes a recognized icon shortcode from the start of text
def strip_icon(text: str) -> tuple[str | None, str]:
    match = SHORTCODE.match(text)
    name = known_icon(match.group(1)) if match else None
    if not name:
        return None, text
    return name, text[match.end():]
