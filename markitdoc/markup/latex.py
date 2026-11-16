import re

from markitdoc.models.model_constants import SKIPPED_TEXT

LATEX_TEXT = re.compile(rf"({SKIPPED_TEXT})|\\(textbf|textit|emph|underline|texttt|footnote)\{{([^{{}}]*)\}}|\\(newpage|centering|LaTeX)\b|\\([%&$])", re.S)
LATEX_WRAPS = {"textbf": "**{}**", "textit": "*{}*", "emph": "*{}*", "underline": "[{}]{{.underline}}", "texttt": "`{}`", "footnote": "^[{}]"}
LATEX_WORDS = {"newpage": "\n\n+++\n\n", "centering": "", "LaTeX": "LaTeX"}
LATEX_ADVICE = {"textbf": "use **text**", "textit": "use *text*", "emph": "use *text*", "underline": "use [text]{.underline}",
                "texttt": "use `text`", "footnote": "use ^[text] or [^1] with a note below", "newpage": "put +++ on its own line",
                "centering": "put {align=center} on the line below the paragraph", "LaTeX": "write LaTeX as plain text",
                "%": "write % without the backslash", "&": "write & without the backslash", "$": "write \\$ or put the amount in a code span"}


# text with each common LaTeX text command replaced by its markdown form, leaving code and maths alone
def latex_text(text):
    if "\\" not in text:
        return text

    def replaced(found):
        if found.group(1):
            return found.group(1)
        if found.group(2):
            return LATEX_WRAPS[found.group(2)].format(found.group(3))
        return LATEX_WORDS[found.group(4)] if found.group(4) else ("\\$" if found.group(5) == "$" else found.group(5))

    return LATEX_TEXT.sub(replaced, text)


# check findings for LaTeX text commands, as (line, severity, message, fix)
def latex_findings(lines, end):
    text = "\n".join([""] * end + lines[end:])
    found = []
    for match in LATEX_TEXT.finditer(text):
        if match.group(1):
            continue
        name = match.group(2) or match.group(4) or match.group(5)
        found.append((text.count("\n", 0, match.start()) + 1, "warning", f"LaTeX command \\{name} is rendered, but markdown is the supported form",
                      LATEX_ADVICE[name]))
    return found
