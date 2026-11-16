import logging
import re
from dataclasses import dataclass

from markitdoc.markup.elements import (
    chart_data,
    closing_index,
    column_alignments,
    element_settings,
    only_display_maths,
    table_styles,
    without_display_maths,
)
from markitdoc.markup.inline import anchor, parser, plain_text
from markitdoc.pptx.deck import Item
from markitdoc.visuals.diagrams import chain_steps, diagram_title

logger = logging.getLogger(__name__)

footnote_mark = re.compile(r"\[\^([^\]]+)\]")
checkbox = re.compile(r"^\[( |x|X)\]\s+")
settings_tail = re.compile(r"\s*\{[^{}]*\}\s*$")
page_break_marker = "+++"


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


break_piece = Piece("break")


class FlowReader:
    def __init__(self, deck):
        self.deck, self.sections, self.lists, self.caption, self.labels = deck, [], [], "", {}

    @property
    def parts(self):
        if not self.sections:
            self.sections.append(Section("", 2, []))
        return self.sections[-1].parts

    def number_of(self, match):
        return "^" + str(self.labels.setdefault(match.group(1), len(self.labels) + 1)) + "^"

    def source_of(self, inline):
        source = footnote_mark.sub(self.number_of, inline.content)
        return checkbox.sub(lambda match: "☐ " if match.group(1) == " " else "☑ ", source)

    def read(self, tokens):
        index = 0
        while index < len(tokens):
            index = self.step(tokens, index)

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
            self.parts.append(break_piece)
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

    def heading(self, tokens, index):
        level, source = int(tokens[index].tag[1]), anchor.sub("", tokens[index + 1].content)
        if level <= 2:
            self.sections.append(Section(plain_text(source), level, []))
        else:
            self.parts.append(Item(source, "subheading"))
        return index + 3

    def container(self, tokens, index):
        token = tokens[index]
        end = closing_index(tokens, index, token.type, token.type[:-5] + "_close")
        title = re.search(r'title="([^"]*)"', token.info)
        if title:
            self.parts.append(Item(title.group(1), "subheading"))
        self.read(tokens[index + 1:end])
        return end + 1

    def quote(self, tokens, index):
        end = closing_index(tokens, index, "blockquote_open", "blockquote_close")
        self.parts.extend(Item(self.source_of(token), "quote") for token in tokens[index:end] if token.type == "inline")
        return end + 1

    def paragraph(self, tokens, index):
        inline, equations = without_display_maths(tokens[index + 1])
        picture = next((child for child in inline.children or [] if child.type == "image"), None)
        source = settings_tail.sub("", self.source_of(tokens[index + 1] if not equations else inline)).strip()
        if picture is not None:
            self.parts.append(Piece("figure", picture.content or str(picture.attrs.get("alt", ""))))
        elif source == page_break_marker:
            self.parts.append(break_piece)
        elif source.startswith("Table:") and not self.lists:
            self.caption = source[6:].strip()
        elif source and not (equations and only_display_maths(tokens[index + 1])):
            self.parts.append(self.listed_item(source))
        self.parts.extend(Piece("equation", equation.strip()) for equation in equations)
        return index + 3

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
        styled = settings.get("class") in table_styles
        style = settings["class"] if styled else self.deck.table_style
        self.parts.append(Piece("table", Table(tuple(rows), tuple(column_alignments(tokens[index:end])), style), self.caption))
        self.caption = ""
        return end + 1 + (3 if styled else 0)

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


def read_sections(deck, markdown):
    reader = FlowReader(deck)
    reader.read(parser.parse(markdown))
    return [section for section in reader.sections if section.title or section.parts]
