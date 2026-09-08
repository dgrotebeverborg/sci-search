# Program 2: Identity and Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SURFconext-compatible identities, revocable sessions, personal/shared workspaces, project ownership, and centralized role authorization.

**Architecture:** Define identity and authorization as application-domain contracts first, backed initially by an in-memory test repository and then by Program 3 persistence. OIDC is isolated behind an adapter so local Keycloak and SURFconext use the same callback contract.

**Tech Stack:** Python dataclasses/enums, Authlib, Starlette security primitives, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-multi-user-production-platform-design.md`

## Global Constraints

- Identify a person only by normalized `(issuer, subject)`.
- Every authenticated user receives a personal workspace on first login.
- All research resources require project authorization; version 1 has no public access.
- Unauthorized and unknown project resources produce the same not-found result.

---

### Task 1: Identity and tenancy contracts

**Files:**
- Create: `sci_search/application/identity.py`
- Create: `sci_search/application/projects.py`
- Test: `tests/application/test_identity_projects.py`

**Interfaces:**
- Produces: `ExternalIdentity`, `User`, `Workspace`, `Project`, `ProjectRole`, `Membership`, `IdentityRepository`, and `ProjectRepository`.

- [x] Write a failing test proving first login creates one user, one personal workspace, and one owner membership for `(https://connect.surfconext.nl, stable-subject)`.
- [x] Run `python -m pytest tests/application/test_identity_projects.py::test_first_login_provisions_private_workspace -q`; expect import failure.
- [x] Implement immutable contracts and `provision_user(identity, profile, repositories, clock)` with normalized issuer, non-empty subject, and profile-only email.
- [x] Add a failing test proving the same email with different subjects creates different users and the same subject with changed email reuses one user.
- [x] Implement identity lookup exclusively by `(issuer, subject)` and rerun the file.
- [x] Commit with `git commit -m "feat: add federated identity and project contracts"`.

### Task 2: Central project policy

**Files:**
- Create: `sci_search/application/authorization.py`
- Test: `tests/application/test_authorization.py`

**Interfaces:**
- Produces: `Action`, `AuthorizationContext`, `ProjectPolicy.require(action, context, project_id) -> ProjectGrant`.

- [x] Write a literal role/action table test covering owner, editor, reviewer, and viewer for read, download, run management, review, membership, and delete actions.
- [x] Verify RED: `python -m pytest tests/application/test_authorization.py -q` fails because `ProjectPolicy` is absent.
- [x] Implement default-deny policy with explicit role grants and a single `ResourceNotFound` failure for absent and inaccessible projects.
- [x] Add tests proving inactive membership, deleted project, workspace mismatch, and guessed identifiers all deny without revealing existence.
- [x] Run authorization and identity tests; expect PASS.
- [x] Commit with `git commit -m "feat: enforce centralized project authorization"`.

### Task 3: Revocable server-side sessions

**Files:**
- Create: `sci_search/application/sessions.py`
- Test: `tests/application/test_sessions.py`

**Interfaces:**
- Produces: `SessionService.create`, `authenticate`, `rotate`, `revoke`, and `revoke_user` using opaque random tokens whose digests alone are persisted.

- [x] Write failing tests for token hashing, expiry, rotation invalidating the old token, explicit logout, and user-wide revocation.
- [x] Verify RED with `python -m pytest tests/application/test_sessions.py -q`.
- [x] Implement 256-bit URL-safe tokens, SHA-256 persisted digests, injected clock/random source, absolute expiry, idle expiry, and rotation.
- [x] Mutation-check by changing the expiry comparison and token digest in a temporary diff; confirm tests fail, then restore.
- [x] Run the focused suite and commit with `git commit -m "feat: add revocable opaque sessions"`.

### Task 4: OIDC adapter and callback validation

**Files:**
- Create: `sci_search/infrastructure/oidc.py`
- Create: `sci_search/api/auth.py`
- Test: `tests/infrastructure/test_oidc.py`
- Test: `tests/api/test_auth.py`

**Interfaces:**
- Produces: `OidcProvider.authorization_redirect`, `exchange_callback`, `logout_redirect`, and callback mapping to `ExternalIdentity`.

- [x] Write failing tests against a local fake discovery/JWKS server for state, nonce, PKCE, issuer, audience, signature, algorithm, issued-at, expiry, and exact redirect URI.
- [x] Verify each negative case fails for its intended missing validation before implementation.
- [x] Integrate Authlib Authorization Code flow; do not parse or verify JWT signatures manually.
- [x] Map only `iss` and `sub` into the identity key; keep names, email, affiliation, and institution as profile claims.
- [x] Add cookie tests asserting `Secure`, `HttpOnly`, `SameSite=Lax`, bounded lifetime, and rotation after callback.
- [x] Run `python -m pytest tests/infrastructure/test_oidc.py tests/api/test_auth.py -q` and commit.

### Task 5: Cross-project isolation matrix

**Files:**
- Create: `tests/security/test_project_isolation.py`

**Interfaces:**
- Consumes: every protected application use case added from Program 2 onward.
- Produces: a reusable parametrized isolation suite extended by later programs.

- [x] Define two users, two private projects, one shared workspace, and all four roles using literal fixtures.
- [x] Parametrize current operations and prove each unauthorized subject receives `ResourceNotFound` while authorized roles receive the expected grant.
- [x] Add this test module to the mandatory CI security marker.
- [x] Run the full suite and commit with `git commit -m "test: enforce project isolation matrix"`.

### Task 6: Program 2 verification

- [x] Run focused identity, session, OIDC, authorization, and isolation tests.
- [x] Run `python -m pytest -q`, Ruff, Pyright, and package build.
- [x] Verify logs and exceptions never include access tokens, ID tokens, cookie values, or OIDC client secrets.
- [x] Verify production configuration refuses local development login and insecure callback URLs.
