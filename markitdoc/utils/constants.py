# Constants shared by more than one module; a constant only one module uses stays in that module.
import os
from pathlib import Path

# ── Bundled fonts, icons, vendor scripts and themes ──
ASSETS_FOLDER = Path(__file__).parent.parent / "assets"

# ── Downloaded photos and rendered diagrams, reused across runs ──
CACHE_FOLDER = Path(os.environ.get("MARKITDOC_CACHE") or Path.home() / ".cache" / "markitdoc")

# ── Metadata stamped on every PowerPoint and Word file ──
PLATFORM_CREATOR = "MarkitDoc"
PLATFORM_KEYWORDS = "markitdoc,generated"
