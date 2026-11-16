import re
from dataclasses import dataclass

page_width, page_height, margin = 210, 297, 20
content_width = page_width - 2 * margin
text_width = content_width
content_limit = page_height - 19


@dataclass(frozen=True)
class Box:
    width: float
    size: float
    lines: int
    style: str = ""
    required: bool = True
    min_lines: int = 0


@dataclass(frozen=True)
class PdfLayout:
    name: str
    boxes: dict
    items: tuple = (0, 0, ())
    variants: tuple = ("default",)
    image_ratio: float = 0
    dark_variants: tuple = ()


feature_text_width = page_width - 92 - 12 - margin
layouts = {
    "cover": PdfLayout("cover", {"kicker": Box(170, 8.5, 1, "B", False), "title": Box(content_width, 40, 3, "B"),
                                 "subtitle": Box(150, 13, 3)}, variants=("dark", "photo", "light", "split", "company"),
                       image_ratio=page_width / page_height, dark_variants=("dark", "photo")),
    "summary": PdfLayout("summary", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12.5, 4),
                                     "body": Box(text_width, 10.5, 24, min_lines=8)}, items=(2, 4, (12, 40))),
    "divider": PdfLayout("divider", {"number": Box(60, 64, 1, "B", False), "title": Box(content_width, 32, 3, "B"),
                                     "lead": Box(150, 13, 5, required=False)}, items=(0, 6, (70,)),
                         variants=("light", "dark"), dark_variants=("dark",)),
    "chapter": PdfLayout("chapter", {"number": Box(20, 30, 1, "B", False), "title": Box(content_width - 22, 21, 2, "B"),
                                     "lead": Box(content_width, 12.5, 4, required=False),
                                     "body": Box(content_width / 2 - 4, 10, 38, min_lines=12),
                                     "quote": Box(content_width - 6, 12.5, 3, "I", False)},
                         variants=("band", "plain"), image_ratio=page_width / 108),
    "figures": PdfLayout("figures", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 3, required=False),
                                     "body": Box(content_width, 10, 10, required=False)}, items=(3, 6, (10, 32, 110))),
    "keypoints": PdfLayout("keypoints", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 3, required=False)},
                           items=(3, 5, (60, 240))),
    "matrix": PdfLayout("matrix", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 3, required=False)},
                        items=(4, 4, (32, 260))),
    "quote": PdfLayout("quote", {"quote": Box(content_width - 10, 26, 6, "I"), "quote_by": Box(150, 11, 1, "B", False),
                                 "context": Box(130, 10.5, 5, required=False)},
                       variants=("light", "dark"), dark_variants=("dark",)),
    "comparison": PdfLayout("comparison", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 4, required=False),
                                           "left": Box(content_width / 2 - 13, 13, 1, "B"),
                                           "right": Box(content_width / 2 - 13, 13, 1, "B"),
                                           "takeaway": Box(content_width - 14, 11, 3, "B", False)}, items=(3, 7, (170, 170))),
    "process": PdfLayout("process", {"title": Box(content_width, 22, 2, "B"), "lead": Box(content_width, 12, 4, required=False)},
                         items=(3, 6, (34, 180)), variants=("vertical", "horizontal")),
    "timeline": PdfLayout("timeline", {"title": Box(content_width, 26, 2, "B"), "lead": Box(150, 11.5, 3, required=False)},
                          items=(3, 8, (16, 48, 160)), variants=("vertical", "horizontal", "dark"), dark_variants=("dark",)),
    "feature": PdfLayout("feature", {"title": Box(feature_text_width, 21, 3, "B"), "body": Box(feature_text_width, 10, 33, min_lines=10)},
                         items=(0, 3, (14, 40)), variants=("left", "right"), image_ratio=92 / page_height),
    "closing": PdfLayout("closing", {"quote": Box(content_width - 8, 22, 5, "I", False), "quote_by": Box(150, 10.5, 1, "B", False),
                                     "title": Box(content_width, 17, 2, "B"), "body": Box(text_width, 10.5, 22)},
                         variants=("default", "company")),
    "flow": PdfLayout("flow", {}),
}
icon_layouts = ("figures",)
trailing_headings = re.compile(r"(?:\n*^#{1,6} [^\n]*\s*)+\Z", re.M)
sectioned_layouts = ("summary", "divider", "chapter", "figures", "keypoints", "matrix", "comparison", "process", "feature", "timeline")
