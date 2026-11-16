import os
from datetime import date, datetime, time, timezone
from pathlib import Path

FONTS_BY_FILE = {"PTSerif": "Georgia"}
SANS_FONT, MONO_FONT = "Calibri", "Consolas"


# lightens a color toward white by the requested share
def lifted(rgb, amount=0.4):
    return tuple(int(channel + (255 - channel) * amount) for channel in rgb)


# formats an ISO date as a long readable date
def long_date(text):
    try:
        moment = datetime.strptime(str(text).strip(), "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{moment.day} {moment:%B %Y}"


# parses a creation date or returns the current time
def creation_date(written):
    try:
        if written:
            return datetime.combine(date.fromisoformat(str(written)), time.min, tzinfo=timezone.utc)
    except ValueError:
        pass
    epoch = os.getenv("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return datetime.combine(date.today(), time.min, tzinfo=timezone.utc)


# maps a font file path to a font name supported by Office
def office_font(path):
    return next((font for stem, font in FONTS_BY_FILE.items() if stem in Path(path).name), SANS_FONT)
