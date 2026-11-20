import io

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import (
    XL_CHART_TYPE,
    XL_LABEL_POSITION,
    XL_LEGEND_POSITION,
    XL_MARKER_STYLE,
    XL_TICK_LABEL_POSITION,
    XL_TICK_MARK,
)
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from markitdoc.markup.inline import literal, plain_text
from markitdoc.pptx.deck import WHITE, tint, write_text
from markitdoc.pptx.photos import add_image
from markitdoc.visuals.charts import chart_title, chart_value, highlight_index, render_chart, waterfall_steps

CHART_SCALE, CHART_DPI = 1.6, 200
SOURCE_HEIGHT = 0.32
WATERFALL_PLOT = (0.04, 0.1, 0.92, 0.70)
WATERFALL_GAP = 45
WATERFALL_LABEL_SIZE = 12
WATERFALL_LABEL_CLEARANCE = 0.23
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
    left, top, width, height = box
    if source := data.get("source"):
        height -= SOURCE_HEIGHT
        write_text(deck, slide, literal(f"Source: {source}"), left, top + height + 0.04, width, 10, "muted", name="Chart source")
    box = left, top, width, height
    if data["type"] == "waterfall":
        steps = waterfall_steps(data)
        if any(min(base, size) < 0 for _, base, size, _ in steps):
            add_image(slide, chart_png(deck, {**data, "source": ""}, width, height), *box, f"Chart: {chart_title(data) or 'waterfall'}")
        else:
            place_waterfall(deck, slide, data, box, steps)
        return
    kind = NATIVE_CHARTS.get(data["type"])
    if kind is None:
        add_image(slide, chart_png(deck, {**data, "source": ""}, width, height), *box, f"Chart: {chart_title(data) or data['type']}")
        return
    values = CategoryChartData()
    values.categories = [str(label) for label in data.get("labels") or range(1, len(data["datasets"][0]["values"]) + 1)]
    for number, dataset in enumerate(data["datasets"], 1):
        values.add_series(str(dataset.get("label") or f"Series {number}"), [float(value) for value in dataset["values"]])
    left, top, width, height = box
    graphic = slide.shapes.add_chart(kind, Inches(left), Inches(top), Inches(width), Inches(height), values)
    graphic.name = "Chart"
    style_chart(deck, graphic.chart, data, kind in (XL_CHART_TYPE.PIE, XL_CHART_TYPE.DOUGHNUT), deck.section_title)


# builds and styles a native waterfall chart on a slide
def place_waterfall(deck, slide, data, box, steps):
    values = CategoryChartData()
    values.categories = [label for label, _, _, _ in steps]
    values.add_series("Base", [base for _, base, _, _ in steps])
    for kind in ("total", "up", "down"):
        values.add_series(kind, [size if step == kind else 0 for _, _, size, step in steps])
    left, top, width, height = box
    if title := chart_title(data):
        used = write_text(deck, slide, literal(title), left, top, width, 16, "ink", bold=True, name="Chart title")
        top, height = top + used + 0.1, height - used - 0.1
    graphic = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, Inches(left), Inches(top), Inches(width), Inches(height), values)
    graphic.name = "Chart"
    chart = graphic.chart
    chart.font.size, chart.font.name = Pt(13), deck.body_font
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.gap_width, plot.overlap = WATERFALL_GAP, 100
    colors = {"total": deck.color("muted"), "up": deck.color("success"), "down": deck.color("danger")}
    highlight = highlight_index(data, len(steps) - 1)
    maximum = (max(base + size for _, base, size, _ in steps) or 1) * 1.12
    for series in chart.series:
        if series.name == "Base":
            series.format.fill.background()
            series.format.line.fill.background()
            continue
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = colors[series.name]
        for index, (_, _, size, step) in enumerate(steps):
            if step == series.name and size:
                point = series.points[index]
                if index == highlight:
                    point.format.fill.solid()
                    point.format.fill.fore_color.rgb = deck.color("mood")
                if size / maximum * height * WATERFALL_PLOT[3] >= WATERFALL_LABEL_CLEARANCE:
                    label = point.data_label
                    label.has_text_frame = True
                    label.text_frame.text = chart_value(-size if step == "down" else size, data, signed=step != "total")
                    label.position = XL_LABEL_POSITION.INSIDE_BASE if step == "total" else XL_LABEL_POSITION.CENTER
                    font = label.text_frame.paragraphs[0].runs[0].font
                    font.size, font.bold, font.name = Pt(14 if step == "total" else 13), True, deck.body_font
                    font.color.rgb = deck.color(WHITE)
    value_axis, category_axis = chart.value_axis, chart.category_axis
    value_axis.visible, value_axis.has_major_gridlines = False, False
    value_axis.minimum_scale = 0
    value_axis.maximum_scale = maximum
    waterfall_connectors(deck, slide, chart, (left, top, width, height), steps, maximum, data)
    category_axis.format.line.color.rgb = deck.color("rule")
    category_axis.tick_label_position = XL_TICK_LABEL_POSITION.NONE
    category_axis.major_tick_mark = XL_TICK_MARK.NONE


# sets a fixed plot area so editable PowerPoint connectors align with the initial chart values
def waterfall_connectors(deck, slide, chart, box, steps, maximum, data):
    layout = chart._chartSpace.chart.plotArea.find(qn("c:layout"))
    if layout is None:
        layout = OxmlElement("c:layout")
        chart._chartSpace.chart.plotArea.insert(0, layout)
    manual = OxmlElement("c:manualLayout")
    layout.append(manual)
    for key, value in (("layoutTarget", "inner"), ("xMode", "edge"), ("yMode", "edge"),
                       *zip(("x", "y", "w", "h"), map(str, WATERFALL_PLOT))):
        element = OxmlElement(f"c:{key}")
        element.set("val", value)
        manual.append(element)
    left, top, width, height = box
    x, y, w, h = WATERFALL_PLOT
    step = w * width / len(steps)
    gap = step * WATERFALL_GAP / (100 + WATERFALL_GAP) / 2
    for index, (label, base, size, kind) in enumerate(steps):
        category_x = left + x * width + index * step
        write_text(deck, slide, literal(label), category_x, top + (y + h) * height + 0.06,
                   step, WATERFALL_LABEL_SIZE, "body", align=PP_ALIGN.CENTER, name="Waterfall category")
        if size / maximum * height * h < WATERFALL_LABEL_CLEARANCE:
            value = chart_value(-size if kind == "down" else size, data, signed=kind != "total")
            above = top + (y + h * (1 - (base + size) / maximum)) * height - 0.24
            write_text(deck, slide, value, category_x, above, step, WATERFALL_LABEL_SIZE, "ink",
                       bold=True, align=PP_ALIGN.CENTER, name="Waterfall value")
    for index, (_, base, size, kind) in enumerate(steps[:-1], 1):
        line_x = left + x * width + step * index
        line_y = top + (y + h * (1 - (base if kind == "down" else base + size) / maximum)) * height
        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(line_x - gap), Inches(line_y),
                                          Inches(line_x + gap), Inches(line_y))
        line.name = "Waterfall connector"
        line.line.color.rgb, line.line.width = deck.color("muted"), Pt(0.75)


# applies document fonts, colors, labels, and values to a chart
def style_chart(deck, chart, data, round_chart, slide_title=""):
    colors = [deck.color(role) for role in CHART_ROLES]
    many = len(data["datasets"]) > 1
    if many and not round_chart:
        colors = [deck.color(tint(deck, "mood", 0.62)), deck.color("mood"), deck.color("night"), deck.color("muted")]
    chart.font.size, chart.font.name = Pt(13), deck.body_font
    chart.font.color.rgb = deck.color("body")
    title = chart_title(data)
    chart.has_title = bool(title) and plain_text(title).lower() not in plain_text(slide_title).lower()
    if chart.has_title:
        chart.chart_title.text_frame.text = plain_text(title)
        title_font = chart.chart_title.text_frame.paragraphs[0].font
        title_font.size, title_font.bold, title_font.name = Pt(16), True, deck.body_font
        title_font.color.rgb = deck.color("ink")
    line_chart = data["type"] == "line"
    chart.has_legend = many and not line_chart and not round_chart
    if chart.has_legend:
        chart.legend.position, chart.legend.include_in_layout = XL_LEGEND_POSITION.TOP if not round_chart else XL_LEGEND_POSITION.BOTTOM, False
        chart.legend.font.size = Pt(13)
        chart.legend.font.color.rgb = deck.color("body")
    plot = chart.plots[0]
    plot.has_data_labels = not line_chart
    if plot.has_data_labels:
        labels = plot.data_labels
        precision = data.get("precision")
        number_format = "#,##0" + ("." + "0" * precision if precision else "") if precision is not None else "#,##0.##"
        labels.font.size, labels.number_format, labels.number_format_is_linked = Pt(13), number_format, False
        labels.font.color.rgb = deck.color("ink")
        if data["type"] == "stacked_bar":
            labels.position = XL_LABEL_POSITION.CENTER
            labels.font.color.rgb = deck.color(WHITE)
        elif not round_chart:
            labels.position = XL_LABEL_POSITION.OUTSIDE_END
    if round_chart:
        labels.show_value, labels.show_percentage, labels.show_category_name, labels.number_format = False, True, True, "0%"
        labels.font.color.rgb, labels.font.bold = deck.color("ink"), True
        labels.position = XL_LABEL_POSITION.BEST_FIT
        donut_colors = [deck.color(tint(deck, "mood", share)) for share in (0.0, 0.3, 0.5, 0.65, 0.78, 0.88)]
        for index, point in enumerate(chart.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = (deck.color("mood" if index == highlight_index(data) else "muted")
                                                if data.get("highlight") is not None else
                                                donut_colors[index % len(donut_colors)] if data["type"] == "donut" else colors[index % len(colors)])
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
            values = data["datasets"][index]["values"]
            point_index = len(values) - 1 if many else highlight_index(data, len(values) - 1)
            last = series.points[point_index]
            last.marker.style, last.marker.size = XL_MARKER_STYLE.CIRCLE, 9
            last.marker.format.fill.solid()
            last.marker.format.fill.fore_color.rgb = color
            last.marker.format.line.color.rgb = color
            label = last.data_label
            label.position = XL_LABEL_POSITION.RIGHT
            label.has_text_frame = True
            name = str(data["datasets"][index].get("label") or "") if many else ""
            label.text_frame.text = chart_value(values[point_index], data) + (f"  {name}" if name else "")
            font = label.text_frame.paragraphs[0].runs[0].font
            font.size, font.bold, font.name = Pt(13), True, deck.body_font
            font.color.rgb = color
        else:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = colors[index % len(colors)] if many else deck.color(tint(deck, "mood", 0.45))
            if not many:
                point = series.points[highlight_index(data)]
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
