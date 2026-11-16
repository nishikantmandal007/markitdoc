import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path

from markitdoc.markup.elements import (
    TABLE_STYLES,
    chart_data,
    closing_index,
    column_alignments,
    element_settings,
    only_display_maths,
    top_level_blocks,
    without_display_maths,
    written_image,
)
from markitdoc.markup.inline import ANCHOR, UNNUMBERED, parser, plain_text
from markitdoc.models.attributes import parse_attributes
from markitdoc.models.references import caption_of
from markitdoc.options import options_in_use
from markitdoc.pptx.deck import Item
from markitdoc.themes.theme_constants import STYLE_PROPERTIES
from markitdoc.visuals.diagrams import chain_steps, diagram_title

logger = logging.getLogger(__name__)

FOOTNOTE_MARK = re.compile(r"\[\^([^\]]+)\]")
CHECKBOX = re.compile(r"^\[( |x|X)\]\s+")
SETTINGS_TAIL = re.compile(r"\s*\{[^{}]*\}\s*$")
PAGE_BREAK_MARKER = "+++"


@dataclass(frozen=True)
class Piece:
    kind: str
    data: object = None
    caption: str = ""
    after: tuple = ()


@dataclass(frozen=True)
class Table:
    rows: tuple
    aligns: tuple
    style: str


@dataclass
class Section:
    title: str
    level: int
    parts: list


BREAK_PIECE = Piece("break")


class FlowReader:
    # sets up the rendering context and its document settings
    def __init__(self, deck):
        self.deck, self.sections, self.lists, self.caption, self.labels, self.context = deck, [], [], "", {}, None

    # returns the current section parts, creating a default section when needed
    @property
    def parts(self):
        if not self.sections:
            self.sections.append(Section("", 2, []))
        return self.sections[-1].parts

    # replaces a footnote label with its numbered marker
    def number_of(self, match):
        return "^" + str(self.labels.setdefault(match.group(1), len(self.labels) + 1)) + "^"

    # converts footnote and checkbox syntax to visible text
    def source_of(self, inline):
        source = FOOTNOTE_MARK.sub(self.number_of, inline.content)
        return CHECKBOX.sub(lambda match: "☐ " if match.group(1) == " " else "☑ ", source)

    # an item with the look the stylesheet gives its element, unchanged for version 1 decks
    def styled(self, item, selector, attributes=None):
        if not self.deck.styles:
            return item
        found = attributes or parse_attributes("")
        return replace(item, look=self.deck.look(selector, found.classes, found.values, self.context))

    # the parts the tokens read as, kept apart from the current section
    def parts_of(self, tokens):
        saved, self.sections = self.sections, [Section("", 2, [])]
        self.read(tokens)
        found, self.sections = [part for section in self.sections for part in section.parts], saved
        return found

    # reads markdown tokens into slide content parts
    def read(self, tokens):
        index = 0
        while index < len(tokens):
            index = self.step(tokens, index)

    # dispatches the current token and returns the next unread position
    def step(self, tokens, index):
        token = tokens[index]
        kind = token.type
        if kind == "heading_open":
            return self.heading(tokens, index)
        if kind == "paragraph_open":
            return self.paragraph(tokens, index)
        if kind in ("bullet_list_open", "ordered_list_open"):
            self.lists.append({"ordered": kind == "ordered_list_open", "number": int(token.attrs.get("start", 1) or 1), "fresh": False})
        elif kind in ("bullet_list_close", "ordered_list_close"):
            self.lists.pop()
        elif kind == "list_item_open":
            self.lists[-1]["fresh"] = True
        elif kind == "table_open":
            return self.table(tokens, index)
        elif kind == "fence":
            self.fence(token)
        elif kind == "math_block":
            self.parts.append(Piece("equation", token.content.strip()))
        elif kind == "hr":
            self.parts.append(BREAK_PIECE)
        elif kind == "blockquote_open":
            return self.quote(tokens, index)
        elif kind == "dt_open":
            self.parts.append(Item(self.source_of(tokens[index + 1]), "subheading"))
            return index + 3
        elif kind == "footnote_block_open":
            end = closing_index(tokens, index, kind, "footnote_block_close")
            self.deck.footnotes += [(token.meta.get("label", ""), self.source_of(tokens[position + 1]))
                                    for position, token in enumerate(tokens[index:end], index) if token.type == "footnote_open"]
            return end + 1
        elif kind.startswith("container_") and kind.endswith("_open"):
            return self.container(tokens, index)
        return index + 1

    # starts a slide section or adds a subheading from a markdown heading
    def heading(self, tokens, index):
        level, source = int(tokens[index].tag[1]), ANCHOR.sub("", UNNUMBERED.sub("", tokens[index + 1].content))
        if level <= 2:
            self.sections.append(Section(plain_text(source), level, []))
        else:
            self.parts.append(self.styled(Item(source, "subheading"), f"h{min(level, 4)}"))
        return index + 3

    # reads a markdown container and adds its contents to the current section; a styled box and columns become pieces of their own
    def container(self, tokens, index):
        token = tokens[index]
        end = closing_index(tokens, index, token.type, token.type[:-5] + "_close")
        title = re.search(r'title="([^"]*)"', token.info)
        if title:
            self.parts.append(Item(title.group(1), "subheading"))
        inner, name, found = tokens[index + 1:end], token.type[len("container_"):-len("_open")], parse_attributes(token.info)
        if self.deck.styles and name == "columns":
            blocks = top_level_blocks(inner, True)
            half = (len(blocks) + 1) // 2
            columns = [self.parts_of([item for block in part for item in block]) for part in (blocks[:half], blocks[half:])]
            weights, gap = self.deck.styles.columns(found.values)
            self.parts.append(Piece("columns", (weights, gap, *[[part for part in column if isinstance(part, Item)] for column in columns])))
            self.parts.extend(part for column in columns for part in column if not isinstance(part, Item))
            return end + 1
        look = self.deck.look("box", found.classes, found.values, self.context) if self.deck.styles and name == "box" else None
        if look and look.boxed():
            before, self.context = self.context, {key: item for key, item in look.props.items() if key in STYLE_PROPERTIES}
            parts, self.context = self.parts_of(inner), before
            self.parts.append(Piece("box", (look, [part for part in parts if isinstance(part, Item)]), title.group(1) if title else ""))
            self.parts.extend(part for part in parts if not isinstance(part, Item))
            return end + 1
        self.read(inner)
        return end + 1

    # adds blockquote text to the current slide section
    def quote(self, tokens, index):
        end = closing_index(tokens, index, "blockquote_open", "blockquote_close")
        self.parts.extend(self.styled(Item(self.source_of(token), "quote"), "quote") for token in tokens[index:end] if token.type == "inline")
        return end + 1

    # turns a markdown paragraph into slide content
    def paragraph(self, tokens, index):
        inline, equations = without_display_maths(tokens[index + 1])
        picture = next((child for child in inline.children or [] if child.type == "image"), None)
        raw = self.source_of(tokens[index + 1] if not equations else inline)
        source, tail = SETTINGS_TAIL.sub("", raw).strip(), SETTINGS_TAIL.search(raw)
        attributes = parse_attributes(tail.group().strip()) if tail and self.deck.styles else None
        written = written_image(tokens[index + 1].content.strip()) if picture is not None and self.deck.styles else None
        if written:
            self.parts.append(self.file_image(written))
        elif picture is not None:
            self.parts.append(Piece("figure", picture.content or str(picture.attrs.get("alt", ""))))
        elif source == PAGE_BREAK_MARKER:
            self.parts.append(BREAK_PIECE)
        elif source.startswith("Table:") and not self.lists:
            self.caption = source[6:].strip()
        elif source and not (equations and only_display_maths(tokens[index + 1])):
            self.parts.append(self.styled(self.listed_item(source), "list" if self.lists else "paragraph", attributes))
        self.parts.extend(Piece("equation", equation.strip()) for equation in equations)
        return index + 3

    # a piece for an image written with a file path: its path, alt text, width, side and caption, numbered like Word and PDF captions
    def file_image(self, found):
        attributes = parse_attributes(found.group(3) or "")
        folders = options_in_use().style_folders
        target = self.deck.numbers.get(attributes.id)
        caption = caption_of(target) if target else str(attributes.values.get("caption", ""))
        look = self.deck.look("figure", attributes.classes, attributes.values)
        data = (str((Path(folders[0]) if folders else Path()) / found.group(2)), found.group(1) or found.group(2), look.width,
                str(attributes.values.get("side", "")).lower(), caption)
        return Piece("image", data)

    # assigns a list item its bullet or numbering details
    def listed_item(self, source):
        if not self.lists:
            return Item(source)
        current = self.lists[-1]
        if not current["fresh"]:
            return Item(source, "paragraph", len(self.lists))
        current["fresh"] = False
        item = Item(source, "number" if current["ordered"] else "bullet", len(self.lists) - 1, current["number"])
        current["number"] += 1
        return item

    # reads a markdown table into slide table data
    def table(self, tokens, index):
        end = closing_index(tokens, index, "table_open", "table_close")
        rows, row = [], None
        for token in tokens[index:end]:
            if token.type == "tr_open":
                row = []
            elif token.type == "inline" and row is not None:
                row.append(token.content)
            elif token.type == "tr_close":
                rows.append(tuple(row))
                row = None
        settings = element_settings(tokens, end + 1)
        last = rows[-1] if len(rows) > 2 else ()
        if last and re.fullmatch(r"\{[^{}]*\}", last[0].strip()) and not any(cell.strip() for cell in last[1:]):
            settings, rows = {"class": last[0].strip("{} .").split()[0] if last[0].strip("{} .") else ""}, rows[:-1]
        styled = settings.get("class") in TABLE_STYLES
        style = settings["class"] if styled else self.deck.table_style
        self.parts.append(Piece("table", Table(tuple(rows), tuple(column_alignments(tokens[index:end])), style), self.caption))
        self.caption = ""
        return end + 1 + (3 if styled else 0)

    # turns a code fence into a chart, diagram, image, or code block
    def fence(self, token):
        language = token.info.split("{")[0].strip()
        content = token.content
        if language == "chart":
            data = chart_data(content)
            if data:
                self.parts.append(Piece("chart", data))
            else:
                logger.warning("Chart skipped: invalid JSON, unknown type, no values, or a value count that differs from the labels")
        elif language == "mermaid":
            lines = content.strip().splitlines()
            titled = any(line.strip().startswith(("title ", "pie title ")) for line in lines)
            source = "\n".join("pie" if line.strip().startswith("pie title ") else line for line in lines
                               if not line.strip().startswith("title "))
            steps = chain_steps(source)
            if len(steps) >= 4:
                self.parts.append(Piece("steps", tuple(steps), diagram_title(content) if titled else ""))
            else:
                self.parts.append(Piece("diagram", source, diagram_title(content) if titled else ""))
        elif language.split()[:1] == ["infographic"]:
            self.parts.append(Piece("infographic", f"{language}\n{content}" if " " in language else content))
        else:
            self.parts.append(Piece("code", content.rstrip("\n"), language))


# reads markdown into titled slide sections
def read_sections(deck, markdown):
    reader = FlowReader(deck)
    reader.read(parser.parse(markdown))
    return [section for section in reader.sections if section.title or section.parts]
