"""Bounded, deterministic source navigation inside the existing Python sandbox."""

import json
from pathlib import Path

from sci_search.data_research.execution import run_python

PDF_DOCUMENTATION_CODE = """import io, json
from pathlib import Path
from pypdf import PdfReader
reader = PdfReader(io.BytesIO(Path('/input/source.bin').read_bytes()))
if reader.is_encrypted or len(reader.pages) > 200:
    raise ValueError('Encrypted or excessive PDF documentation')
parts, size = [], 0
for number, page in enumerate(reader.pages, 1):
    text = page.extract_text() or ''
    size += len(text)
    if size > 200000:
        raise ValueError('PDF documentation exceeds the text limit')
    parts.append(f'[PAGE {number}]\\n{text}')
if size < 100:
    raise ValueError('PDF documentation has too little extractable text')
Path('/output/documentation.json').write_text(json.dumps({'text': '\\n\\n'.join(parts)}))
"""


def extract_documentation_pdf(body, directory, *, check_cancelled=lambda: None):
    """Read source definitions in isolation; retain every page or explicitly fail."""
    if len(body) > 10_000_000 or not body.startswith(b"%PDF-"):
        raise ValueError("Invalid or excessive PDF documentation")
    result = run_python(
        PDF_DOCUMENTATION_CODE,
        {"source.bin": body},
        directory,
        check_cancelled=check_cancelled,
    )
    if result["status"] != "succeeded":
        raise ValueError(result.get("error", "PDF documentation extraction failed"))
    return json.loads((Path(directory) / "output/documentation.json").read_text())["text"]


REQUEST_SCHEMA = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": ["kind", "offset", "limit", "name"],
    "properties": {
        "kind": {"type": "string", "enum": ["text", "pdf", "sheet", "archive"]},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        "name": {"type": "string"},
    },
}
CODE = """import io, json, itertools, zipfile
from pathlib import Path
body=Path('/input/source.bin').read_bytes()
request=json.loads(Path('/input/request.json').read_text())
kind,offset,limit,name=(request[k] for k in ('kind','offset','limit','name'))
if kind=='pdf':
    from pypdf import PdfReader
    pages=PdfReader(io.BytesIO(body)).pages
    text='\\n'.join(pages[i].extract_text()[:12000] for i in range(offset,min(offset+limit,len(pages))))
elif kind=='sheet':
    import openpyxl
    book=openpyxl.load_workbook(io.BytesIO(body),read_only=True,data_only=True)
    sheet=book[name]
    rows=list(itertools.islice(sheet.values,offset,offset+limit))
    text=json.dumps(rows,default=str,ensure_ascii=False)
elif kind=='archive':
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        info=archive.getinfo(name)
        if info.file_size>5000000: raise ValueError('Archive entry exceeds inspection limit')
        body=archive.read(info)
    text='\\n'.join(body.decode('utf-8-sig').splitlines()[offset:offset+limit])
else:
    text='\\n'.join(body.decode('utf-8-sig').splitlines()[offset:offset+limit])
Path('/output/inspection.json').write_text(json.dumps({**request,'text':text[:40000],'truncated':len(text)>40000}))
"""


def inspect_source(body, request, directory, *, check_cancelled=lambda: None):
    if (
        not isinstance(request, dict)
        or request.get("kind") not in {"text", "pdf", "sheet", "archive"}
        or type(request.get("offset")) is not int
        or not 0 <= request["offset"] <= 1000000
        or type(request.get("limit")) is not int
        or not 1 <= request["limit"] <= 200
        or not isinstance(request.get("name"), str)
        or len(request["name"]) > 1000
    ):
        raise ValueError("Invalid bounded inspection request")
    if request["kind"] == "pdf" and request["limit"] > 8:
        raise ValueError("PDF inspection is limited to eight pages")
    result = run_python(
        CODE,
        {"source.bin": body, "request.json": json.dumps(request).encode()},
        directory,
        check_cancelled=check_cancelled,
    )
    if result["status"] != "succeeded":
        raise ValueError(result.get("error", "Source inspection failed"))
    return json.loads((Path(directory) / "output/inspection.json").read_text())
