import json
import re
from functools import lru_cache

from markitdoc.utils.constants import ASSETS_FOLDER

icons_folder = ASSETS_FOLDER / "icons"
icon_names = tuple(sorted(path.stem for path in icons_folder.glob("*.svg")))
featured_icons = tuple(line.strip() for line in (icons_folder / "featured.txt").read_text().splitlines() if line.strip())
icon_aliases = json.loads((icons_folder / "aliases.json").read_text())
shortcode = re.compile(r"^:([a-z0-9-]+):\s*")
license_comment = re.compile(rb"<!--.*?-->\s*", re.S)


# returns a supported icon name after resolving aliases
def known_icon(name: str) -> str | None:
    name = icon_aliases.get(name, name)
    return name if name in icon_names else None


# loads an icon and replaces its stroke with the requested color
@lru_cache(maxsize=None)
def icon_svg(name: str, rgb: tuple[int, int, int]) -> bytes | None:
    name = known_icon(name)
    if not name:
        return None
    color = "#%02x%02x%02x" % tuple(rgb)
    svg = re.sub(rb"\s+", b" ", license_comment.sub(b"", (icons_folder / f"{name}.svg").read_bytes()).strip())
    return svg.replace(b'stroke="currentColor"', f'stroke="{color}"'.encode())


# removes a recognized icon shortcode from the start of text
def strip_icon(text: str) -> tuple[str | None, str]:
    match = shortcode.match(text)
    name = known_icon(match.group(1)) if match else None
    if not name:
        return None, text
    return name, text[match.end():]
