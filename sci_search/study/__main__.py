"""Start the local study-plan page: ``python -m sci_search.study [--port 8020]``."""

from __future__ import annotations

import argparse
from pathlib import Path

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sci_search.study")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--root", type=Path, default=Path("data/studies"))
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK:
        parser.error("the study page runs on this computer only (use 127.0.0.1)")

    import uvicorn

    from sci_search.configuration import load_env_file
    from sci_search.study.service import StudyService
    from sci_search.study.store import StudyStore
    from sci_search.study.web import create_app

    load_env_file(Path(".env.local"))
    service = StudyService(StudyStore(args.root))
    service.recover()
    print(f"Study plans: http://{args.host}:{args.port}")
    uvicorn.run(create_app(service), host=args.host, port=args.port, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
