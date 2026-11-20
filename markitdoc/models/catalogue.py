import re
from dataclasses import dataclass

PAGE_WIDTH, PAGE_HEIGHT, MARGIN = 210, 297, 20
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
TEXT_WIDTH = CONTENT_WIDTH
CONTENT_LIMIT = PAGE_HEIGHT - 19
COVER_SPLIT_WIDTH = 76


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


FEATURE_TEXT_WIDTH = PAGE_WIDTH - 92 - 12 - MARGIN


# the width of a feature page's side panel: wide for a photo, narrow for figures, none otherwise
def feature_panel(has_image, has_items):
    return 92 if has_image else 64 if has_items else 0


# the text width left on a feature page: one margin beside a panel, two without
def feature_text_width(panel):
    return PAGE_WIDTH - panel - 12 - MARGIN if panel else CONTENT_WIDTH


LAYOUTS = {
    "cover": PdfLayout("cover", {"kicker": Box(170, 8.5, 1, "B", False), "title": Box(CONTENT_WIDTH, 40, 3, "B"),
                                 "subtitle": Box(150, 13, 3)}, variants=("dark", "photo", "light", "split", "company"),
                       image_ratio=PAGE_WIDTH / PAGE_HEIGHT, dark_variants=("dark", "photo")),
    "summary": PdfLayout("summary", {"title": Box(CONTENT_WIDTH, 22, 2, "B"), "lead": Box(CONTENT_WIDTH, 12.5, 4),
                                     "body": Box(TEXT_WIDTH, 10.5, 24, min_lines=8)}, items=(2, 4, (12, 40))),
    "divider": PdfLayout("divider", {"number": Box(60, 64, 1, "B", False), "title": Box(CONTENT_WIDTH, 32, 3, "B"),
                                     "lead": Box(150, 13, 5, required=False)}, items=(0, 6, (70,)),
                         variants=("light", "dark"), dark_variants=("dark",)),
    "chapter": PdfLayout("chapter", {"number": Box(20, 30, 1, "B", False), "title": Box(CONTENT_WIDTH - 22, 21, 2, "B"),
                                     "lead": Box(CONTENT_WIDTH, 12.5, 4, required=False),
                                     "body": Box(CONTENT_WIDTH / 2 - 4, 10, 38, min_lines=12),
                                     "quote": Box(CONTENT_WIDTH - 6, 12.5, 3, "I", False)},
                         variants=("band", "plain"), image_ratio=PAGE_WIDTH / 108),
    "figures": PdfLayout("figures", {"title": Box(CONTENT_WIDTH, 22, 2, "B"), "lead": Box(CONTENT_WIDTH, 12, 3, required=False),
                                     "body": Box(CONTENT_WIDTH, 10, 10, required=False)}, items=(3, 6, (10, 32, 110))),
    "keypoints": PdfLayout("keypoints", {"title": Box(CONTENT_WIDTH, 22, 2, "B"), "lead": Box(CONTENT_WIDTH, 12, 3, required=False)},
                           items=(3, 5, (60, 240))),
    "matrix": PdfLayout("matrix", {"title": Box(CONTENT_WIDTH, 22, 2, "B"), "lead": Box(CONTENT_WIDTH, 12, 3, required=False)},
                        items=(4, 4, (32, 260))),
    "quote": PdfLayout("quote", {"quote": Box(CONTENT_WIDTH - 10, 26, 6, "I"), "quote_by": Box(150, 11, 1, "B", False),
                                 "context": Box(130, 10.5, 5, required=False)},
                       variants=("light", "dark"), dark_variants=("dark",)),
    "comparison": PdfLayout("comparison", {"title": Box(CONTENT_WIDTH, 22, 2, "B"), "lead": Box(CONTENT_WIDTH, 12, 4, required=False),
                                           "left": Box(CONTENT_WIDTH / 2 - 13, 13, 1, "B"),
                                           "right": Box(CONTENT_WIDTH / 2 - 13, 13, 1, "B"),
                                           "takeaway": Box(CONTENT_WIDTH - 14, 11, 3, "B", False)}, items=(3, 7, (170, 170))),
    "process": PdfLayout("process", {"title": Box(CONTENT_WIDTH, 22, 2, "B"), "lead": Box(CONTENT_WIDTH, 12, 4, required=False)},
                         items=(3, 6, (34, 180)), variants=("vertical", "horizontal")),
    "timeline": PdfLayout("timeline", {"title": Box(CONTENT_WIDTH, 26, 2, "B"), "lead": Box(150, 11.5, 3, required=False)},
                          items=(3, 8, (16, 48, 160)), variants=("vertical", "horizontal", "dark"), dark_variants=("dark",)),
    "feature": PdfLayout("feature", {"title": Box(FEATURE_TEXT_WIDTH, 21, 3, "B"), "body": Box(FEATURE_TEXT_WIDTH, 10, 33, min_lines=10)},
                         items=(0, 3, (14, 40)), variants=("left", "right"), image_ratio=92 / PAGE_HEIGHT),
    "closing": PdfLayout("closing", {"quote": Box(CONTENT_WIDTH - 8, 22, 5, "I", False), "quote_by": Box(150, 10.5, 1, "B", False),
                                     "title": Box(CONTENT_WIDTH, 17, 2, "B"), "body": Box(TEXT_WIDTH, 10.5, 22)},
                         variants=("default", "company")),
    "flow": PdfLayout("flow", {}),
}
ICON_LAYOUTS = ("figures",)
TRAILING_HEADINGS = re.compile(r"(?:\n*^#{1,6} [^\n]*\s*)+\Z", re.M)
SECTIONED_LAYOUTS = ("summary", "divider", "chapter", "figures", "keypoints", "matrix", "comparison", "process", "feature", "timeline")
