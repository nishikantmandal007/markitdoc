import logging
import re
from dataclasses import replace

from markitdoc.models.catalogue import icon_layouts, layouts
from markitdoc.models.document import Block
from markitdoc.themes.themes import Theme
from markitdoc.visuals.icons import strip_icon

logger = logging.getLogger(__name__)

paragraph_break = "||"
leading_number = re.compile(r"^\s*(step\s+)?\d+\s*[.):-]\s*", re.IGNORECASE)


# splits a block slot into the text pieces used for fitting
def slot_pieces(block, slot):
    text = block.slots.get(slot, "")
    return paragraphs(text) if block.layout == "chapter" and slot == "body" else [text.replace(paragraph_break, "\n")]


# splits text into non-empty paragraphs
def paragraphs(text):
    return [part.strip() for part in text.split(paragraph_break) if part.strip()]


# fills layout aliases and defaults into a document block
def prepared(block: Block) -> Block:
    layout = layouts.get(block.layout)
    if not layout:
        return block
    slots = dict(block.slots)
    for slot in layout.boxes:
        if slot not in slots:
            alias = next((name for name in slots if name.startswith(f"{slot}_")), None)
            if alias:
                slots[slot] = slots.pop(alias)
    if len(slots.get("number", "")) > 3:
        digits = re.findall(r"\d+", slots["number"])
        slots["number"] = digits[0][:3] if digits else ""
    parts = len(layout.items[2]) if layout.items[2] else 0
    items = block.items
    if parts:
        items = tuple(item[:parts - 1] + (" — ".join(item[parts - 1:]),) if len(item) > parts else item + ("",) * (parts - len(item))
                      for item in items)
    if block.layout not in icon_layouts:
        items = tuple((strip_icon(item[0])[1],) + item[1:] if item else item for item in items)
    if block.layout == "process":
        items = tuple((icon_kept(item[0], lambda name: leading_number.sub("", name)),) + item[1:] for item in items)
    if block.layout == "chapter" and len(paragraphs(slots.get("body", ""))) > 2:
        parts = paragraphs(slots["body"])
        half = (len(parts) + 1) // 2
        slots["body"] = "\n\n".join(parts[:half]) + f" {paragraph_break} " + "\n\n".join(parts[half:])
    return replace(block, slots=slots, items=items)


# applies a text change while preserving a leading icon shortcode
def icon_kept(text, change):
    icon, rest = strip_icon(text)
    return (f":{icon}: " if icon else "") + change(rest)


# makes text safe for a markdown table cell
def cell(text):
    return text.replace("|", "/").replace("\n", " ")


# checks whether a block uses a dark layout variant
def is_dark(block: Block, theme: Theme) -> bool:
    layout = layouts.get(block.layout)
    if not layout or not layout.dark_variants:
        return False
    variant = block.slots.get("variant") or (theme.cover if block.layout == "cover" else layout.variants[0])
    return variant in layout.dark_variants


# switches adjacent dark blocks to a light variant for page contrast
def balanced(blocks, theme: Theme):
    result, previous_dark = [], False
    for block in blocks:
        if previous_dark and is_dark(block, theme) and block.layout != "cover":
            logger.info("Page %d (%s) switched to its light variant to keep dark pages apart", len(result) + 1, block.layout)
            block = replace(block, slots={**block.slots, "variant": "light"})
        previous_dark = is_dark(block, theme)
        result.append(block)
    return tuple(result)


# converts designed blocks into ordinary flowing markdown content
def as_flow(block: Block) -> Block:
    slots = block.slots
    if block.layout in ("process", "keypoints") and block.items:
        steps = "\n".join(f"{number}. **{strip_icon(item[0])[1]}** — {' — '.join(part for part in item[1:] if part)}"
                          for number, item in enumerate(block.items, 1))
        return Block("flow", {}, (), "\n\n".join(part for part in (f"## {slots.get('title', '')}", slots.get("lead", ""), steps,
                                                                   slots.get("takeaway", ""), block.body) if part.strip("# ")))
    if block.layout == "comparison" and slots.get("left") and slots.get("right") and block.items:
        rows = "\n".join(f"| {cell(item[0])} | {cell(' — '.join(part for part in item[1:] if part))} |" for item in block.items)
        table = f"| {cell(slots['left'])} | {cell(slots['right'])} |\n|---|---|\n{rows}"
        return Block("flow", {}, (), "\n\n".join(part for part in (f"## {slots.get('title', '')}", slots.get("lead", ""), table,
                                                                   slots.get("takeaway", ""), block.body) if part.strip("# ")))
    heading = "# " if block.layout == "cover" else "## "
    quote = f"> {slots['quote']}" + (f" — {slots['quote_by']}" if slots.get("quote_by") else "") if slots.get("quote") else ""
    columns = f"**{slots['left']}** — **{slots['right']}**" if slots.get("left") and slots.get("right") else ""
    parts = [quote if block.layout == "closing" else "", slots.get("kicker", ""), heading + " ".join(filter(None, (slots.get("number", ""), slots.get("title", "")))) if slots.get("title") else "",
             slots.get("subtitle", ""), slots.get("lead", ""), *paragraphs(slots.get("body", "")), columns,
             "\n".join(f"- {icon_kept(item[0], lambda name: f'**{name}**')} — {' — '.join(part for part in item[1:] if part)}" for item in block.items),
             quote if block.layout != "closing" else "", slots.get("context", ""),
             slots.get("takeaway", ""), block.body]
    return Block("flow", {}, (), "\n\n".join(part for part in parts if part))
