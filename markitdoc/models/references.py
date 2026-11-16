from dataclasses import dataclass, field, replace
from difflib import get_close_matches

from markitdoc.markup.elements import IMAGE_WRITTEN, chart_data, written_image
from markitdoc.markup.inline import ANCHOR, literal, plain_text
from markitdoc.markup.latex import latex_text
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.document import Document
from markitdoc.models.editorial import citation_style, citation_text, cited_keys, load_refs, with_editorial
from markitdoc.models.model_constants import (
    CAPTION_LABELS,
    EQUATION_ID,
    FENCE_OPEN,
    HEADING_LINE,
    MERMAID_TITLE,
    NUMBERING_OFF,
    REFERENCE_LABELS,
    REFERENCE_TEXT,
    TABLE_CAPTION,
    TRAILING_BRACES,
)
from markitdoc.options import options_in_use


@dataclass(frozen=True)
class Target:
    id: str
    kind: str
    number: str
    label: str
    mark: str
    text: str
    line: int


@dataclass
class Numbering:
    references: dict
    captions: dict
    section_numbers: bool = False
    refs: dict = field(default_factory=dict)
    style: str = "numeric"
    cited: list = field(default_factory=list)
    wants_pages: bool = False
    targets: dict = field(default_factory=dict)
    duplicates: list = field(default_factory=list)
    counts: dict = field(default_factory=lambda: {"figure": 0, "table": 0, "equation": 0})
    headings: list = field(default_factory=lambda: [0, 0, 0, 0])


# the numbering state of a document: label formats from set rules, whether headings are numbered, the refs entries and citation style
def new_numbering(sheet, meta):
    references, captions = dict(REFERENCE_LABELS), dict(CAPTION_LABELS)
    sections = str(meta.get("numbering", "")).lower() == "decimal"
    if sheet:
        for kind in ("figure", "table", "equation"):
            value = sheet.numbering(kind)
            if value and "{n}" in value:
                captions[kind] = value
                if kind != "equation":
                    references[kind] = value
        sections = sections or any(str(sheet.numbering(name)).lower() not in NUMBERING_OFF for name in ("h2", "h3", "h4")
                                   if sheet.numbering(name) is not None)
    return Numbering(references, captions, sections, style=citation_style(meta))


# records a target; an id seen before is noted as a duplicate and the first one is kept
def add_target(state, target):
    if target.id in state.targets:
        state.duplicates.append((target.id, target.line))
    else:
        state.targets[target.id] = target


# numbers a figure, table or equation, giving it an automatic id when it has none; returns the id
def register(state, kind, ident, text, line):
    state.counts[kind] += 1
    number = str(state.counts[kind])
    ident = ident or f"auto-{kind}-{number}"
    add_target(state, Target(ident, kind, number, state.references.get(kind, "").replace("{n}", number),
                             state.captions[kind].replace("{n}", number), text, line))
    return ident


# a line with {#id} added to its last or first attribute braces, or new braces at the end
def with_id(line, ident, last=True):
    found = TRAILING_BRACES.search(line) if last else None
    if found:
        return line[:found.start(1)] + f"#{ident} " + line[found.start(1):]
    if not last and "{" in line:
        return line.replace("{", "{#" + ident + " ", 1)
    return f"{line.rstrip()} {{#{ident}}}"


# numbers every labelled target in the lines in order, returning the lines with automatic ids added when asked
def number_lines(lines, state, first_line=1, inject=True):
    out, fence, index = [], "", 0
    while index < len(lines):
        line, number = lines[index], first_line + index
        stripped = line.strip()
        index += 1
        opening = FENCE_OPEN.match(stripped)
        if fence:
            fence = "" if stripped.startswith(fence) else fence
            out.append(line)
            continue
        if opening:
            fence = opening.group(1)
            info = opening.group(2).strip()
            language = info.split("{")[0].strip()
            if language in ("chart", "mermaid"):
                body = []
                for follow in lines[index:]:
                    if follow.strip().startswith(fence):
                        break
                    body.append(follow)
                attributes = parse_attributes(info[info.find("{"):]) if "{" in info else parse_attributes("")
                content = "\n".join(body)
                title = MERMAID_TITLE.search(content).group(1).strip() if language == "mermaid" and MERMAID_TITLE.search(content) else ""
                text = str(attributes.values.get("caption", "")) or title
                if (attributes.id or text) and (language == "mermaid" or chart_data(content)):
                    ident = register(state, "figure", attributes.id, text, number)
                    if inject and not attributes.id:
                        line = with_id(line, ident, last=False)
            out.append(line)
            continue
        if heading := HEADING_LINE.match(stripped):
            level, anchor = len(heading.group(1)), ANCHOR.search(heading.group(2))
            numbered = state.section_numbers and 2 <= level <= 4
            if numbered:
                state.headings[level - 1] += 1
                state.headings[level:] = [0] * (4 - level)
            if anchor:
                title = plain_text(ANCHOR.sub("", heading.group(2)))
                digits = ".".join(str(item) for item in state.headings[1:level]) if numbered else ""
                label = state.references["section"].replace("{n}", digits) if digits else title
                add_target(state, Target(anchor.group(1), "section", digits, label, "", title, number))
            out.append(line)
            continue
        if caption := TABLE_CAPTION.match(line):
            braces = TRAILING_BRACES.search(caption.group(1))
            attributes = parse_attributes(braces.group(1) if braces else "")
            ident = register(state, "table", attributes.id, TRAILING_BRACES.sub("", caption.group(1)).strip(), number)
            out.append(with_id(line, ident) if inject and not attributes.id else line)
            continue
        if equation := EQUATION_ID.search(line):
            if (ident := parse_attributes(equation.group(1)).id):
                register(state, "equation", ident, "", number)

        # an image written with a file path gets numbered when it has an id or a caption
        def image_found(match):
            if not written_image(match.group(0)):
                return match.group(0)
            attributes = parse_attributes(match.group(3) or "")
            text = str(attributes.values.get("caption", ""))
            if not (attributes.id or text):
                return match.group(0)
            ident = register(state, "figure", attributes.id, text, number)
            if not inject or attributes.id:
                return match.group(0)
            return f"![{match.group(1)}]({match.group(2)}){{#{ident} {match.group(3)}}}" if match.group(3) is not None \
                else f"![{match.group(1)}]({match.group(2)}){{#{ident}}}"

        out.append(IMAGE_WRITTEN.sub(image_found, line) if "![" in line else line)
    return out


# a document with its labelled targets numbered, plus the numbering found; inject adds automatic ids to unlabelled captioned elements
def number_document(document, sheet=None, inject=True):
    state, blocks = new_numbering(sheet, document.meta), []
    for block in document.blocks:
        body = "\n".join(number_lines(block.body.split("\n"), state, inject=inject))
        blocks.append(replace(block, body=body))
        texts = (body, *block.slots.values(), *(part for item in block.items for part in item))
        state.wants_pages = state.wants_pages or any(found.group(3) for text in texts for found in REFERENCE_TEXT.finditer(text))
    state.refs = load_refs(document.meta, options_in_use().style_folders)[0]
    state.cited = cited_keys([text for block in blocks for text in (block.body, *block.slots.values(), *(part for item in block.items for part in item))], state)
    if inject:
        blocks, listed = with_editorial(blocks, state, document.meta)
        state.wants_pages = state.wants_pages or listed
    return Document(document.meta, tuple(blocks)), state


# "a, b and c" from a list of texts
def joined(texts):
    return texts[0] if len(texts) == 1 else ", ".join(texts[:-1]) + " and " + texts[-1]


# one target as text, a link to the target when links are wanted
def piece(target, text, links):
    return f"[{literal(text)}](#{target.id})" if links else literal(text)


# the text of one page reference: a recorded page for PDF, a field marker for Word, the number for slides
def page_piece(target, mode, pages):
    if mode == "pdf":
        return piece(target, pages.get(target.id, "0"), True)
    if mode == "docx":
        return f"[?](#page:{target.id})"
    return literal(target.number or target.label)


# the text a reference stands for: "Figure 3", "Figures 1 and 2", a section title, or page numbers
def reference_markup(match, state, mode, pages):
    ids = [part.strip().lstrip("@") for part in match.group(2).split(";")]
    if not match.group(3) and all(ident in state.refs and ident not in state.targets for ident in ids):
        return citation_text(ids, state)
    targets = [state.targets.get(ident) for ident in ids]
    links = mode != "pptx"
    if match.group(3):
        return joined([page_piece(target, mode, pages) if target else rf"\[?{ident}\]" for target, ident in zip(targets, ids)])
    if all(targets) and len(targets) > 1 and len({target.kind for target in targets}) == 1 and all(target.number for target in targets):
        word = targets[0].label.replace(targets[0].number, "").strip()
        return (word + "s" if word[-1:].isalpha() else word) + " " + joined([piece(target, target.number, links) for target in targets])
    return joined([piece(target, target.label, links) if target else rf"\[?{ident}\]" for target, ident in zip(targets, ids)])


# text with each [@id] reference replaced, leaving code and maths alone
def resolve_text(text, state, mode, pages):
    return REFERENCE_TEXT.sub(lambda found: found.group(1) or reference_markup(found, state, mode, pages), latex_text(text))


# a document with every reference resolved in bodies, slots and items; mode is pdf, docx or pptx
def resolve_document(document, state, mode, pages=None):
    pages = pages or {}
    return Document(document.meta, tuple(
        replace(block, body=resolve_text(block.body, state, mode, pages),
                slots={key: resolve_text(text, state, mode, pages) for key, text in block.slots.items()},
                items=tuple(tuple(resolve_text(part, state, mode, pages) for part in item) for item in block.items))
        for block in document.blocks))


# the caption text of a figure or table target: "Figure 1. caption"
def caption_of(target):
    return f"{target.mark}. {target.text}" if target.text else f"{target.mark}."


# check findings for duplicate ids, unknown references and citations, unused or malformed refs and page references in slides, as (line, severity, message, fix)
def reference_findings(lines, end, meta, folders=()):
    state = new_numbering(None, meta)
    number_lines(lines[end:], state, first_line=end + 1, inject=False)
    state.refs, problem = load_refs(meta, folders)
    refs_line = next((number for number, text in enumerate(lines[:end], 1) if text.lower().startswith("refs")), 1)
    found = [(line, "error", f"id '{ident}' is already used on line {state.targets[ident].line}", "give each target its own id")
             for ident, line in state.duplicates]
    if problem:
        found.append((refs_line, "error", f"the refs file is unusable: {problem}", "fix the file or remove refs:"))
    found += [(refs_line, "error", f"id '{ident}' is both a target and a reference", "rename one of them") for ident in state.refs if ident in state.targets]
    text = "\n".join([""] * end + lines[end:])
    used = set()
    for match in REFERENCE_TEXT.finditer(text):
        if match.group(1):
            continue
        line = text.count("\n", 0, match.start()) + 1
        for ident in (part.strip().lstrip("@") for part in match.group(2).split(";")):
            used.add(ident)
            if ident not in state.targets and ident not in state.refs:
                close = get_close_matches(ident, [*state.targets, *state.refs], n=1)
                found.append((line, "error", f"unknown reference '{ident}'", f"did you mean '{close[0]}'?" if close else f"label the target with {{#{ident}}}"))
        if match.group(3):
            found.append((line, "info", "a page reference shows the target's number in a PowerPoint deck", "use it for PDF and Word"))
    found += [(refs_line, "info", f"reference '{key}' is never cited", "cite it or remove it from the refs file") for key in state.refs if key not in used]
    return found
