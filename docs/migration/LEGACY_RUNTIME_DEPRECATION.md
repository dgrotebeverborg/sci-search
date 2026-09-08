# Legacy runtime retirement

Sci-Search's pre-FastAPI local web server was removed in the production-platform release. The
retired components were the `http.server` request handler, its embedded `RESEARCHER_UI` HTML
string, the `--legacy-local-web` CLI selector, and the daemon-thread `ResearchRunManager.start`
method.

The supported `serve` command now always runs FastAPI. `--unsafe-development` remains available
only on a loopback address for explicit local authentication; production configuration rejects it.

The following compatibility surfaces remain supported for this release:

- local corpus `compare`, `export`, `evaluate`, and `investigate` commands;
- synchronous `research-online` execution and its versioned JSON artifact;
- read-only SQLite inventory and import commands for retained legacy data;
- existing evidence, graph, cited-review, and download artifact formats.

No production application or worker imports the SQLite scientific-memory runtime. Retained source
data is not removed by this code change and remains subject to the rollback window and explicit
owner approval in `CUTOVER.md`.
