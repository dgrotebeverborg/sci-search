"""Download the explicitly curated open-access iron-air source list."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "corpora" / "iron_air_real" / "sources.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    destination = args.sources.parent / "papers"
    destination.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.sources.read_text(encoding="utf-8"))
    failures: list[str] = []
    for source in payload["sources"]:
        target = destination / source["filename"]
        if target.exists() and not args.force:
            print(f"keep {target.name} ({_sha256(target)[:12]})")
            continue
        request = urllib.request.Request(
            source["url"],
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Sci-Search/0.1; scientific corpus acquisition)",
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
                "Referer": source.get("source_url", source["url"]),
            },
        )
        print(f"fetch {source['id']} from {source['url']}")
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                content_type = response.headers.get_content_type()
                data = response.read()
        except Exception as exc:
            failures.append(f"{source['id']}: {exc}")
            print(f"skip {source['id']}: {exc}")
            continue
        expected = source.get("format", "pdf")
        if expected == "pdf":
            valid = data.startswith(b"%PDF")
        else:
            xml_start = data.lstrip().lstrip(b"\xef\xbb\xbf").lstrip()
            valid = xml_start.startswith((b"<?xml", b"<!DOCTYPE article", b"<article"))
        if not valid:
            failures.append(f"{source['id']}: returned {content_type}, not {expected}")
            print(f"skip {source['id']}: returned {content_type}, not {expected}")
            continue
        target.write_bytes(data)
        print(f"saved {target.name} ({len(data)} bytes, sha256 {_sha256(target)})")
    if failures:
        print(f"completed with {len(failures)} unavailable source(s)")
        for failure in failures:
            print(f"  {failure}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
