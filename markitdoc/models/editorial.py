import re
from dataclasses import replace
from pathlib import Path

import yaml

from markitdoc.markup.inline import literal
from markitdoc.models.document import Block
from markitdoc.models.model_constants import FLOW_LAYOUT, PAGE_SWITCH, REFERENCE_TEXT

CITATION_STYLES = ("numeric", "author-year")
LIST_KINDS = {"figures": ("figure", "List of figures"), "tables": ("table", "List of tables")}
REFERENCES_BLOCK = re.compile(r"^:::+[ \t]*references[ \t]*\n(?::::*[ \t]*(?:\n|$))?", re.M)
LIST_BLOCK = re.compile(r"^:::+[ \t]*list-of-(figures|tables)[ \t]*\n(?::::*[ \t]*(?:\n|$))?", re.M)
REFERENCES_TITLE = "References"
UNNUMBERED_MARK = " {.unnumbered}"


# the refs file entries as {key: entry} and the problem found, empty when none; the file is read from the first style folder
def load_refs(meta, folders):
    name = str(meta.get("refs") or "").strip()
    if not name:
        return {}, ""
    try:
        data = yaml.safe_load((Path(folders[0]) if folders else Path()).joinpath(name).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        return {}, f"cannot read {name}: {str(error).splitlines()[0][:80]}"
    if not isinstance(data, dict) or not all(isinstance(entry, dict) for entry in data.values()):
        return {}, f"{name} must map each key to an entry with author, title, year"
    return {str(key): entry for key, entry in data.items()}, ""


# the citation style a document asks for with style: numeric or author-year, numeric when it asks for none
def citation_style(meta):
    return meta["style"] if meta.get("style") in CITATION_STYLES else CITATION_STYLES[0]


# the authors of an entry as a list of names
def authors_of(entry):
    found = entry.get("author") or []
    return [str(name).strip() for name in (found if isinstance(found, list) else [found]) if str(name).strip()]


# the family name in "Family, Given" or "Given de Family"
def surname(name):
    if "," in name:
        return name.split(",")[0].strip()
    words = name.split()
    start = len(words) - 1
    while start > 0 and words[start - 1].islower():
        start -= 1
    return " ".join(words[start:])


# "a, b and c" from texts
def joined(texts):
    return texts[0] if len(texts) == 1 else ", ".join(texts[:-1]) + " and " + texts[-1]


# "de Wit", "de Wit and Jansen" or "de Wit et al." for an entry
def short_authors(entry):
    names = [surname(name) for name in authors_of(entry)]
    return "" if not names else names[0] + " et al." if len(names) > 2 else " and ".join(names)


# the id of a reference list entry, which a citation links to
def reference_id(key):
    return f"ref-{key}"


# the text a citation of these keys stands for: "[1, 2]" or "(de Wit and Jansen, 2021; Brook, 2020)"
def citation_text(keys, state, links=True):
    def linked(key, text):
        return f"[{literal(text)}](#{reference_id(key)})" if links else literal(text)

    if state.style == "numeric":
        return "\\[" + ", ".join(linked(key, str(state.cited.index(key) + 1)) for key in keys) + "\\]"
    return "(" + "; ".join(linked(key, ", ".join(part for part in (short_authors(state.refs[key]), str(state.refs[key].get("year", ""))) if part))
                           for key in keys) + ")"


# one reference list entry as markdown: authors (year). Title. Journal. link
def entry_text(entry):
    names = joined(authors_of(entry)) if authors_of(entry) else ""
    year = str(entry.get("year", "")).strip()
    source = str(entry.get("journal") or entry.get("publisher") or "").strip()
    link = str(entry.get("doi") or "").strip()
    link = f"[doi:{literal(link)}](https://doi.org/{link})" if link else (f"[{literal(str(entry['url']))}]({entry['url']})" if entry.get("url") else "")
    first = " ".join(part for part in (literal(names), f"({literal(year)})" if year else "") if part)
    title = literal(str(entry.get("title", "")).strip())
    return " ".join(part for part in (first + "." if first else "", title + "." if title else "", f"*{literal(source)}*." if source else "", link) if part)


# the cited entries as one markdown paragraph each, numbered in citation order or sorted by author and year
def references_markup(state):
    keys = state.cited if state.style == "numeric" else sorted(
        state.cited, key=lambda key: (short_authors(state.refs[key]).lower(), str(state.refs[key].get("year", ""))))
    items = [(f"\\[{number}\\] " if state.style == "numeric" else "") + entry_text(state.refs[key]) + f" {{#{reference_id(key)} dropcap=0}}" for number, key in enumerate(keys, 1)]
    return f"## {REFERENCES_TITLE}{UNNUMBERED_MARK}\n\n" + "\n\n".join(items) if items else ""


# the keys of a document's citations in order of first use: ids that name a reference and no target
def cited_keys(texts, state):
    found = []
    for text in texts:
        for match in REFERENCE_TEXT.finditer(text):
            if not match.group(1):
                found += [key for key in (part.strip().lstrip("@") for part in match.group(2).split(";"))
                          if key in state.refs and key not in state.targets and key not in found]
    return found


# a list of figures or tables as markdown: a title and one line per target, caption and page separated by a tab
def list_markup(kind, state):
    name, title = LIST_KINDS[kind]
    targets = [target for target in state.targets.values() if target.kind == name]
    lines = [f"[{literal(f'{target.mark}. {target.text}' if target.text else target.mark + '.')}](#{target.id})\t[@{target.id} page]" for target in targets]
    return f"## {title}{UNNUMBERED_MARK}\n\n" + "\n\n".join(lines) if lines else ""


# the list kinds a front matter lists: value asks for, such as "[figures, tables]"
def front_lists(meta):
    return [word for word in re.findall(r"[a-z]+", str(meta.get("lists", ""))) if word in LIST_KINDS]


# blocks with lists and the references section written out: placed where their ::: block is, else after the contents or at the end
def with_editorial(blocks, state, meta):
    placed = set()

    def fill(body):
        def listed(found):
            placed.add(found.group(1))
            return list_markup(found.group(1), state) + "\n\n"

        def referenced(_):
            placed.add("references")
            return references_markup(state) + "\n\n"

        return REFERENCES_BLOCK.sub(referenced, LIST_BLOCK.sub(listed, body))

    blocks = [replace(block, body=fill(block.body)) if block.layout == FLOW_LAYOUT else block for block in blocks]
    extra = "\n\n".join(list_markup(kind, state) for kind in front_lists(meta) if kind not in placed)
    first = next((index for index, block in enumerate(blocks) if block.layout == FLOW_LAYOUT), None)
    if extra.strip() and first is not None:
        head, _, rest = blocks[first].body.partition("\n")
        lead = head + "\n\n" if PAGE_SWITCH.match(head.strip()) else ""
        blocks[first] = replace(blocks[first], body=lead + extra + "\n\n" + (rest if lead else blocks[first].body))
    elif extra.strip():
        blocks.append(Block(FLOW_LAYOUT, {}, (), extra))
    if "references" not in placed and state.cited:
        if blocks and blocks[-1].layout == FLOW_LAYOUT:
            blocks[-1] = replace(blocks[-1], body=blocks[-1].body + "\n\n" + references_markup(state))
        else:
            blocks.append(Block(FLOW_LAYOUT, {}, (), references_markup(state)))
    return blocks, bool(placed or front_lists(meta))
