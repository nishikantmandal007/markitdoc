import re

SUPPORT_FORMATS = ("pdf", "docx", "pptx")
SUPPORT_LEVELS = ("full", "approximate", "ignored")
IMAGE_FILE = r"!\[[^\]]*\]\([^)\s:]+\.(?:png|jpe?g|gif|webp|bmp)\)"
FENCE_LINE = re.compile(r"^\s*(```|~~~)")

# feature -> (what it is, pdf, docx, pptx, regex that finds it in a document, what differs when it is not full)
SUPPORT = {
    "text styles": ("text styles, set rules and named styles", "full", "full", "approximate", r"^\s*(set|styles|text)\s*:",
                    "slides apply font, colour, weight, italic, caps, tracking, align and size from rules and styles, but not the base size under text:"),
    "boxes": ("boxes with borders, fill and padding", "full", "full", "approximate", r"^:::+\s*\{?\s*\.?box\b",
              "a box is one rounded rectangle with the widest border edge, on a slide of its own"),
    "columns": ("columns", "full", "full", "approximate", r"^:::+\s*\{?\s*\.?columns\b",
                "two text frames side by side, text only, on a slide of their own"),
    "file images": ("images written with a file path", "full", "full", "approximate", IMAGE_FILE,
                    "one picture per slide; text beside it goes on the other side"),
    "page masters": ("paper sizes and page masters", "full", "full", "ignored", r"^\s*(page|pages)\s*:|^\+\+\+\s*\{",
                     "slides are always 16:9 with their own layout"),
    "headers and footers": ("headers, footers and page fields", "full", "full", "ignored", r"^\s*(header|footer)\s*:",
                            "slides carry their own footer and slide number"),
    "drop caps": ("drop caps", "full", "full", "ignored", r"dropcap", "slides never use drop caps"),
    "section numbering": ("numbered headings", "full", "full", "ignored", r"^\s*numbering\s*:",
                          "slide titles are not numbered, a reference to a section shows its number"),
    "page references": ("page references [@id page]", "full", "approximate", "approximate", r"\[@[\w-]+(?:\s*;\s*@[\w-]+)*\s+page\]",
                        "Word fills the page number when the file opens; a slide shows the target's number"),
    "lists of figures and tables": ("lists of figures and tables", "full", "full", "ignored", r"^\s*lists\s*:|^:::+\s*list-of",
                                    "slides do not print the lists"),
    "reference list": ("the generated References section", "full", "full", "ignored", r"^:::+\s*references\b",
                       "citations show as text on slides but no References slide is added"),
    "language tag": ("lang", "full", "full", "ignored", r"^\s*lang\s*:|\blang=", "slides carry no language tag"),
}


# the status of a feature for a format: full, approximate or ignored
def status_of(feature, output_format):
    return SUPPORT[feature][1 + SUPPORT_FORMATS.index(output_format)]


# the features a format does not fully support, as {feature: (status, what differs)}
def limits_of(output_format):
    return {feature: (status_of(feature, output_format), row[5]) for feature, row in SUPPORT.items() if status_of(feature, output_format) != "full"}


# info findings as (line, severity, message, fix), one per feature the document uses that the format approximates or ignores
def support_findings(markdown, output_format):
    found, seen, in_fence = [], set(), False
    for number, text in enumerate(str(markdown or "").split("\n"), 1):
        if FENCE_LINE.match(text):
            in_fence = not in_fence
            continue
        for feature, (status, note) in limits_of(output_format).items():
            if feature not in seen and not in_fence and re.search(SUPPORT[feature][4], text):
                seen.add(feature)
                found.append((number, "info", f"{SUPPORT[feature][0]}: {status} in {output_format} ({note})", "check the output if this matters"))
    return found


# the support table as lines: one line per feature with its status for each format
def support_table():
    return "\n".join(f"- {row[0]}: " + ", ".join(f"{name} {status_of(feature, name)}" for name in SUPPORT_FORMATS) for feature, row in SUPPORT.items())
