import hashlib
import io
import json
import logging
import os
import re
from pathlib import Path

import requests
from PIL import Image, ImageChops

from markitdoc.utils.constants import ASSETS_FOLDER, CACHE_FOLDER

logger = logging.getLogger(__name__)

antv_bundle = ASSETS_FOLDER / "vendor" / "antv-infographic-0.2.20.min.js"
infographic_folder = CACHE_FOLDER / "infographics"
canvas_width, canvas_height, zoom = 800, 460, 2
infographic_templates = {
    "sequence-steps-badge-card": ("sequences", "numbered steps of a process, 3 to 6"),
    "list-row-simple-horizontal-arrow": ("lists", "a short flow of 3 to 5 stages"),
    "list-grid-badge-card": ("lists", "4 to 6 parallel ideas or features"),
    "list-grid-compact-card": ("lists", "3 to 6 headline figures; each item has label, desc and value"),
    "list-pyramid-badge-card": ("lists", "3 to 5 levels from foundation (last) to top (first)"),
    "compare-swot": ("compares", "SWOT: exactly 4 groups Strengths, Weaknesses, Opportunities, Threats with children"),
    "compare-binary-horizontal-badge-card-fold": ("compares", "two sides (before / after, option A / B) with children"),
    "chart-column-simple": ("values", "3 to 8 values over time or categories; each item has label and value"),
    "chart-pie-donut-plain-text": ("values", "2 to 6 parts of a whole; each item has label and value"),
}
page = """<!doctype html><html><head><meta charset="utf-8">
<style>@font-face{font-family:Brand;src:url(brand.ttf)}@font-face{font-family:Brand;font-weight:700;src:url(brand-bold.ttf)}
html{zoom:%d}html,body{margin:0;background:#fff;font-family:Brand}#chart{width:%dpx;height:%dpx}</style>
<script src="antv.js"></script><script src="data.js"></script></head><body><div id="chart"></div><script>
document.documentElement.style.background = window.paper;
document.fonts.load("16px Brand").then(() => document.fonts.load("bold 16px Brand")).then(() => {
  AntVInfographic.setDefaultFont("Brand");
  new AntVInfographic.Infographic({container: "#chart", width: %d, height: %d, editable: false}).render(window.syntax);
  setTimeout(() => { window.rendered = true; }, 300);
});
</script></body></html>""" % (zoom, canvas_width, canvas_height, canvas_width, canvas_height)


# adds a missing data-list key required by an infographic template
def with_data_key(syntax: str) -> str:
    lines = syntax.strip().splitlines()
    first = lines[0].split() if lines else []
    key = infographic_templates.get(first[1], ("",))[0] if len(first) == 2 else ""
    if not key or any(line.strip() == key for line in lines):
        return syntax.strip()
    items = [index for index, line in enumerate(lines) if line.strip().startswith("- ")]
    if not items:
        return syntax.strip()
    start = items[0]
    return "\n".join(lines[:start] + [f"  {key}"] + ["  " + line for line in lines[start:]])


# returns validation problems found in infographic syntax
def problems_in_infographic(syntax: str) -> list[str]:
    lines = [line for line in with_data_key(syntax).splitlines() if line.strip()]
    first = lines[0].split() if lines else []
    if len(first) != 2 or first[0] != "infographic" or first[1] not in infographic_templates:
        return [f"first line must be 'infographic <template>' with a template from {sorted(infographic_templates)}"]
    data_key = infographic_templates[first[1]][0]
    if not any(line.strip() == data_key for line in lines):
        return [f"template {first[1]} needs a '{data_key}' list under data"]
    values = [line.strip()[6:].replace(",", "").rstrip("%") for line in lines if line.strip().startswith("value ")]
    if any(not re.fullmatch(r"-?\d+(\.\d+)?", value) for value in values):
        return ["every 'value' must be a plain number (put units in the label or desc)"]
    if any(line.strip() == "theme" for line in lines):
        return ["leave out the theme block, colours come from the document theme"]
    return []


# adds document theme colors to infographic syntax
def themed(syntax: str, theme) -> str:
    first, rest = with_data_key(syntax).split("\n", 1)
    palette = " ".join("#" + theme.colors[role].lstrip("#") for role in ("mood", "accent", "primary", "muted"))
    return (f"{first}\ntheme\n  colorPrimary #{theme.colors['mood'].lstrip('#')}\n  colorBg #{theme.colors['paper'].lstrip('#')}"
            f"\n  palette {palette}\n{rest}")


# renders a validated infographic and reuses cached images
def render_infographic(syntax: str, theme) -> Path | None:
    endpoint = os.getenv("GOTENBERG_ENDPOINT")
    if not endpoint or problems_in_infographic(syntax):
        return None
    source = themed(syntax, theme)
    key = "|".join([source, theme.name, antv_bundle.name, Path(theme.fonts["body"]).name, Path(theme.fonts["heading"]).name])
    path = infographic_folder / f"{hashlib.sha1(key.encode()).hexdigest()}.png"
    if path.exists():
        return path
    files = [("files", ("index.html", page.encode(), "text/html")),
             ("files", ("antv.js", antv_bundle.read_bytes(), "text/javascript")),
             ("files", ("data.js", f"window.syntax = {json.dumps(source)}; window.paper = '#{theme.colors['paper'].lstrip('#')}';".encode(), "text/javascript")),
             ("files", ("brand.ttf", Path(theme.fonts["body"]).read_bytes(), "font/ttf")),
             ("files", ("brand-bold.ttf", Path(theme.fonts["heading"]).read_bytes(), "font/ttf"))]
    form = {"width": str(canvas_width * zoom), "height": str(canvas_height * zoom), "format": "png",
            "waitForExpression": "window.rendered === true", "skipNetworkIdleEvent": "true"}
    try:
        response = requests.post(f"{endpoint.rstrip('/')}/forms/chromium/screenshot/html", files=files, data=form, timeout=60)
    except requests.RequestException as error:
        logger.warning("Infographic render failed: %s", type(error).__name__)
        return None
    if response.status_code != 200:
        logger.warning("Infographic render failed: HTTP %d", response.status_code)
        return None
    picture = Image.open(io.BytesIO(response.content)).convert("RGB")
    box = ImageChops.difference(picture, Image.new("RGB", picture.size, picture.getpixel((2, 2)))).getbbox()
    if box is None:
        logger.warning("Infographic render was blank: template %s", source.split()[1])
        return None
    left, top, right, bottom = box
    path.parent.mkdir(parents=True, exist_ok=True)
    picture.crop((max(0, left - 24), max(0, top - 24), min(picture.width, right + 24), min(picture.height, bottom + 24))).save(path)
    return path
