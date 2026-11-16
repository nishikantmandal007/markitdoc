import hashlib
import io
import json
import logging
import os
import re
from pathlib import Path

import requests
from PIL import Image, ImageChops

from markitdoc.themes.themes import mixed
from markitdoc.utils.constants import ASSETS_FOLDER, CACHE_FOLDER

logger = logging.getLogger(__name__)

MERMAID_BUNDLE = ASSETS_FOLDER / "vendor" / "mermaid-11.4.1.min.js"
DIAGRAM_FOLDER = CACHE_FOLDER / "diagrams"
CANVAS_WIDTH, CANVAS_HEIGHT, ZOOM = 800, 1100, 2
DIRECTED_TYPES = {"flowchart": ("TD", "LR", "TB", "RL"), "graph": ("TD", "LR")}
PLAIN_TYPES = ("sequenceDiagram", "stateDiagram-v2", "classDiagram", "erDiagram", "timeline", "mindmap", "gantt", "pie")
DIAGRAM_TYPES = tuple(f"{kind} {direction}" for kind, directions in DIRECTED_TYPES.items() for direction in directions) + PLAIN_TYPES
LISTED_TYPES = ("pie", "timeline", "gantt", "mindmap")
SETTING_WORDS = {"title", "dateFormat", "axisFormat", "tickInterval", "excludes", "todayMarker", "weekday", "direction", "classDef",
                 "class", "style", "linkStyle", "click", "subgraph", "end", "participant", "actor", "section", "note", "Note", "loop",
                 "alt", "else", "opt", "par", "and", "rect", "critical", "break", "autonumber", "activate", "deactivate", "showData",
                 "state", "accTitle", "accTitle:", "accDescr", "accDescr:", "}"}
SPOKEN_TYPES = ("sequenceDiagram", "stateDiagram-v2", "classDiagram", "erDiagram")
NODE = re.compile(r'(\w+)\s*(?:\[\[|\[\(|\(\(|\(\[|\[/|\[\\|\{\{|\[|\(|\{)\s*"?(.*?)"?\s*(?:\]\]|\)\]|\)\)|\]\)|/\]|\\\]|\}\}|\]|\)|\})')
LABELLED_LINK = re.compile(r"(?<![-=.])(--|==|-\.)(?![->.=])\s+([^|>]+?)\s+(-->|==>|\.->|---|-\.-)")
ARROW = re.compile(r"\s*((?:[}|]o|(?<=\s)o)?[<>|}{*=.\-]*(?:--|==|\.\.|-\.|->|-x|-\))[<>{}*=.\-)]*(?:\|[{|]|o[{|]|[ox](?=\s|$))?)"
                   r"\s*(?:\|([^|]*)\|)?\s*")
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>@font-face{font-family:Brand;src:url(brand.ttf)}@font-face{font-family:Brand;font-weight:700;src:url(brand-bold.ttf)}
html,body{margin:0;font-family:Brand}#diagram{width:%dpx;padding:16px;box-sizing:border-box}
#diagram svg{max-height:%dpx}</style>
<script src="mermaid.js"></script><script src="data.js"></script></head><body><div id="diagram"></div><script>
document.documentElement.style.background = window.paper;
document.fonts.load("16px Brand").then(() => document.fonts.load("bold 16px Brand")).then(() => {
  mermaid.initialize(window.settings);
  return mermaid.render("diagram-svg", window.source);
}).then((result) => {
  document.getElementById("diagram").innerHTML = result.svg;
  document.documentElement.style.zoom = window.zoom;
  setTimeout(() => { window.rendered = true; }, 200);
}).catch(() => {
  document.body.innerHTML = "";
  window.failed = true;
  window.rendered = true;
});
</script></body></html>""" % (CANVAS_WIDTH, CANVAS_HEIGHT - 32)


# returns the first meaningful line of diagram source
def first_line(source: str) -> str:
    return next((line.strip() for line in source.splitlines() if line.strip() and not line.strip().startswith("%%")), "")


# returns validation problems found in diagram source
def problems_in_diagram(source: str) -> list[str]:
    words = first_line(source).split()
    if not words:
        return ["the diagram is empty"]
    kind = words[0]
    if kind in DIRECTED_TYPES and len(words) > 1 and words[1] in DIRECTED_TYPES[kind]:
        return []
    if kind in PLAIN_TYPES:
        return []
    if kind in DIRECTED_TYPES:
        return [f"'{kind}' needs a direction on the first line: one of {', '.join(DIRECTED_TYPES[kind])}, e.g. '{kind} LR'"]
    return [f"first line must name the diagram type, one of: {', '.join(DIAGRAM_TYPES)} (found '{first_line(source)[:40]}')"]


# builds Mermaid theme settings from the document palette
def settings(theme) -> dict:
    color = {role: "#" + theme.colors[role].lstrip("#") for role in ("mood", "second", "ink", "muted", "paper", "surface", "rule")}
    variables = {"primaryColor": "#" + mixed(theme.colors["mood"].lstrip("#"), theme.colors["paper"].lstrip("#"), 0.86),
                 "primaryBorderColor": color["mood"], "primaryTextColor": color["ink"],
                 "secondaryColor": "#" + mixed(theme.colors["second"].lstrip("#"), theme.colors["paper"].lstrip("#"), 0.86),
                 "secondaryBorderColor": color["second"], "tertiaryColor": color["surface"], "tertiaryBorderColor": color["rule"],
                 "lineColor": color["muted"], "background": color["paper"], "mainBkg": "#" + mixed(theme.colors["mood"].lstrip("#"),
                 theme.colors["paper"].lstrip("#"), 0.86), "textColor": color["ink"], "titleColor": color["ink"], "edgeLabelBackground": color["paper"],
                 "fontFamily": "Brand", "fontSize": "16px"}
    return {"startOnLoad": False, "securityLevel": "strict", "theme": "base", "themeVariables": variables,
            "deterministicIds": True, "suppressErrorRendering": True, "htmlLabels": True,
            "flowchart": {"htmlLabels": True}, "gantt": {"todayMarker": "off"}}


# renders a validated Mermaid diagram and reuses cached images
def render_diagram(source: str, theme) -> Path | None:
    endpoint = os.getenv("GOTENBERG_ENDPOINT")
    if not endpoint or problems_in_diagram(source):
        return None
    configuration = json.dumps(settings(theme), sort_keys=True)
    key = "|".join([source.strip(), theme.name, configuration, MERMAID_BUNDLE.name, Path(theme.fonts["body"]).name,
                    Path(theme.fonts["heading"]).name])
    path = DIAGRAM_FOLDER / f"{hashlib.sha1(key.encode()).hexdigest()}.png"
    if path.exists():
        return path
    data = (f"window.source = {json.dumps(source.strip())}; window.settings = {configuration}; "
            f"window.paper = '#{theme.colors['paper'].lstrip('#')}'; window.zoom = {ZOOM};")
    files = [("files", ("index.html", PAGE.encode(), "text/html")),
             ("files", ("mermaid.js", MERMAID_BUNDLE.read_bytes(), "text/javascript")),
             ("files", ("data.js", data.encode(), "text/javascript")),
             ("files", ("brand.ttf", Path(theme.fonts["body"]).read_bytes(), "font/ttf")),
             ("files", ("brand-bold.ttf", Path(theme.fonts["heading"]).read_bytes(), "font/ttf"))]
    form = {"width": str(CANVAS_WIDTH * ZOOM), "height": str(CANVAS_HEIGHT * ZOOM), "format": "png",
            "waitForExpression": "window.rendered === true", "skipNetworkIdleEvent": "true"}
    try:
        response = requests.post(f"{endpoint.rstrip('/')}/forms/chromium/screenshot/html", files=files, data=form, timeout=60)
    except requests.RequestException as error:
        logger.warning("Diagram render failed: %s", type(error).__name__)
        return None
    if response.status_code != 200:
        logger.warning("Diagram render failed: HTTP %d", response.status_code)
        return None
    try:
        picture = Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as error:
        logger.warning("Diagram render failed: %s", type(error).__name__)
        return None
    box = ImageChops.difference(picture, Image.new("RGB", picture.size, picture.getpixel((2, 2)))).getbbox()
    if box is None:
        logger.warning("Diagram render was blank (mermaid could not read it): %s", first_line(source)[:40])
        return None
    left, top, right, bottom = box
    path.parent.mkdir(parents=True, exist_ok=True)
    picture.crop((max(0, left - 24), max(0, top - 24), min(picture.width, right + 24), min(picture.height, bottom + 24))).save(path)
    return path


# extracts readable labels from diagram nodes
def node_labels(source: str) -> dict:
    return {name: readable(label) for name, label in NODE.findall(source) if readable(label)}


# cleans diagram markup from a node label
def readable(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r":::\w+", "", text)
    return " ".join(text.strip().strip('"').strip("'").split())


# returns a readable node label, including start and end markers
def named(part: str, labels: dict, start: bool) -> str:
    part = part.strip()
    if part == "[*]":
        return "Start" if start else "End"
    found = NODE.fullmatch(part)
    if found:
        return readable(found.group(2)) or found.group(1)
    return labels.get(readable(part), readable(part).strip("[](){}"))


# converts diagram connections into readable labeled lines
def edge_lines(line: str, labels: dict, kind: str) -> list[str]:
    line = LABELLED_LINK.sub(lambda match: f"{match.group(3)}|{match.group(2)}|", line)
    note = ""
    if kind in SPOKEN_TYPES:
        line, _, note = line.partition(" : ") if " : " in line else line.partition(":")
    pieces = ARROW.split(line)
    names, links = pieces[::3], pieces[2::3]
    result = []
    for index, (source, target) in enumerate(zip(names, names[1:])):
        text = f"{named(source, labels, True)} → {named(target, labels, False)}"
        extra = readable(links[index] or "") or (readable(note) if index == len(names) - 2 else "")
        result.append(f"{text}: {extra}" if extra else text)
    return result


# converts diagram connections into readable text lines
def diagram_as_text(source: str) -> list[str]:
    kind = first_line(source).split()[0] if first_line(source) else ""
    labels = node_labels(source) if kind in DIRECTED_TYPES else {}
    labels.update({name: readable(label) for name, label in re.findall(r"(?:participant|actor)\s+(\w+)\s+as\s+(.+)", source)})
    lines, body = [], source.strip().splitlines()[1:]
    for raw in body:
        line = raw.strip()
        if not line or line.startswith(("%%", "::")) or line.split()[0] in SETTING_WORDS:
            continue
        if ARROW.search(line) and kind not in LISTED_TYPES:
            lines += edge_lines(line, labels, kind)
        elif kind in LISTED_TYPES:
            left, _, right = line.partition(":")
            found = NODE.fullmatch(left.strip())
            left = readable(found.group(2)) if found else readable(left)
            lines.append(f"{left}: {readable(right)}" if readable(right) else left)
    unique = []
    for line in lines:
        if line and line not in unique:
            unique.append(line)
    return unique


# returns sequential steps when a diagram forms a simple chain
def chain_steps(source: str) -> list[tuple[str, str]]:
    if first_line(source).split()[:1] not in (["flowchart"], ["graph"]):
        return []
    following, notes, incoming = {}, {}, {}
    for line in diagram_as_text(source):
        link, _, note = line.partition(": ")
        start, arrow_mark, end = link.partition(" → ")
        if not arrow_mark or start in following:
            return []
        following[start], notes[end], incoming[end] = end, note, incoming.get(end, 0) + 1
    starts = [name for name in following if name not in incoming]
    if len(starts) != 1 or any(count > 1 for count in incoming.values()):
        return []
    steps, current = [(starts[0], "")], starts[0]
    while current in following and len(steps) <= len(following):
        current = following[current]
        steps.append((current, notes.get(current, "")))
    return steps if len(steps) == len(following) + 1 and len({name for name, _ in steps}) == len(steps) else []


# chooses a title from the diagram or its first readable label
def diagram_title(source: str) -> str:
    title = next((line.strip()[6:].strip() for line in source.splitlines() if line.strip().startswith("title ")), "")
    words = first_line(source).split()
    if not title and len(words) > 2 and words[0] == "pie" and words[1] == "title":
        title = " ".join(words[2:])
    labels = list(node_labels(source).values()) if words and words[0] in (*DIRECTED_TYPES, "mindmap") else []
    return title or (labels[0] if labels else (words[0] if words else "diagram"))
