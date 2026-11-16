import re
from dataclasses import replace

from markitdoc.markup.inline import inline_runs

DROPCAP_RANGE = (2, 4)


# the lines a look's drop cap spans, 0 when it has none
def dropcap_lines(look):
    value = look.props.get("dropcap", (0,))[0] if look else 0
    return int(value) if str(value).isdigit() and DROPCAP_RANGE[0] <= int(value) <= DROPCAP_RANGE[1] else 0


# the runs of an inline token with the paragraph's trailing {attributes} removed
def trimmed_runs(inline, targets, block_line):
    runs = inline_runs(inline, targets)
    if block_line and runs:
        runs[-1] = replace(runs[-1], text=re.sub(r"\s*\{[^{}]*\}\s*$", "", runs[-1].text))
    return runs


# whether a top-level token other than a heading or paragraph ends the stretch where a paragraph is the first of its section
def interrupts_opening(token):
    return token.level == 0 and (token.type in ("fence", "hr", "math_block")
                                 or token.type.endswith("_open") and token.type not in ("paragraph_open", "heading_open"))
