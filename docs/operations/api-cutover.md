# FastAPI web cutover

`sci-search serve` now starts the versioned FastAPI service and modular researcher interface on
`127.0.0.1:8000` by default. The evidence, graph, report, comparison, evaluation, and online-research
CLI commands retain their existing artifact contracts.

For a loopback-only interface smoke test, explicitly enable the temporary development identity:

```bash
sci-search --corpus fixtures/iron_air_pilot serve --unsafe-development
```

Development authentication cannot bind to a non-loopback host and production configuration rejects
it at application startup. Production identity is configured through OIDC environment settings in
the deployment layer.

The retired monolithic handler remains temporarily available for regression comparison only:

```bash
sci-search --corpus fixtures/iron_air_pilot serve \
  --legacy-local-web --unsafe-development
```

Both explicit flags are required. This compatibility handler is not a production deployment path.

## Versioned route changes

The previous unversioned local endpoints remain available only through the compatibility handler.
The FastAPI interface uses project-scoped version 1 routes:

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
