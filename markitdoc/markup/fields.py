import re
from dataclasses import replace

from markitdoc.models.document import Document
from markitdoc.utils.helpers import long_date

FIELD_TEXT = re.compile(r"(```.*?```|~~~.*?~~~|`[^`\n]*`|\$\$.*?\$\$|\$[^\s$][^$\n]*\$)|\{([A-Za-z_][\w-]*)\}", re.S)


# the field values of a document: the style and front matter fields, and the front matter date in long form
def field_values(sheet, meta):
    return {**sheet.fields, **({"date": long_date(meta["date"])} if long_date(meta.get("date", "")) else {})}


# text with each known {name} replaced, leaving code spans, code blocks and maths alone
def replace_fields(text, values):
    return FIELD_TEXT.sub(lambda found: found.group(1) or values.get(found.group(2), found.group(0)), text)


# a document with the fields replaced in every block's body, slots and items
def with_fields(document, values):
    return Document(document.meta, tuple(
        replace(block, body=replace_fields(block.body, values), slots={key: replace_fields(text, values) for key, text in block.slots.items()},
                items=tuple(tuple(replace_fields(part, values) for part in item) for item in block.items))
        for block in document.blocks))
