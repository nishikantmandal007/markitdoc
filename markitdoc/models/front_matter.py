import re

from markitdoc.models.model_constants import BARE_DIRECTIVE, BARE_DIRECTIVES, FREE_TEXT_SETTINGS


# settings between --- lines at the top, then the markdown after them
def front_matter(markdown):
    lines = (markdown or "").lstrip("\n").split("\n")
    if not lines or lines[0].strip() != "---" or "---" not in [line.strip() for line in lines[1:]]:
        return bare_directives(markdown or "")
    end = [line.strip() for line in lines].index("---", 1)
    meta = {}
    for line in lines[1:end]:
        if ":" in line:
            key, value = line.split(":", 1)
            key, value = key.strip().lower(), value.strip().strip("'\"").strip()
            meta[key] = value if key in FREE_TEXT_SETTINGS else value.lower()
    return meta, "\n".join(lines[end + 1:])


# older documents: 'toc: true' style lines before or just after the # title, without --- fences
def bare_directives(markdown):
    lines = markdown.split("\n")
    meta = {}
    start = consume_directives(lines, first_text_line(lines, 0), meta)
    title = first_text_line(lines, start)
    if title < len(lines) and re.match(r"^#\s+", lines[title].strip()):
        before = len(meta)
        after = consume_directives(lines, title + 1, meta)
        if len(meta) > before:
            return meta, "\n".join([lines[title]] + lines[after:])
    if not meta:
        return {}, markdown
    return meta, "\n".join(lines[first_text_line(lines, start):])


# index of the first non-blank line from start
def first_text_line(lines, start):
    while start < len(lines) and not lines[start].strip():
        start += 1
    return start


# read known 'key: value' lines into meta and return where they stop
def consume_directives(lines, start, meta):
    while start < len(lines):
        stripped = lines[start].strip()
        if not stripped:
            start += 1
            continue
        match = BARE_DIRECTIVE.match(stripped)
        if not match:
            break
        key, value = match.group(1).lower(), match.group(2).lower()
        if value not in BARE_DIRECTIVES.get(key, frozenset()):
            break
        meta[key] = value
        start += 1
    return start
