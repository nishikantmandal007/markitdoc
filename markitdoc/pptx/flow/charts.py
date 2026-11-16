import io

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_MARK
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from markitdoc.markup.inline import plain_text
from markitdoc.pptx.deck import WHITE, tint
from markitdoc.pptx.photos import add_image
from markitdoc.visuals.charts import render_chart

CHART_SCALE, CHART_DPI = 1.6, 200
CHART_ROLES = ("mood", "second", "muted", "night", "success", "danger")
NATIVE_CHARTS = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "horizontal_bar": XL_CHART_TYPE.BAR_CLUSTERED, "stacked_bar": XL_CHART_TYPE.COLUMN_STACKED,
                 "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE, "donut": XL_CHART_TYPE.DOUGHNUT}


# renders chart data as a themed PNG for a slide
def chart_png(deck, data, width, height):
    data = {**data, "colors": ["#" + deck.theme.colors[role].lstrip("#") for role in ("mood", "second", "muted", "primary", "success", "danger")],
            "background": "#" + deck.theme.colors["paper"].lstrip("#"), "font": str(deck.theme.fonts["body"])}
    return io.BytesIO(render_chart(data, width_inches=width / CHART_SCALE, height_inches=height / CHART_SCALE, dpi=CHART_DPI))


# adds a native or rendered chart to a slide
def place_chart(deck, slide, piece, box):
    data = piece.data
    if data["type"] == "waterfall":
        place_waterfall(deck, slide, data, box)
        return
    kind = NATIVE_CHARTS.get(data["type"])
    if kind is None:
        left, top, width, height = box
        add_image(slide, chart_png(deck, data, width, height), left, top, width, height, f"Chart: {data.get('title') or data['type']}")
        return
    values = CategoryChartData()
    values.categories = [str(label) for label in data.get("labels") or range(1, len(data["datasets"][0]["values"]) + 1)]
    for number, dataset in enumerate(data["datasets"], 1):
        values.add_series(str(dataset.get("label") or f"Series {number}"), [float(value) for value in dataset["values"]])
    left, top, width, height = box
    graphic = slide.shapes.add_chart(kind, Inches(left), Inches(top), Inches(width), Inches(height), values)
    graphic.name = "Chart"
    style_chart(deck, graphic.chart, data, kind in (XL_CHART_TYPE.PIE, XL_CHART_TYPE.DOUGHNUT), deck.section_title)


# converts waterfall values into cumulative chart steps
def waterfall_steps(data):
    labels = [str(label) for label in data.get("labels") or []]
    values = [float(value) for value in data["datasets"][0]["values"]]
    if not values:
        return []
    steps, running = [(labels[0] if labels else "Start", 0.0, values[0], "total")], values[0]
    for label, value in zip(labels[1:] or [f"Step {n}" for n in range(1, len(values))], values[1:]):
        steps.append((label, running if value >= 0 else running + value, abs(value), "up" if value >= 0 else "down"))
        running += value
    if data.get("total"):
        steps.append((str(data["total"]), 0.0, running, "total"))
    return steps


# builds and styles a native waterfall chart on a slide
def place_waterfall(deck, slide, data, box):
    steps = waterfall_steps(data)
    values = CategoryChartData()
    values.categories = [label for label, _, _, _ in steps]
    values.add_series("Base", [base for _, base, _, _ in steps])
    for kind in ("total", "up", "down"):
        values.add_series(kind, [size if step == kind else 0 for _, _, size, step in steps])
    left, top, width, height = box
    graphic = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, Inches(left), Inches(top), Inches(width), Inches(height), values)
    graphic.name = "Chart"
    chart = graphic.chart
    chart.font.size, chart.font.name = Pt(13), deck.body_font
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.gap_width, plot.overlap = 45, 100
    colors = {"total": deck.color("night"), "up": deck.color("success"), "down": deck.color("danger")}
    for series in chart.series:
        if series.name == "Base":
            series.format.fill.background()
            series.format.line.fill.background()
            continue
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = colors[series.name]
        for index, (_, _, size, step) in enumerate(steps):
            if step == series.name and size:
                label = series.points[index].data_label
                label.has_text_frame = True
                sign = "+" if step == "up" else "−" if step == "down" else ""
                label.text_frame.text = f"{sign}{size:,.10g}"
                label.position = XL_LABEL_POSITION.INSIDE_BASE if step == "total" else XL_LABEL_POSITION.CENTER
                font = label.text_frame.paragraphs[0].runs[0].font
                font.size, font.bold, font.name = Pt(14 if step == "total" else 13), True, deck.body_font
                font.color.rgb = deck.color(WHITE)
    value_axis, category_axis = chart.value_axis, chart.category_axis
    value_axis.visible, value_axis.has_major_gridlines = False, False
    category_axis.format.line.color.rgb = deck.color("rule")
    category_axis.tick_labels.font.size = Pt(13)
    category_axis.tick_labels.font.color.rgb = deck.color("body")
    category_axis.major_tick_mark = XL_TICK_MARK.NONE


# applies document fonts, colors, labels, and values to a chart
def style_chart(deck, chart, data, round_chart, slide_title=""):
    colors = [deck.color(role) for role in CHART_ROLES]
    many = len(data["datasets"]) > 1
    if many and not round_chart:
        colors = [deck.color(tint(deck, "mood", 0.62)), deck.color("mood"), deck.color("night"), deck.color("muted")]
    chart.font.size, chart.font.name = Pt(13), deck.body_font
    chart.font.color.rgb = deck.color("body")
    chart.has_title = bool(data.get("title")) and plain_text(str(data["title"])).lower() not in plain_text(slide_title).lower()
    if chart.has_title:
        chart.chart_title.text_frame.text = plain_text(str(data["title"]))
        title_font = chart.chart_title.text_frame.paragraphs[0].font
        title_font.size, title_font.bold, title_font.name = Pt(16), True, deck.body_font
        title_font.color.rgb = deck.color("ink")
    line_chart = data["type"] == "line"
    chart.has_legend = (many and not line_chart) or round_chart
    if chart.has_legend:
        chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.TOP if not round_chart else XL_LEGEND_POSITION.BOTTOM, False
        chart.legend.font.size = Pt(13)
        chart.legend.font.color.rgb = deck.color("body")
    plot = chart.plots[0]
    plot.has_data_labels = not line_chart
    if plot.has_data_labels:
        labels = plot.data_labels
        labels.font.size, labels.number_format, labels.number_format_is_linked = Pt(13), "#,##0.##", False
        labels.font.color.rgb = deck.color("ink")
        if data["type"] == "stacked_bar":
            labels.position = XL_LABEL_POSITION.CENTER
            labels.font.color.rgb = deck.color(WHITE)
        elif not round_chart:
            labels.position = XL_LABEL_POSITION.OUTSIDE_END
    if round_chart:
        labels.show_value, labels.show_percentage, labels.number_format = False, True, "0%"
        labels.font.color.rgb, labels.font.bold = deck.color(WHITE), True
        donut_colors = [deck.color(tint(deck, "mood", share)) for share in (0.0, 0.3, 0.5, 0.65, 0.78, 0.88)]
        for index, point in enumerate(chart.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = donut_colors[index % len(donut_colors)] if data["type"] == "donut" else colors[index % len(colors)]
            point.format.line.color.rgb, point.format.line.width = deck.color("paper"), Pt(2)
        hole = plot._element.find(qn("c:holeSize"))
        if hole is not None:
            hole.set("val", "62")
        return
    if not line_chart:
        plot.gap_width = 60
        if many:
            plot.overlap = -12
    for index, series in enumerate(chart.series):
        if line_chart:
            color = colors[index % len(colors)] if many else deck.color("mood")
            series.format.line.color.rgb, series.format.line.width = color, Pt(3.25)
            series.smooth = False
            series.marker.style = XL_MARKER_STYLE.NONE
            last = series.points[len(data["datasets"][index]["values"]) - 1]
            last.marker.style, last.marker.size = XL_MARKER_STYLE.CIRCLE, 9
            last.marker.format.fill.solid()
            last.marker.format.fill.fore_color.rgb = color
            last.marker.format.line.color.rgb = color
            label = last.data_label
            label.position = XL_LABEL_POSITION.RIGHT
            label.has_text_frame = True
            name = str(data["datasets"][index].get("label") or "") if many else ""
            value = data["datasets"][index]["values"][-1]
            label.text_frame.text = f"{value:,.10g}" + (f"  {name}" if name else "")
            font = label.text_frame.paragraphs[0].runs[0].font
            font.size, font.bold, font.name = Pt(13), True, deck.body_font
            font.color.rgb = color
        else:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = colors[index % len(colors)] if many else deck.color(tint(deck, "mood", 0.45))
            if not many:
                largest = max(range(len(data["datasets"][0]["values"])), key=lambda position: data["datasets"][0]["values"][position])
                point = series.points[largest]
                point.format.fill.solid()
                point.format.fill.fore_color.rgb = deck.color("mood")
    value_axis, category_axis = chart.value_axis, chart.category_axis
    value_axis.has_major_gridlines = data["type"] == "line"
    if value_axis.has_major_gridlines:
        value_axis.major_gridlines.format.line.color.rgb = deck.color("rule")
    value_axis.visible = data["type"] == "line"
    value_axis.format.line.fill.background()
    value_axis.tick_labels.font.size = Pt(12)
    value_axis.tick_labels.font.color.rgb = deck.color("muted")
    category_axis.format.line.color.rgb = deck.color("rule")
    category_axis.tick_labels.font.size = Pt(13)
    category_axis.tick_labels.font.color.rgb = deck.color("body")
    category_axis.has_major_gridlines = False
    category_axis.major_tick_mark = value_axis.major_tick_mark = XL_TICK_MARK.NONE
    if data["type"] == "horizontal_bar":
        category_axis.reverse_order = True
