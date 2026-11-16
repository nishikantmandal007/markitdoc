import os
from datetime import date, datetime, time, timezone
from pathlib import Path

fonts_by_file = {"PTSerif": "Georgia"}
sans_font, mono_font = "Calibri", "Consolas"


def lifted(rgb, amount=0.4):
    return tuple(int(channel + (255 - channel) * amount) for channel in rgb)


def long_date(text):
    try:
        moment = datetime.strptime(str(text).strip(), "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{moment.day} {moment:%B %Y}"


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


def office_font(path):
    return next((font for stem, font in fonts_by_file.items() if stem in Path(path).name), sans_font)
