import re

FLOW_LAYOUT = "flow"
FLOW_CONTAINERS = ("box", "sidebar", "columns")
FREE_TEXT_SETTINGS = ("header", "footer", "title", "subject", "author")
ITEM_SEPARATOR = " — "
STRONG_SEPARATORS = (" — ", " – ", " | ")
BULLET_SEPARATORS = (" - ", ": ")
BARE_DIRECTIVES = {
    "toc": frozenset({"true", "yes", "show", "on", "false", "no", "hide", "off"}),
    "date": frozenset({"true", "yes", "show", "on", "false", "no", "off", "hide", "hidden"}),
    "template": frozenset({"default", "company"}),
}

BLOCK_START = re.compile(r"^##\s+(page|slide)(\s+\d+)?\s*:?\s*$", re.IGNORECASE)
SLOT_LINE = re.compile(r"^([a-z_]+):\s*(.*)$")
DIV_OPEN = re.compile(r"^:::+\s*\{?\s*\.?([a-z][\w-]*)(.*?)\}?\s*$", re.IGNORECASE)
DIV_CLOSE = re.compile(r"^:::+\s*$")
ATTRIBUTE = re.compile(r'([a-z_]+)=("([^"]*)"|\S+)')
BARE_DIRECTIVE = re.compile(r"^([A-Za-z]+)\s*:\s*(\S.*?)\s*$")
