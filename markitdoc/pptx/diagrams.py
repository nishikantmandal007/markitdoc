import re
from dataclasses import dataclass

from lxml import etree
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from markitdoc.visuals.diagrams import arrow, first_line, labelled_link, readable, setting_words
from markitdoc.pptx.deck import add_rect, configure_frame, plain_text, tint, white, write_text

shape_marks = (("{{", "}}", MSO_SHAPE.HEXAGON), ("{", "}", MSO_SHAPE.DIAMOND), ("((", "))", MSO_SHAPE.OVAL), ("([", "])", MSO_SHAPE.ROUNDED_RECTANGLE),
               ("[(", ")]", MSO_SHAPE.CAN), ("[[", "]]", MSO_SHAPE.RECTANGLE), ("[", "]", MSO_SHAPE.ROUNDED_RECTANGLE),
               ("(", ")", MSO_SHAPE.ROUNDED_RECTANGLE))
node_part = re.compile(r"^\s*(\w+)\s*(.*?)\s*$")
label_sizes = (16, 15, 14, 13, 12, 11)
max_columns, max_rows, narrowest = 8, 4, 1.05


@dataclass
class Flow:
    labels: dict
    shapes: dict
    edges: list
    columns: list


def flow_graph(source):
    words = first_line(source).split()
    if words[:1] not in (["flowchart"], ["graph"]):
        return None
    labels, shapes, edges = {}, {}, []
    for raw in source.strip().splitlines()[1:]:
        line = raw.strip().rstrip(";")
        if not line or line.startswith("%%") or line.split()[0] in setting_words:
            continue
        line = labelled_link.sub(lambda match: f"{match.group(3)}|{match.group(2)}|", line)
        pieces = arrow.split(line)
        names = [named_node(part, labels, shapes) for part in pieces[::3]]
        if None in names:
            return None
        links = pieces[2::3]
        edges += [(start, end, readable(links[index] or "")) for index, (start, end) in enumerate(zip(names, names[1:]))]
    if not edges or len(labels) < 2:
        return None
    columns = ranked(list(labels), edges)
    if len(columns) > max_columns or max(len(column) for column in columns) > max_rows:
        return None
    return Flow(labels, shapes, edges, columns)


def named_node(part, labels, shapes):
    found = node_part.match(part)
    if not found:
        return None
    name, rest = found.groups()
    for opening, closing, shape in shape_marks:
        if rest.startswith(opening) and rest.endswith(closing):
            labels[name] = readable(rest[len(opening):len(rest) - len(closing)]) or name
            shapes[name] = shape
            return name
    if rest:
        return None
    labels.setdefault(name, name)
    shapes.setdefault(name, MSO_SHAPE.ROUNDED_RECTANGLE)
    return name


def ranked(names, edges):
    order, seen, forward = [], set(), []
    following = {name: [end for start, end, _ in edges if start == name] for name in names}

    def visit(name, path):
        seen.add(name)
        for end in following[name]:
            if end in path:
                continue
            forward.append((name, end))
            if end not in seen:
                visit(end, path | {end})
        order.append(name)

    starts = [name for name in names if not any(end == name for _, end, _ in edges)] or names[:1]
    for name in starts + names:
        if name not in seen:
            visit(name, {name})
    rank = {name: 0 for name in names}
    for name in reversed(order):
        for start, end in forward:
            if start == name:
                rank[end] = max(rank[end], rank[name] + 1)
    columns = [[] for _ in range(max(rank.values()) + 1)]
    for name in names:
        columns[rank[name]].append(name)
    for sweep in range(4):
        indexes = range(1, len(columns)) if sweep % 2 == 0 else range(len(columns) - 2, -1, -1)
        for index in indexes:
            neighbour = columns[index - 1] if sweep % 2 == 0 else columns[index + 1]
            position = {name: place for place, name in enumerate(neighbour)}
            links = {name: [position[other] for start, end in forward for other, this in ((start, end), (end, start))
                            if this == name and other in position] for name in columns[index]}
            current = {name: place for place, name in enumerate(columns[index])}
            columns[index].sort(key=lambda name: (sum(links[name]) / len(links[name]) if links[name] else current[name], current[name]))
    return columns


def row_centres(flow, top, height, spacing):
    forward = [(start, end) for start, end, _ in flow.edges]
    rank = {name: index for index, column in enumerate(flow.columns) for name in column}
    centre = {}
    for column in flow.columns:
        wanted = []
        for place, name in enumerate(column):
            parents = [centre[start] for start, end in forward if end == name and start in centre and rank[start] < rank[name]]
            even = top + height * (place + 0.5) / len(column)
            wanted.append(sum(parents) / len(parents) if parents and len(column) == 1 else even)
        for place in range(1, len(wanted)):
            wanted[place] = max(wanted[place], wanted[place - 1] + spacing)
        shift = max(0.0, wanted[-1] + spacing / 2 - (top + height)) if wanted else 0
        for name, value in zip(column, wanted):
            centre[name] = max(top + spacing / 2, value - shift)
    return centre


def draw_flow(deck, slide, flow, box):
    left, top, width, height = box
    count = len(flow.columns)
    gap = (0.95 if count <= 5 else 0.7) if any(label for _, _, label in flow.edges) else (0.6 if count <= 5 else 0.42)
    node_width = min(2.6, (width - gap * (count - 1)) / count)
    if node_width < narrowest:
        return False
    gap = (width - node_width * count) / max(1, count - 1) if count > 1 else 0
    decision_width = min(node_width * 1.45, node_width + gap * 0.85)

    def inner(name):
        return (decision_width * 0.5 - 0.06 if decided(flow, name) else node_width - 0.3) * 0.92

    def fits(name, size):
        text = flow.labels[name]
        return (deck.lines(text, inner(name), size, "B") <= (4 if decided(flow, name) else 3)
                and all(deck.lines(word, inner(name), size, "B") == 1 for word in text.split()))

    size = next((size for size in label_sizes if all(fits(name, size) for name in flow.labels)), None)
    if size is None:
        return False
    node_height = max(0.95, max(deck.text_height(flow.labels[name], inner(name), size, "B") for name in flow.labels if not decided(flow, name))
                      + 0.4 if any(not decided(flow, name) for name in flow.labels) else 0.95)
    decision_height = max(node_height * 1.3, max((deck.text_height(flow.labels[name], inner(name), size, "B") * 2 + 0.2
                                                   for name in flow.labels if decided(flow, name)), default=0))
    tall = max(len(column) for column in flow.columns)
    if max(node_height, decision_height) * tall + 0.4 * (tall - 1) > height:
        return False
    sources = {name for name in flow.labels if not any(end == name for _, end, _ in flow.edges)}
    sinks = {name for name in flow.labels if not any(start == name for start, _, _ in flow.edges)}
    placed = {}
    centres = row_centres(flow, top, height, max(node_height, decision_height) + 0.4)
    for column_index, column in enumerate(flow.columns):
        for name in column:
            shape_width, shape_height = (decision_width, decision_height) if decided(flow, name) else (node_width, node_height)
            x = left + column_index * (node_width + gap) + (node_width - shape_width) / 2
            y = centres[name] - shape_height / 2
            placed[name] = draw_node(deck, slide, flow, name, x, y, shape_width, shape_height, size, name in sources or name in sinks)
    rank = {name: index for index, column in enumerate(flow.columns) for name in column}
    for start, end, label in flow.edges:
        backward = rank[end] <= rank[start]
        connect(deck, slide, placed[start], placed[end], backward)
        if label:
            edge_label(deck, slide, placed[start], placed[end], label, gap, backward)
    return True


def decided(flow, name):
    return flow.shapes[name] in (MSO_SHAPE.DIAMOND, MSO_SHAPE.HEXAGON)


def draw_node(deck, slide, flow, name, x, y, width, height, size, end_point):
    kind = flow.shapes[name]
    decision = kind in (MSO_SHAPE.DIAMOND, MSO_SHAPE.HEXAGON)
    fill = "mood" if end_point and not decision else tint(deck, "mood", 0.86) if decision else "paper"
    shape = add_rect(deck, slide, x, y, width, height, fill, "Flow node", kind)
    if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        shape.adjustments[0] = 0.18
    shape.line.color.rgb = deck.color("mood")
    shape.line.width = Pt(1.25)
    frame = shape.text_frame
    configure_frame(frame, MSO_ANCHOR.MIDDLE, 0.08)
    frame.margin_left = frame.margin_right = Inches(0.15 if not decision else 0.03)
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = plain_text(flow.labels[name])
    run.font.size, run.font.bold, run.font.name = Pt(size), True, deck.body_font
    run.font.color.rgb = deck.color(white if fill == "mood" else "ink")
    return shape


def connect(deck, slide, start, end, backward):
    line = slide.shapes.add_connector(MSO_CONNECTOR.ELBOW, 0, 0, 0, 0)
    line.name = "Flow connector"
    line.begin_connect(start, 2 if backward else 3)
    line.end_connect(end, 2 if backward else 1)
    line.line.color.rgb = deck.color(tint(deck, "mood", 0.25) if not backward else tint(deck, "muted", 0.2))
    line.line.width = Pt(1.75)
    outline = line.line._get_or_add_ln()
    if backward:
        etree.SubElement(outline, qn("a:prstDash"), val="dash")
    etree.SubElement(outline, qn("a:tailEnd"), type="triangle", w="lg", len="lg")


def inches(value):
    return value / 914400


def edge_label(deck, slide, start, end, label, gap, backward):
    width = max(0.9, gap - 0.1) if not backward else 1.8
    if backward:
        x = (inches(start.left + start.width / 2) + inches(end.left + end.width / 2)) / 2 - width / 2
        y = max(inches(start.top + start.height), inches(end.top + end.height)) + 0.12
    else:
        x = inches(end.left) - gap / 2 - width / 2
        y = inches(end.top + end.height / 2) - 0.42
    write_text(deck, slide, label, x, y, width, 12, "muted", italic=True, align=PP_ALIGN.CENTER, name="Flow label")
