import io
import json
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib import font_manager, patheffects

_PALETTE = [
    "#4F7DF9", "#22C997", "#FDAD33", "#F25D5D",
    "#9B6DF7", "#F472B6", "#22BDD8", "#FB923C",
]



# selects a chart series color from the configured palette
def series_color(data, index):
    palette = data.get("colors") or _PALETTE
    return palette[index % len(palette)]


_BG = "#FAFBFC"
_TEXT = "#374151"
_MUTED = "#596579"
_REFERENCE = "#8998A8"
_MIN_LABEL_SIZE = 9
_MAX_PRECISION = 6
_GRID = "#F0F1F3"
_INK = "#111827"


# joins the takeaway with its unit unless the title already includes the unit
def chart_title(data):
    title, unit = (str(data.get(key) or "").strip() for key in ("title", "unit"))
    return f"{title} ({unit})" if title and unit and unit.lower() not in title.lower() else title or unit


# picks the highlighted category, using the largest value when the writer leaves it open
def highlight_index(data, default=None):
    labels = data.get("labels", [])
    value = data.get("highlight")
    if value in labels and value is not None:
        return labels.index(value)
    if default is not None:
        return default
    values = data["datasets"][0]["values"]
    return max(range(len(values)), key=values.__getitem__)


# prints a chart value with the chart's requested precision and an optional leading sign
def chart_value(value, data, signed=False):
    places = data.get("precision")
    if type(places) is int and 0 <= places <= _MAX_PRECISION:
        return format(value, f"{'+' if signed else ''},.{places}f").replace("-", "−")
    return format(value, ("+" if signed else "") + ",.10g").replace("-", "−")


# returns a categorical bar's color, keeping one point prominent in a single-series chart
def bar_colors(data, series, categories):
    color = series_color(data, series)
    if len(data["datasets"]) > 1:
        return color
    highlight = highlight_index(data)
    return [color if index == highlight else _REFERENCE for index in range(categories)]


# registers regular and bold faces once so Matplotlib can draw both weights
@lru_cache(maxsize=32)
def chart_family(path):
    font = Path(path)
    for face in {font, font.with_name(font.name.replace("-Regular", "-Bold"))}:
        if face.is_file():
            font_manager.fontManager.addfont(str(face))
    return font_manager.FontProperties(fname=path).get_name()


# sets chart backgrounds, tick labels, and grid styling
def _apply_theme(ax, fig, chart_type="bar"):
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_MUTED, labelsize=_MIN_LABEL_SIZE, length=0, pad=5)
    ax.xaxis.label.set_color(_TEXT)
    ax.yaxis.label.set_color(_TEXT)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if chart_type not in ("pie", "donut"):
        ax.yaxis.grid(True, color=_GRID, linewidth=0.5, linestyle="--", alpha=0.8)
        ax.xaxis.grid(False)
    ax.set_axisbelow(True)


# draws a vertical bar chart with labels and value annotations
def _bar(ax, data):
    labels = data["labels"]
    datasets = data.get("datasets", [])
    x = list(range(len(labels)))
    n = max(len(datasets), 1)
    total_width = 0.7
    width = total_width / n
    all_bars = []
    for i, ds in enumerate(datasets):
        offset = (i - n / 2 + 0.5) * width
        bars = ax.bar([xi + offset for xi in x], ds["values"],
                      width=width * 0.88, label=ds.get("label", ""),
                      color=bar_colors(data, i, len(labels)),
                      edgecolor="none", zorder=3)
        all_bars.append(bars)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10, color=_TEXT)
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(ymin, ymax * 1.15)
    if n <= 3:
        for bars in all_bars:
            ax.bar_label(bars, fmt=lambda v: chart_value(v, data) if v else "",
                         padding=3, fontsize=_MIN_LABEL_SIZE, color=_TEXT)
    if len(datasets) > 1 and any(ds.get("label") for ds in datasets):
        ax.legend(fontsize=8.5, frameon=False, labelcolor=_TEXT,
                  loc="upper right", ncol=min(len(datasets), 4),
                  handlelength=1.0, handletextpad=0.4, columnspacing=0.8,
                  borderaxespad=0.3)


# draws a horizontal bar chart with labels and value annotations
def _horizontal_bar(ax, data):
    labels = data["labels"]
    datasets = data.get("datasets", [])
    y = list(range(len(labels)))
    n = max(len(datasets), 1)
    total_height = 0.7
    height = total_height / n
    all_bars = []
    for i, ds in enumerate(datasets):
        offset = (i - n / 2 + 0.5) * height
        bars = ax.barh([yi + offset for yi in y], ds["values"],
                       height=height * 0.88, label=ds.get("label", ""),
                       color=bar_colors(data, i, len(labels)),
                       edgecolor="none", zorder=3)
        all_bars.append(bars)
    ax.set_yticks(y)
    ax.set_yticklabels([textwrap.fill(str(label), 22) for label in labels], fontsize=10, color=_TEXT)
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=_GRID, linewidth=0.5, linestyle="--", alpha=0.8)
    ax.yaxis.grid(False)
    ax.tick_params(axis="x", length=0)
    xmin, xmax = ax.get_xlim()
    ax.set_xlim(xmin, xmax * 1.12)
    if n <= 2:
        for bars in all_bars:
            ax.bar_label(bars, fmt=lambda v: chart_value(v, data) if v else "",
                         padding=4, fontsize=_MIN_LABEL_SIZE, color=_TEXT)
    if len(datasets) > 1 and any(ds.get("label") for ds in datasets):
        ax.legend(fontsize=8.5, frameon=False, labelcolor=_TEXT,
                  loc="lower right", ncol=min(len(datasets), 3),
                  borderaxespad=0.3)


# draws stacked bars for each chart category
def _stacked_bar(ax, data):
    labels = data["labels"]
    datasets = data.get("datasets", [])
    x = list(range(len(labels)))
    bottom = [0] * len(labels)
    for i, ds in enumerate(datasets):
        ax.bar(x, ds["values"], bottom=bottom, width=0.55,
               label=ds.get("label", ""),
               color=series_color(data, i), alpha=0.92,
               edgecolor="none", zorder=3)
        bottom = [b + v for b, v in zip(bottom, ds["values"])]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10, color=_TEXT)
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(ymin, ymax * 1.08)
    if len(datasets) > 1 and any(ds.get("label") for ds in datasets):
        ax.legend(fontsize=8.5, frameon=False, labelcolor=_TEXT,
                  loc="upper right", ncol=min(len(datasets), 4),
                  handlelength=1.0, handletextpad=0.4, borderaxespad=0.3)


# draws one or more lines across the chart categories
def _line(ax, data):
    labels = data["labels"]
    datasets = data.get("datasets", [])
    x = list(range(len(labels)))
    for i, ds in enumerate(datasets):
        color = series_color(data, i)
        ax.plot(x, ds["values"], marker="o", markersize=6,
                linewidth=2.4, label=ds.get("label", ""),
                color=color, zorder=3,
                markerfacecolor="#FFFFFF", markeredgecolor=color, markeredgewidth=2.2)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10, color=_TEXT)
    if len(datasets) == 1:
        values = datasets[0]["values"]
        point = highlight_index(data, len(values) - 1)
        ax.scatter([point], [values[point]], s=65, color=series_color(data, 0), edgecolors="white", zorder=4)
    has_labels = len(datasets) > 1 and any(ds.get("label") for ds in datasets)
    if has_labels and len(datasets) <= 4:
        for i, ds in enumerate(datasets):
            color = series_color(data, i)
            name = ds.get("label", "")
            if name:
                ax.annotate(name, xy=(len(labels) - 1, ds["values"][-1]),
                            xytext=(12, 0), textcoords="offset points",
                            fontsize=8.5, color=color, fontweight="semibold",
                            va="center", clip_on=False)
        ax.set_xlim(-0.3, len(labels) - 0.4)
    elif has_labels:
        ax.legend(fontsize=8.5, frameon=False, labelcolor=_TEXT,
                  loc="upper left", ncol=min(len(datasets), 3),
                  borderaxespad=0.3)
        ax.set_xlim(-0.3, len(labels) - 0.8)
    else:
        ax.set_xlim(-0.3, len(labels) - 0.8)
    ymin, ymax = ax.get_ylim()
    margin = (ymax - ymin) * 0.08
    ax.set_ylim(ymin - margin, ymax + margin)


# draws a pie or donut chart with category labels
def _pie(ax, data, donut=False):
    labels = data["labels"]
    values = data.get("datasets", [{}])[0].get("values", [])
    colors = [series_color(data, i) for i in range(len(values))]
    if data.get("highlight") in labels:
        colors = bar_colors(data, 0, len(labels))
    wedgeprops = {"edgecolor": "#FFFFFF", "linewidth": 2.5}
    if donut:
        wedgeprops["width"] = 0.42
    _, _, autotexts = ax.pie(
        values, labels=[textwrap.fill(str(label), 20) for label in labels], colors=colors,
        autopct=lambda share: f"{share:.0f}%" if share >= 5 else "",
        textprops={"fontsize": 9}, pctdistance=0.76 if donut else 0.58,
        wedgeprops=wedgeprops, startangle=90)
    for t in autotexts:
        t.set_color("#FFFFFF")
        t.set_fontweight("bold")
        t.set_fontsize(8.5)
        t.set_path_effects([
            patheffects.withStroke(linewidth=2.5, foreground="#00000022")])


# calculates the baseline, change steps and closing total for each waterfall renderer
def waterfall_steps(data):
    values = data["datasets"][0]["values"]
    labels = data.get("labels") or ["Start", *(f"Step {i}" for i in range(1, len(values)))]
    running = values[0]
    steps = [(str(labels[0]), 0, running, "total")]
    for label, value in zip(labels[1:], values[1:]):
        steps.append((str(label), min(running, running + value), abs(value), "up" if value >= 0 else "down"))
        running += value
    if data.get("total"):
        steps.append((str(data["total"]), 0, running, "total"))
    return steps


# draws cumulative increases and decreases as a connected waterfall chart
def _waterfall(ax, data):
    steps = waterfall_steps(data)
    x = list(range(len(steps)))
    highlight = highlight_index(data, len(steps) - 1)
    colors = [series_color(data, 0) if index == highlight else
              series_color(data, 4) if kind == "up" else series_color(data, 5) if kind == "down" else _REFERENCE
              for index, (_, _, _, kind) in enumerate(steps)]
    ax.bar(x, [size for _, _, size, _ in steps], bottom=[base for _, base, _, _ in steps], width=0.64, color=colors, zorder=3)
    for position, (_, base, size, kind) in enumerate(steps):
        end = base if kind == "down" else base + size
        if position + 1 < len(steps):
            ax.hlines(end, position + 0.32, position + 0.68, color=_MUTED, linewidth=0.8, zorder=2)
        value = -size if kind == "down" else size
        ax.annotate(chart_value(value, data, signed=kind != "total"), (position, max(base, base + size)), xytext=(0, 3),
                    textcoords="offset points", ha="center", va="bottom", fontsize=10, color=_INK, fontweight="bold")
    label_width = max(9, min(17, round(ax.figure.get_figwidth() * 13 / len(steps))))
    ax.set_xticks(x, [textwrap.fill(label, label_width, break_long_words=False) for label, *_ in steps], fontsize=_MIN_LABEL_SIZE, color=_TEXT)
    ax.set_yticks([])
    ax.margins(y=0.16)
    ax.axhline(0, color=_GRID, linewidth=0.8)


_RENDERERS = {
    "waterfall": _waterfall,
    "bar": _bar,
    "horizontal_bar": _horizontal_bar,
    "stacked_bar": _stacked_bar,
    "line": _line,
    "pie": lambda ax, d: _pie(ax, d, donut=False),
    "donut": lambda ax, d: _pie(ax, d, donut=True),
}


# parses chart data from JSON or simple chart fence syntax
def parse_chart_fence(lines: list[str]) -> Optional[dict]:
    raw = "\n".join(lines).strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or "type" not in data:
        return None
    if not isinstance(data["type"], str) or data["type"] not in _RENDERERS:
        return None
    if "labels" not in data and data["type"] not in ("pie", "donut"):
        return None
    return data


# renders validated chart data as a PNG image
def render_chart(data: dict, width_inches: float = 6.0,
                 height_inches: float = 3.5, dpi: int = 150) -> bytes:
    chart_type = data["type"]
    previous_family = plt.rcParams["font.family"]
    if data.get("font"):
        plt.rcParams["font.family"] = chart_family(data["font"])
    fig, ax = plt.subplots(figsize=(width_inches, height_inches),
                           layout="constrained")
    try:
        _apply_theme(ax, fig, chart_type)
        if data.get("background"):
            fig.set_facecolor(data["background"])
            ax.set_facecolor(data["background"])

        renderer = _RENDERERS[chart_type]
        renderer(ax, data)
        if chart_type in ("bar", "line", "stacked_bar"):
            labels = [label.get_text() for label in ax.get_xticklabels()]
            if labels:
                wrap = max(9, min(22, round(width_inches * 13 / len(labels))))
                ax.set_xticks(ax.get_xticks(), [textwrap.fill(label, wrap, break_long_words=False) for label in labels],
                              fontsize=_MIN_LABEL_SIZE, color=_TEXT)

        if title := chart_title(data):
            ax.set_title(textwrap.fill(title, max(25, round(width_inches * 13))), pad=10,
                         fontsize=13, fontweight="bold", color=_INK, loc="left")
        if source := data.get("source"):
            fig.supxlabel("Source: " + str(source), fontsize=8.5, color=_MUTED, ha="left", x=0.02)
        if data.get("x_label"):
            ax.set_xlabel(data["x_label"], fontsize=9.5, labelpad=10)
        if data.get("y_label"):
            ax.set_ylabel(data["y_label"], fontsize=9.5, labelpad=10)

        if chart_type in ("pie", "donut"):
            ax.set_aspect("equal")
            ax.grid(False)

        axis = ax.xaxis if chart_type == "horizontal_bar" else ax.yaxis
        if chart_type not in ("pie", "donut", "waterfall"):
            axis.set_major_formatter(mticker.FuncFormatter(lambda value, _: chart_value(value, {})))

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor=fig.get_facecolor())
    finally:
        plt.close(fig)
        plt.rcParams["font.family"] = previous_family
    buf.seek(0)
    return buf.read()


# returns the language label from an opening code fence
def get_fence_language(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("```"):
        return stripped[3:].strip().lower()
    return ""
