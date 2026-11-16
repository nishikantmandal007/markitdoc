import uuid
from pathlib import Path

from markitdoc.errors import MarkitDocError
from markitdoc.render import render


# the old generate_document call shape: a path string, or None when the input is rejected
def generate_document(markdown, output_format, filename_stem=None, output_dir=None, template="default", user_email=None):
    output = Path(output_dir or ".") / f"{filename_stem or uuid.uuid4()}.{output_format}"
    try:
        return str(render(markdown, output_format, output, template=template, author=user_email or ""))
    except MarkitDocError:
        return None
