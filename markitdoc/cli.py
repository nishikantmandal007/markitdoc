import argparse
import sys
from pathlib import Path

from markitdoc.errors import MarkitDocError
from markitdoc.guide.contract import guide
from markitdoc.options import Options
from markitdoc.rendering import FORMATS, render


# command line: markitdoc render in.md -o out.pdf, or markitdoc guide pptx
def main(arguments=None):
    parser = argparse.ArgumentParser(prog="markitdoc", description="Markdown to PDF, PowerPoint and Word.")
    commands = parser.add_subparsers(dest="command", required=True)
    render_command = commands.add_parser("render", help="render a markdown file")
    render_command.add_argument("source", type=Path, help="markdown file")
    render_command.add_argument("-o", "--output", type=Path, required=True, help="output file; its suffix picks the format")
    render_command.add_argument("--template", default="default", help="theme or registered brand name")
    render_command.add_argument("--author", default="", help="author stamped on PowerPoint and Word files")
    render_command.add_argument("--gotenberg", help="Gotenberg server URL for diagrams")
    render_command.add_argument("--cache", type=Path, help="cache folder for images and diagrams")
    guide_command = commands.add_parser("guide", help="print the markdown guide for a format")
    guide_command.add_argument("format", nargs="?", default="pdf", choices=FORMATS)
    options = parser.parse_args(arguments)
    try:
        if options.command == "guide":
            print(guide(options.format))
            return 0
        path = render(options.source.read_text(encoding="utf-8"), options.output.suffix.lstrip(".").lower(), options.output,
                      template=options.template, author=options.author,
                      options=Options(gotenberg_url=options.gotenberg, cache_folder=options.cache))
        print(path)
        return 0
    except (MarkitDocError, OSError) as error:
        print(f"markitdoc: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
