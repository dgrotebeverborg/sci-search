# Dependency refresh before main integration — 12 November 2026

The GitHub integration run
[43193271045](https://github.com/dgrotebeverborg/sci-search/actions/runs/43193271045)
passed quality, all four Python test jobs, coverage, wheel building and wheel
installation. Its final dependency audit reported known vulnerabilities in six
locked packages. The lock refresh is limited to those six packages:

| Package | Previous | Updated |
| --- | --- | --- |
| authlib | 1.7.2 | 1.9.5 |
| certifi | 2026.7.22 | 2026.10.23 |
| filelock | 3.32.4 | 4.2.10 |
| joserfc | 1.7.4 | 1.8.0 |
| msgpack | 1.2.2 | 1.2.4 |
| pypdf | 6.20.1 | 6.21.4 |

The direct dependency floors are now Authlib 1.9.1 and pypdf 6.21.4. Their existing
major-version upper bounds remain in place. The remaining four packages are
transitive dependencies recorded in `uv.lock`.

The same strict audit now reports **no known vulnerabilities**:

```sh
uv export --frozen --all-extras --no-emit-project --quiet --output-file /tmp/sci-search-audit.txt
.venv/bin/pip-audit --strict --requirement /tmp/sci-search-audit.txt
```

The updated environment passes **1,704 tests and 39 subtests**, with 24 opt-in
checks skipped (139.66 seconds). One initial full run timed out while a browser
question field remained disabled during initialization; that test passed alone
and the subsequent complete run passed without test or application changes.

The retained scientific suite has the same existing rebound adequacy disagreement:
39 passed, 7 subtests passed and one failed case (`rebound-time-comparison`, partial
expected versus adequate received). Formatting, lint and secret checks pass. A
separate review confirms exactly six versions changed, unchanged package membership
and dependency edges, and Python 3.11 compatibility.
