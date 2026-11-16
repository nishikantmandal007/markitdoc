import io
import re
import zipfile
from pathlib import Path

steady_dates = re.compile(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)")


# saves the presentation with stable package metadata
def save_presentation(presentation, output_path: Path):
    buffer = io.BytesIO()
    presentation.save(buffer)
    output_path.write_bytes(steady_zip(buffer.getvalue()))


# writes ZIP entries with stable timestamps and attributes
def steady_zip(content):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in sorted(source.infolist(), key=lambda item: item.filename) if content[:2] == b"PK" and is_workbook(source) else source.infolist():
            data = source.read(info.filename)
            if info.filename.endswith(".xlsx"):
                data = steady_zip(data)
            elif info.filename == "docProps/core.xml" and is_workbook(source):
                data = steady_dates.sub(rb"\g<1>2000-01-01T00:00:00Z\g<2>", data)
            entry = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type, entry.external_attr = zipfile.ZIP_DEFLATED, info.external_attr
            target.writestr(entry, data)
    return output.getvalue()


# checks whether a ZIP package contains an Excel workbook
def is_workbook(archive):
    return "xl/workbook.xml" in archive.namelist()
