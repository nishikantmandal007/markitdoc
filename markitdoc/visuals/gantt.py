import calendar
import re

from markitdoc.markup.inline import plain_text

MONTH_NUMBERS = {name.lower(): number for number, name in enumerate(calendar.month_abbr) if name}
RANGE_SPLIT = re.compile(r"\s*(?:–|—|-|\bto\b)\s*")


# parses a quarter, month, or year and resolves its year
def moment(text, year):
    text = text.strip().rstrip(".")
    found = re.fullmatch(r"(?i)Q([1-4])\s*'?(\d{2}|\d{4})?", text)
    if found:
        return "quarter", int(found.group(1)) - 1, full_year(found.group(2), year)
    found = re.fullmatch(r"(?i)([a-z]{3})[a-z]*\.?\s*'?(\d{2}|\d{4})?", text)
    if found and found.group(1).lower() in MONTH_NUMBERS:
        return "month", MONTH_NUMBERS[found.group(1).lower()] - 1, full_year(found.group(2), year)
    found = re.fullmatch(r"(\d{4})", text)
    return ("year", 0, int(found.group(1))) if found else None


# expands a two-digit year or keeps the supplied full year
def full_year(text, year):
    if not text:
        return year
    return int(text) + 2000 if len(text) == 2 else int(text)


# parses a date range into comparable calendar periods
def period(text):
    parts = [part for part in RANGE_SPLIT.split(plain_text(text).strip()) if part]
    if not 1 <= len(parts) <= 2:
        return None
    end = moment(parts[-1], None)
    start = moment(parts[0], end[2] if end else None) if len(parts) == 2 else end
    if not start or not end or start[0] != end[0] or start[2] is None or end[2] is None:
        return None
    per_year = {"quarter": 4, "month": 12, "year": 1}[start[0]]
    first, last = start[2] * per_year + start[1], end[2] * per_year + end[1]
    return (start[0], first, last) if last >= first else None


# checks whether timeline entries fit a compact Gantt chart
def gantt_plan(items):
    periods = [period(item[0]) for item in items]
    if len(items) < 3 or not all(periods) or len({found[0] for found in periods}) != 1 or not any(found[2] > found[1] for found in periods):
        return None
    first, last = min(found[1] for found in periods), max(found[2] for found in periods)
    return (periods[0][0], first, last, periods) if last - first < 24 else None


# formats a period index as a year, month, or quarter label
def unit_name(unit, value):
    if unit == "quarter":
        return f"Q{value % 4 + 1} {value // 4}"
    if unit == "month":
        return f"{calendar.month_abbr[value % 12 + 1]} {str(value // 12)[2:]}"
    return str(value)
