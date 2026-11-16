import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from markitdoc.errors import MarkitDocError
from markitdoc.guide.contract import guide
from markitdoc.models.checks import check_document
from markitdoc.options import Options
from markitdoc.rendering import FORMATS, render


# command line: markitdoc render in.md -o out.pdf, markitdoc guide pptx, or markitdoc check in.md
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
    check_command = commands.add_parser("check", help="report problems in a markdown file without rendering it")
    check_command.add_argument("source", type=Path, help="markdown file")
    check_command.add_argument("--json", action="store_true", help="print the findings as JSON")
    options = parser.parse_args(arguments)
    try:
        if options.command == "guide":
            print(guide(options.format))
            return 0
        if options.command == "check":
            findings = check_document(options.source.read_text(encoding="utf-8"))
            lines = [f"line {finding.line}: {finding.severity}: {finding.message}" + (f" ({finding.fix})" if finding.fix else "")
                     for finding in findings]
            if options.json:
                print(json.dumps([asdict(finding) for finding in findings], indent=2))
            elif lines:
                print("\n".join(lines))
            return int(any(finding.severity == "error" for finding in findings))
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
