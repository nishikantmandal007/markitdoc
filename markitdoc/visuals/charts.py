import io
import json
import textwrap
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib import patheffects
import matplotlib.ticker as mticker


_PALETTE = [
    "#4F7DF9", "#22C997", "#FDAD33", "#F25D5D",
    "#9B6DF7", "#F472B6", "#22BDD8", "#FB923C",
]



def series_color(data, index):
    palette = data.get("colors") or _PALETTE
    return palette[index % len(palette)]


_BG = "#FAFBFC"
_TEXT = "#374151"
_MUTED = "#9CA3AF"
_GRID = "#F0F1F3"
_INK = "#111827"


def _apply_theme(ax, fig, chart_type="bar"):
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_MUTED, labelsize=9, length=0, pad=8)
    ax.xaxis.label.set_color(_TEXT)
    ax.yaxis.label.set_color(_TEXT)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if chart_type not in ("pie", "donut"):
        ax.yaxis.grid(True, color=_GRID, linewidth=0.5, linestyle="--", alpha=0.8)
        ax.xaxis.grid(False)
    ax.set_axisbelow(True)


def _fmt_val(val):
    if isinstance(val, float) and val != int(val):
        return f"{val:,.1f}"
    return f"{int(val):,}"


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
                      color=series_color(data, i), alpha=0.92,
                      edgecolor="none", zorder=3)
        all_bars.append(bars)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5, color=_TEXT)
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(ymin, ymax * 1.15)
    if n <= 3:
        for bars in all_bars:
            ax.bar_label(bars, fmt=lambda v: _fmt_val(v) if v else "",
                         padding=3, fontsize=8, color=_MUTED, fontweight="medium")
    if any(ds.get("label") for ds in datasets):
        ax.legend(fontsize=8.5, frameon=False, labelcolor=_TEXT,
                  loc="upper right", ncol=min(len(datasets), 4),
                  handlelength=1.0, handletextpad=0.4, columnspacing=0.8,
                  borderaxespad=0.3)


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
                       color=series_color(data, i), alpha=0.92,
                       edgecolor="none", zorder=3)
        all_bars.append(bars)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9.5, color=_TEXT)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.5, linestyle="--", alpha=0.8)
    ax.yaxis.grid(False)
    ax.tick_params(axis="x", length=0)
    xmin, xmax = ax.get_xlim()
    ax.set_xlim(xmin, xmax * 1.12)
    if n <= 2:
        for bars in all_bars:
            ax.bar_label(bars, fmt=lambda v: _fmt_val(v) if v else "",
                         padding=4, fontsize=8, color=_MUTED, fontweight="medium")
    if any(ds.get("label") for ds in datasets):
        ax.legend(fontsize=8.5, frameon=False, labelcolor=_TEXT,
                  loc="lower right", ncol=min(len(datasets), 3),
                  borderaxespad=0.3)


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
    ax.set_xticklabels(labels, fontsize=9.5, color=_TEXT)
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(ymin, ymax * 1.08)
    if any(ds.get("label") for ds in datasets):
        ax.legend(fontsize=8.5, frameon=False, labelcolor=_TEXT,
                  loc="upper right", ncol=min(len(datasets), 4),
                  handlelength=1.0, handletextpad=0.4, borderaxespad=0.3)


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
    ax.set_xticklabels(labels, fontsize=9.5, color=_TEXT)
    has_labels = any(ds.get("label") for ds in datasets)
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


def _pie(ax, data, donut=False):
    labels = data["labels"]
    values = data.get("datasets", [{}])[0].get("values", [])
    colors = [series_color(data, i) for i in range(len(values))]
    wedgeprops = {"edgecolor": "#FFFFFF", "linewidth": 2.5}
    if donut:
        wedgeprops["width"] = 0.42
    wedges, texts, autotexts = ax.pie(
        values, labels=None, colors=colors, autopct=lambda share: f"{share:.0f}%" if share >= 5 else "",
        textprops={"fontsize": 9}, pctdistance=0.76 if donut else 0.58,
        wedgeprops=wedgeprops, startangle=90)
    for t in autotexts:
        t.set_color("#FFFFFF")
        t.set_fontweight("bold")
        t.set_fontsize(8.5)
        t.set_path_effects([
            patheffects.withStroke(linewidth=2.5, foreground="#00000022")])
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.05, 0.5),
              fontsize=9, frameon=False, labelcolor=_TEXT,
              handlelength=1.0, handletextpad=0.5)


def _waterfall(ax, data):
    labels = list(data["labels"])
    values = [float(value) for value in data["datasets"][0]["values"]]
    bases, sizes, colors, running = [0.0], [values[0]], [series_color(data, 0)], values[0]
    for value in values[1:]:
        bases.append(running if value >= 0 else running + value)
        sizes.append(abs(value))
        colors.append(series_color(data, 4) if value >= 0 else series_color(data, 5))
        running += value
    if data.get("total"):
        labels.append(str(data["total"]))
        bases.append(0.0)
        sizes.append(running)
        colors.append(series_color(data, 0))
    x = list(range(len(labels)))
    if len(labels) > 5:
        labels = [textwrap.fill(str(label), 12) for label in labels]
    ax.bar(x, sizes, bottom=bases, width=0.6, color=colors, edgecolor="none", zorder=3)
    for position, (base, size, value) in enumerate(zip(bases, sizes, [values[0]] + values[1:] + ([running] if data.get("total") else []))):
        sign = "+" if 0 < position < len(values) and value >= 0 else ""
        ax.text(position, base + size, f"{sign}{value:,.10g}", ha="center", va="bottom", fontsize=9.5, color=_TEXT, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5 if len(labels) <= 6 else 8, color=_TEXT)
    ax.set_yticks([])
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)


_RENDERERS = {
    "waterfall": _waterfall,
    "bar": _bar,
    "horizontal_bar": _horizontal_bar,
    "stacked_bar": _stacked_bar,
    "line": _line,
    "pie": lambda ax, d: _pie(ax, d, donut=False),
    "donut": lambda ax, d: _pie(ax, d, donut=True),
}


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
    if data["type"] not in _RENDERERS:
        return None
    if "labels" not in data and data["type"] not in ("pie", "donut"):
        return None
    return data


def render_chart(data: dict, width_inches: float = 6.0,
                 height_inches: float = 3.5, dpi: int = 150) -> bytes:
    chart_type = data["type"]
    previous_family = plt.rcParams["font.family"]
    if data.get("font"):
        font_manager.fontManager.addfont(data["font"])
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=data["font"]).get_name()
    fig, ax = plt.subplots(figsize=(width_inches, height_inches),
                           layout="constrained")
    try:
        _apply_theme(ax, fig, chart_type)
        if data.get("background"):
            fig.set_facecolor(data["background"])
            ax.set_facecolor(data["background"])

        renderer = _RENDERERS[chart_type]
        renderer(ax, data)
        if data.get("font") and chart_type in ("bar", "line", "stacked_bar"):
            labels = [label.get_text() for label in ax.get_xticklabels()]
            if labels and max(len(label) for label in labels) > 12:
                ax.set_xticks(ax.get_xticks(), [textwrap.fill(label, 14) for label in labels])

        if data.get("title"):
            ax.set_title(data["title"], pad=16, fontsize=13, fontweight="bold",
                         color=_INK, loc="left")
        if data.get("x_label"):
            ax.set_xlabel(data["x_label"], fontsize=9.5, labelpad=10)
        if data.get("y_label"):
            ax.set_ylabel(data["y_label"], fontsize=9.5, labelpad=10)

        if chart_type in ("pie", "donut"):
            ax.set_aspect("equal")
            ax.grid(False)

        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"{int(v):,}" if v == int(v) else f"{v:,.1f}"))

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                    facecolor=fig.get_facecolor(), pad_inches=0.15)
    finally:
        plt.close(fig)
        plt.rcParams["font.family"] = previous_family
    buf.seek(0)
    return buf.read()


def get_fence_language(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("```"):
        return stripped[3:].strip().lower()
    return ""
