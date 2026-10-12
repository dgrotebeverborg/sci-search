"""Execute, seal and replay the exact Python calculation used for publication."""

import copy
import json
from pathlib import Path

from sci_search.data_research.execution import digest, run_python

ENGINES = (
    "tabular.py",
    "packages.py",
    "preparation.py",
    "spreadsheets.py",
    "statistical_tables.py",
    "jsonstat.py",
    "daily.py",
    "wildfire.py",
    "python_rows.py",
)
DOWNLOAD = '''"""Optional network step. Never overwrites the retained source."""
import argparse, hashlib, json
from pathlib import Path
from retrieval import fetch_public
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True, type=Path)
args=parser.parse_args()
source=json.loads(Path(__file__).with_name("source-metadata.json").read_text())
body, content_type, url=fetch_public(source["url"])
with args.output.open("xb") as stream: stream.write(body)
checksum=hashlib.sha256(body).hexdigest()
print(json.dumps({"url":url,"content_type":content_type,"sha256":checksum,"matches_retained_source":checksum==source["sha256"]},indent=2))
if checksum!=source["sha256"]: raise SystemExit("Source has changed; retained data was not modified")
'''
CALCULATE = """import json, hashlib
from pathlib import Path
root=Path("/input")
result=json.loads((root/"plan.json").read_text())
source=(root/result["source"].get("artifact", "source.xlsx")).read_bytes()
if hashlib.sha256(source).hexdigest()!=result["source"]["sha256"]:
    raise ValueError("Source hash mismatch")
if result.get("python_extraction"):
    from python_rows import analyse_observations
    calculated=analyse_observations(json.loads((root/"observations.json").read_text()),result["scope"])
    result.update(series=calculated["series"], components=calculated["components"])
elif result.get("kind")=="tabular":
    from tabular import analyse_csv
    from packages import prepare_table, attach_provenance
    from preparation import transform_table
    table, prepared = (source, {})
    if result.get("preparation"):
        table, prepared=prepare_table(source,result["preparation"].get("selection"))
    components=[]
    for component in result.get("components", [result]):
        data, preparation=table, prepared
        for plan in component.get("transformations", []):
            data, preparation=transform_table(data,preparation,plan)
        calculated=analyse_csv(data,component["mapping"],component["scope"])
        if preparation: attach_provenance(calculated,preparation)
        components.append({**component, "series":calculated["series"]})
    result["series"]=[series for component in components for series in component["series"]]
    if "components" in result: result["components"]=components
else:
    from wildfire import parse_workbook, analyse
    calculated=analyse(parse_workbook(source),countries=result["requested_countries"],start=result["scope"]["start_year"],end=result["scope"]["end_year"])
    result.update(calculated)
Path("/output/result.json").write_text(json.dumps(result, allow_nan=False))
"""

REPLAY = '''"""Replay retained code offline in the same isolated Python runner."""
import json, tempfile
from pathlib import Path
from execution import run_python, digest
root=Path(__file__).resolve().parent
folders=[root] if (root/"calculation").exists() else sorted(root.glob("source-*"))
published_root=json.loads((root/"analysis.json").read_text())
if not (root/"calculation").exists():
    retained=[]
    for folder in folders:
        saved=folder/"analysis.json"
        if saved.exists():
            value=json.loads(saved.read_text())
            if value.get("execution",{}).get("status")=="verified": retained.append(value)
    expected=published_root["analyses"]
    if len(retained)!=len(expected) or any(item not in retained for item in expected):
        raise ValueError("Published analysis differs from retained source results, or a source is missing")
for folder in folders:
    saved=folder/"analysis.json"
    if not saved.exists(): continue
    result=json.loads(saved.read_text())
    if result.get("execution",{}).get("status")!="verified": continue
    for name, expected in result["execution"]["artifacts"].items():
        path=folder/name
        if path.is_symlink() or digest(path.read_bytes())!=expected:
            raise ValueError("Artifact hash mismatch: "+name)
    with tempfile.TemporaryDirectory() as scratch:
        scratch=Path(scratch)
        if result.get("python_extraction"):
            script=folder/result["python_extraction"]["script"]
            attempt=script.parent
            inputs={p.name:p.read_bytes() for p in (attempt/"input").iterdir()}
            run=run_python(script.read_text(),inputs,scratch/"extract")
            if run["status"]!="succeeded": raise ValueError(run.get("error"))
            actual=json.loads((scratch/"extract/output/observations.json").read_text())
            expected=json.loads((folder/"observations.json").read_text())
            if actual!=expected: raise ValueError("Extraction differs from published observations")
        attempt=folder/"calculation"
        inputs={p.name:p.read_bytes() for p in (attempt/"input").iterdir()}
        run=run_python((attempt/"script.py").read_text(),inputs,scratch/"calculate")
        if run["status"]!="succeeded": raise ValueError(run.get("error"))
        actual=json.loads((scratch/"calculate/output/result.json").read_text())
        expected=json.loads((attempt/"output/result.json").read_text())
        if actual!=expected: raise ValueError("Calculation differs from published result")
        published={k:v for k,v in result.items() if k!="execution"}
        if actual!=published: raise ValueError("Published result differs from executed calculation")
        if folder==root:
            (root/"reproduced").mkdir(exist_ok=True)
            (root/"reproduced/analysis.json").write_text(json.dumps(actual,indent=2))
    print("Verified",folder.name)
'''


def execute_analysis(analysis, folder, *, check_cancelled=lambda: None):
    folder = Path(folder)
    analysis = copy.deepcopy(analysis)
    source_name = analysis["source"].get("artifact", "source.xlsx")
    if Path(source_name).name != source_name:
        raise ValueError("Invalid source artifact name")
    source = (folder / source_name).read_bytes()
    if digest(source) != analysis["source"]["sha256"]:
        raise ValueError("Source hash mismatch")
    (folder / "source-metadata.json").write_text(json.dumps(analysis["source"], indent=2))
    (folder / "download_source.py").write_text(DOWNLOAD)
    (folder / "retrieval.py").write_bytes(Path(__file__).with_name("retrieval.py").read_bytes())
    inputs = {source_name: source, "plan.json": json.dumps(analysis).encode()}
    inputs.update({name: Path(__file__).with_name(name).read_bytes() for name in ENGINES})
    if analysis.get("python_extraction"):
        inputs["observations.json"] = (folder / "observations.json").read_bytes()
    record = run_python(CALCULATE, inputs, folder / "calculation", check_cancelled=check_cancelled)
    if record["status"] != "succeeded":
        raise ValueError(record.get("error", "Python calculation failed"))
    actual = json.loads((folder / "calculation/output/result.json").read_text())
    if actual != analysis:
        raise ValueError("Executed Python calculations differ from the proposed result")
    files = [
        folder / name
        for name in (source_name, "source-metadata.json", "download_source.py", "retrieval.py")
    ]
    files.extend(p for p in (folder / "calculation").rglob("*") if p.is_file())
    files.extend(folder.glob("semantic-review*.json"))
    if (folder / "documentation.bin").exists():
        files.append(folder / "documentation.bin")
    evidence = folder / "python/evidence-documents.json"
    if evidence.exists():
        files.append(evidence)
    if analysis.get("python_extraction"):
        files.append(folder / "observations.json")
        attempt = (folder / analysis["python_extraction"]["script"]).parent
        files.extend(p for p in attempt.rglob("*") if p.is_file())
    actual["execution"] = {
        "status": "verified",
        "script": "calculation/script.py",
        "script_sha256": record["script_sha256"],
        "runtime": record["runtime"],
        "checks": ["Original source hash", "Executed calculation equals published values"],
        "artifacts": {str(p.relative_to(folder)): digest(p.read_bytes()) for p in files},
    }
    return actual


def write_replay(directory):
    directory = Path(directory)
    (directory / "reproduce.py").write_text(REPLAY)
    (directory / "execution.py").write_bytes(Path(__file__).with_name("execution.py").read_bytes())
    from sci_search.data_research.execution import runtime

    environment = runtime()
    (directory / "environment.json").write_text(json.dumps(environment, indent=2))
    (directory / "requirements.txt").write_text(
        "\n".join(
            name + "==" + version
            for name, version in environment["dependencies"].items()
            if name.lower().replace("_", "-") != "sci-search"
        )
        + "\n"
    )
