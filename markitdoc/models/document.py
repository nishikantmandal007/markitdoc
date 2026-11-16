import logging
from dataclasses import dataclass, field

from markitdoc.models.attributes import parse_attributes
from markitdoc.models.catalogue import LAYOUTS
from markitdoc.models.front_matter import front_matter, language_version
from markitdoc.models.model_constants import (
    BLOCK_START,
    BULLET_SEPARATORS,
    DIV_CLOSE,
    DIV_OPEN,
    FLOW_CONTAINERS,
    FLOW_LAYOUT,
    LEAF_BLOCKS,
    SLOT_LINE,
    STRONG_SEPARATORS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Block:
    layout: str
    slots: dict = field(default_factory=dict)
    items: tuple = ()
    body: str = ""


@dataclass(frozen=True)
class Document:
    meta: dict
    blocks: tuple

    # does any block use a designed layout?
    @property
    def is_laid_out(self):
        return any(block.layout != FLOW_LAYOUT for block in self.blocks)


# markdown to a Document: front matter plus designed and flow blocks
def parse_document(markdown):
    meta, body = front_matter(markdown)
    chunks = split_blocks(body, language_version(meta) == 2)
    blocks = tuple(parse_block(chunk) for chunk in chunks) or (Block(layout=FLOW_LAYOUT, body=body.strip()),)
    logger.info("Parsed document: %d blocks (%s), front matter %s", len(blocks), ", ".join(block.layout for block in blocks),
                sorted(meta))
    return Document(meta=meta, blocks=blocks)


# ::: {.layout key=value} opening line to 'layout: name' and slot lines
def div_header(match):
    attributes = {key: value for key, value in parse_attributes(match.group(2)).values.items() if value is not True}
    return [f"layout: {match.group(1).lower()}", *(f"{key}: {value}" for key, value in attributes.items())]


# body lines into chunks: one per fenced designed block, free markdown between them as flow; in language v2 any name that is not a designed layout is a flow container
def split_blocks(body, v2=False):
    chunks, current, loose, in_fence, in_div, nested = [], None, [], False, False, 0
    fences = []

    def flush_loose():
        if "".join(loose).strip():
            chunks.append([f"layout: {FLOW_LAYOUT}", *loose])
        loose.clear()

    # gives outer fences more colons than the ones nested in them, as the container parser needs
    def lengthen_fences():
        deepest = max(depth for _, _, depth in fences)
        if deepest:
            for target, position, depth in fences:
                target[position] = ":" * (3 + deepest - depth) + target[position].strip().lstrip(":")
        fences.clear()

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        container = DIV_OPEN.match(stripped) if not in_fence else None
        if container and v2 and container.group(1).lower() in LEAF_BLOCKS:
            (current if current is not None else loose).append(line)
        elif container and not DIV_CLOSE.match(stripped) and (nested or container.group(1).lower() in FLOW_CONTAINERS
                                                     or (v2 and container.group(1).lower() not in LAYOUTS)):
            target = current if current is not None else loose
            target.append(line)
            fences.append((target, len(target) - 1, nested))
            nested += 1
        elif nested and not in_fence and DIV_CLOSE.match(stripped):
            nested -= 1
            target = current if current is not None else loose
            target.append(line)
            fences.append((target, len(target) - 1, nested))
            if not nested:
                lengthen_fences()
        elif not in_fence and (match := DIV_OPEN.match(stripped)) and not DIV_CLOSE.match(stripped):
            flush_loose()
            current, in_div = div_header(match), True
            chunks.append(current)
        elif not in_fence and in_div and DIV_CLOSE.match(stripped):
            current, in_div = None, False
        elif not in_fence and not in_div and BLOCK_START.match(stripped):
            flush_loose()
            current = []
            chunks.append(current)
        elif current is not None:
            current.append(line)
        else:
            loose.append(line)
    if chunks:
        flush_loose()
    return chunks


# 'value — label — note' item line into its parts
def item_parts(line):
    bulleted = line.startswith(("- ", "* "))
    text = line[2:].strip() if bulleted else line
    for separator in STRONG_SEPARATORS + (BULLET_SEPARATORS if bulleted else ()):
        if separator in text:
            return tuple(part.strip() for part in text.split(separator))
    return (text,) if bulleted else None


# one chunk into a Block with its slots, items and remaining body
def parse_block(lines):
    slots, items, body, in_fence, last_slot = {}, [], [], False, None
    for line in lines:
        stripped = line.strip()
        designed = slots.get("layout", FLOW_LAYOUT) != FLOW_LAYOUT
        if stripped.startswith("```"):
            in_fence = not in_fence
            body.append(line)
        elif in_fence:
            body.append(line)
        elif (match := SLOT_LINE.match(stripped)) and not body and (designed or not slots):
            slots[match.group(1)] = match.group(2).strip()
            last_slot = match.group(1)
        elif designed and stripped and (parts := item_parts(stripped)):
            items.append(parts)
            last_slot = None
        elif designed and stripped and last_slot and not body:
            slots[last_slot] = f"{slots[last_slot]} {stripped}"
        elif stripped or body:
            body.append(line)
    layout = slots.pop("layout", FLOW_LAYOUT)
    return Block(layout=layout, slots=slots, items=tuple(items), body="\n".join(body).strip())
