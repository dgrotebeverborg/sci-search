# FastAPI web cutover

`sci-search serve` runs the FastAPI service and modular researcher interface. The evidence, graph,
report, comparison, evaluation, and synchronous online-research CLI commands retain their artifact
contracts. The legacy local server has been removed.

## Local workspace preview

After installing the project (`uv sync --frozen --extra dev --python 3.11`), run:

```bash
uv run sci-search --corpus fixtures/iron_air_pilot serve --unsafe-development \
  --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` and choose **Continue with development account**. This mode provides a
temporary personal workspace where you can create and switch projects. It displays a preview banner,
loses state when the server stops, and disables **Start review**. Authenticated API attempts to start a
run return HTTP 503. The corpus path supplies the initial project name; it does not populate a live
research service.

Nonproduction startup requires the explicit `--unsafe-development` flag. Development authentication
cannot bind to a non-loopback host, and production configuration rejects it at application startup.
For real local research, use `research-online` or `investigate` and retain their file exports; see the
[README examples](../../README.md).

## Production web research

Production startup requires `SCI_SEARCH_ENVIRONMENT=production`, PostgreSQL, Redis, S3-compatible
storage, Dramatiq workers, and institutional OIDC configuration. Session and service credentials,
HTTPS origins and callbacks, and discovery-provider credentials must be supplied through the
production configuration. The web service stores durable state and dispatches research to workers.

Use the settings and secret-file declarations in [compose.yml](../../compose.yml) and follow the
[deployment runbook](../runbooks/DEPLOYMENT.md) for backup, migration, readiness, and worker startup.
The local preview flag is not part of this deployment. For legacy data and retained CLI commands,
see the [runtime retirement notice](../migration/LEGACY_RUNTIME_DEPRECATION.md).

## Versioned route changes

The previous unversioned local endpoints have been removed. The FastAPI interface uses
project-scoped version 1 routes:

| Capability | FastAPI route |
| --- | --- |
| Session and CSRF bootstrap | `GET /api/v1/session` |
| Workspaces and projects | `GET /api/v1/workspaces`, `/api/v1/projects` |
| Start and inspect research | `/api/v1/projects/{project_id}/runs` |
| Original full text | `/api/v1/projects/{project_id}/documents/{document_id}/content` |
| Evidence and review | `/api/v1/projects/{project_id}/evidence` |
| Validation | `/api/v1/projects/{project_id}/validation` |
| Complete downloads | `/api/v1/projects/{project_id}/exports` |

All protected routes use server-side sessions and project authorization. State changes require the
session-bound CSRF token returned by the session bootstrap route. Unknown and unauthorized project
resources deliberately return the same response.
