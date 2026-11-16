from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from markitdoc.docx.writer import BULLET_MARKS, LIST_FORMATS, write_runs


# creates or reuses the numbering definition for a list style
def abstract_list(writer, ordered, scheme):
    key = (ordered, scheme)
    if key in writer.lists:
        return writer.lists[key]
    numbering = writer.document.part.numbering_part.element
    known = [int(item.get(qn("w:abstractNumId"))) for item in numbering.findall(qn("w:abstractNum"))]
    abstract_id = max(known, default=0) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "hybridMultilevel")
    abstract.append(multi)
    for level in range(4):
        abstract.append(list_level(writer, level, ordered, scheme))
    first_num = numbering.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        numbering.append(abstract)
    writer.lists[key] = abstract_id
    return abstract_id


# builds the numbering settings for one list level
def list_level(writer, level, ordered, scheme):
    item = OxmlElement("w:lvl")
    item.set(qn("w:ilvl"), str(level))
    values = [("w:start", "1"),
              ("w:numFmt", LIST_FORMATS[scheme] if ordered else "bullet"),
              ("w:lvlText", (".".join(f"%{depth + 1}" for depth in range(level + 1)) + "." if scheme == "legal" else f"%{level + 1}.")
               if ordered else BULLET_MARKS[level % 3]),
              ("w:lvlJc", "left")]
    for name, value in values:
        element = OxmlElement(name)
        element.set(qn("w:val"), value)
        item.append(element)
    paragraph = OxmlElement("w:pPr")
    indent = OxmlElement("w:ind")
    hang = 0.75 if scheme == "legal" and ordered else 0.55
    indent.set(qn("w:left"), str(int((0.55 + level * 0.6 + hang - 0.55) * 567 + 0.55 * 567)))
    indent.set(qn("w:hanging"), str(int(hang * 567)))
    paragraph.append(indent)
    item.append(paragraph)
    run = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), writer.hex("mood"))
    run.append(color)
    if ordered:
        run.append(OxmlElement("w:b"))
    item.append(run)
    return item


# starts a numbered or bulleted list with its requested starting number
def new_list(writer, ordered, scheme, start):
    numbering = writer.document.part.numbering_part.element
    number = numbering.add_num(abstract_list(writer, ordered, scheme))
    if start != 1:
        override = number.add_lvlOverride(ilvl=0)
        override.add_startOverride(start)
    return {"id": number.numId, "depth": None, "fresh": False}


# draws a numbered or bulleted list item at its nesting level
def add_list_item(writer, stack, runs):
    current = stack[-1]
    paragraph = writer.body.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(3)
    if current["fresh"]:
        properties = paragraph._p.get_or_add_pPr()
        numbering = OxmlElement("w:numPr")
        level, number = OxmlElement("w:ilvl"), OxmlElement("w:numId")
        level.set(qn("w:val"), str(min(len(stack) - 1, 3)))
        number.set(qn("w:val"), str(current["id"]))
        numbering.append(level)
        numbering.append(number)
        properties.append(numbering)
        current["fresh"] = False
    else:
        paragraph.paragraph_format.left_indent = Cm(0.55 + (len(stack) - 1) * 0.6 + 0.55)
    write_runs(writer, paragraph, runs)
