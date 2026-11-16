import re
from dataclasses import dataclass, field

TOKEN = re.compile(r'#(?P<id>[\w-]+)|\.(?P<cls>[\w-]+)|(?P<key>[\w-]+)=(?:"(?P<quoted>[^"]*)"|(?P<plain>\S+))|(?P<flag>[\w-]+)')
KEY_ALIASES = {"colour": "color", "text-align": "align", "font-size": "size"}
VALUE_ALIASES = {"centre": "center", "grey": "gray"}


@dataclass(frozen=True)
class Attributes:
    id: str = ""
    classes: tuple = ()
    values: dict = field(default_factory=dict)


# '{#id .a key=value key="quoted value" flag}' to its id, classes, values and flags
def parse_attributes(text) -> Attributes:
    text = str(text or "").strip()
    text = text[1:-1] if text.startswith("{") and text.endswith("}") else text.lstrip("{").rstrip("}")
    ident, classes, values = "", [], {}
    for found in TOKEN.finditer(text):
        if found["id"]:
            ident = ident or found["id"]
        elif found["cls"]:
            classes.append(found["cls"])
        elif found["key"]:
            key = found["key"].lower()
            plain = found["plain"]
            values[KEY_ALIASES.get(key, key)] = found["quoted"] if plain is None else VALUE_ALIASES.get(plain.lower(), plain)
        else:
            values[KEY_ALIASES.get(found["flag"].lower(), found["flag"].lower())] = True
    return Attributes(id=ident, classes=tuple(classes), values=values)
