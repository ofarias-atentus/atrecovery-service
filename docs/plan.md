# POC Plan — FastAPI Routine Management System

> Working directory: `/Users/orlando/personal/python/recovery-poc-three` (do not access outside this folder)
> Status: PLAN ONLY — no code implemented yet. Each Stage below is independently buildable by a separate agent.

## 1. Objective

Build a PoC FastAPI application to **retrieve, maintain, and categorize Routines** (mandatory rename: `script` → `routine` everywhere, including DB tables/columns, APIs, UI; only `type/category` data and `python` type remain as-is).

**Out of scope:** actual script execution. The system only dispatches usage requests and records results via external processor services.

Core capabilities:

1. Roles: `admin`, `operator` (extensible to more roles) with RBAC.
2. Routine catalog with categories (start: `python`, plus e.g. `json`; extensible).
3. Resources (e.g. mobile device `{"udid":"ZY323S5GHW","nombre":"Moto G6 3","plataforma":"android","version_plataforma":"8.0.0","descripcion":"random device"}`) with interchangeable metadata.
4. Permission system for operators over routines/resources (RBAC + object-level grants + resource groups).
5. Resource groups auto-assignable to users/roles.
6. Usage layer: `scheduler`, `voucher` (dispatch ID + state check), `direct` execution, extensible to more modes. Relay on other services.
7. Beacon results layer: external processors report results per usage.
8. Processor service authentication via simple token approach.
9. Usage limits (one routine → many limits), each usage mapped to beacon results.
10. Activity tracking at log level (e.g. most-used routine, last fetch time — generic, extensible).
11. Statistics engine: admin-configurable, extensible, including `unknown/external` sources with required params + permission gating.
12. Admin UI like Django Admin: CRUD every table, read-only for logs.
13. Login via OAuth2 + extensible custom/business auth.
14. API docs, async approach, request + user-action logging.
15. DB architecture diagram (text/mermaid).
16. Demo to test end-to-end.

Stack (fixed):

- **Framework:** FastAPI (async)
- **Database:** SQLAlchemy 2.0 ORM async + SQLite PoC via `aiosqlite`
- **Auth:** OAuth2 password flow + JWT + `passlib[bcrypt]`
- **Schemas:** Pydantic v2
- **Admin:** `sqladmin` (Django-Admin-like CRUD over SQLAlchemy) + minimal custom Jinja2 for read-only logs. Fallback if needed: hand-rolled Jinja2 CRUD.
- **Docs:** OpenAPI `/docs`, `/redoc`
- **Logging:** middleware + stdlib logging + DB activity log
- **Python:** 3.11+, `pytest`, `pytest-asyncio`, `httpx`

---

## 2. Target Project Layout (to be created in later stages)

```
./
  plan.md
  README.md
  pyproject.toml / requirements.txt
  .env.example
  app/
    main.py              # app factory, middleware, routers, /admin mount
    core/
      config.py          # pydantic-settings
      security.py        # bcrypt, JWT create/verify, token hashing (sha256)
      deps.py            # get_db, get_current_user, require_permission, require_object_access, get_processor
      logging.py         # request-id middleware + logger setup
      auth_providers.py  # AuthProvider ABC: LocalProvider, BusinessSSOProvider stub, OAuth2 stub
    db/
      base.py            # DeclarativeBase, mixins (id, created_at, updated_at, is_active)
      session.py         # async engine/session, get_db, init_db
      seed.py            # demo seed (admin/operator, categories, routine, resource, group, etc.)
    models/
      __init__.py
      identity.py        # users, roles, permissions, user_roles, role_permissions, auth_identities
      catalog.py         # routine_categories, routines
      resources.py       # resources, metadata_definitions, resource_metadata, resource_groups, members, assignments
      grants.py          # routine_grants, resource_grants
      usage.py           # execution_modes, routine_usages, usage_limits
      beacons.py         # processor_services, execution_results
      tracking.py        # activity_logs
      stats.py           # statistics_definitions
    schemas/             # Pydantic v2 per domain (Create/Update/Read)
    repositories/        # thin CRUD (optional for PoC, keep light)
    services/
      rbac.py            # permission + grant evaluation, group resolution
      activity.py        # append-only ActivityLogger
      usage_svc.py       # limit enforcement, voucher dispatch-id handling
      stats_svc.py       # internal aggregations + external fetch
    api/v1/
      auth.py, users.py, roles.py, categories.py, routines.py,
      resources.py, metadata.py, groups.py, grants.py,
      usages.py, beacons.py, processors.py, logs.py, stats.py
    admin/
      views.py           # sqladmin ModelViews + access guard
    routines/           # custom Jinja pages (login help, dashboard stub)
    static/
  tests/
    conftest.py
    test_auth_rbac.py, test_catalog.py, test_grants.py, test_usages.py,
    test_beacons.py, test_logs.py, test_stats.py
  demo/
    demo.py              # end-to-end script using httpx
    seed_demo.sh (optional)
  docs/
    ER.md                # mermaid + text diagram
```

Conventions: async everywhere, DI via `Depends`, pagination `?limit&offset`, soft `is_active`, `created_at/updated_at`, never leak `hashed_password` / raw tokens. All datetimes UTC: naive UTC for DB/domain (`app/core/time.utcnow_naive`), aware UTC for JWT claims only.

---

## 3. Database Architecture

### 3.1 Text ER Diagram

```
[roles] 1---* [role_permissions] *---1 [permissions]
[users] 1---* [user_roles] *---1 [roles]
[users] 1---* [auth_identities] (provider, provider_sub)

[routine_categories] 1---* [routines] *---1 [users(created_by)]

[resources] 1---* [resource_metadata] *---1 [metadata_definitions]
[resources] 1---* [resource_group_members] *---1 [resource_groups]
[resource_groups] 1---* [group_assignments] -> principal(user|role)

[routines] 1---* [routine_grants] -> principal(user|role|group)
[resources|groups] 1---* [resource_grants] -> principal(user|role|group)

[execution_modes] 1---* [routine_usages]
[routines] 1---* [routine_usages] *---1 [users(requested_by)]
[resources] 1---* [routine_usages] (nullable)
[routines] 1---* [usage_limits]
[routine_usages] 1---* [execution_results]
[processor_services] 1---* [execution_results]

[users] 1---* [activity_logs]
[permissions] 1---* [statistics_definitions(required_permission_code)]
```

### 3.2 Table Definitions

**Identity / RBAC**

- `roles(id PK, name UNIQUE, description)` — seed: `admin`, `operator`.
- `permissions(id PK, code UNIQUE e.g. routine:view|routine:use|resource:use|stats:view|admin:manage, description)`.
- `role_permissions(role_id FK→roles, permission_id FK→permissions, PK both)`.
- `users(id PK, username UNIQUE, email UNIQUE, hashed_password, is_active BOOL, is_superuser BOOL, created_at)`.
- `user_roles(user_id FK, role_id FK, PK both)`.
- `auth_identities(id PK, user_id FK→users, provider e.g. local|google|business_sso, provider_sub UNIQUE, extra JSON)` — enables OAuth + business custom auth without changing `users`.

**Catalog (Routines)**

- `routine_categories(id PK, name UNIQUE e.g. python|json, description, schema_hint JSON, is_active)`.
- `routines(id PK, name, version default 1, category_id FK→categories, content TEXT, input_schema JSON nullable, is_active BOOL, created_by FK→users, created_at, updated_at)` — UNIQUE(name, version). NOTE: no `script` naming anywhere.

**Resources + Metadata + Groups**

- `resources(id PK, name, identifier UNIQUE e.g. UDID ZY323S5GHW, platform, platform_version, description, extra JSON, is_active BOOL)`.
  - Example: `identifier=ZY323S5GHW, name=Moto G6 3, platform=android, platform_version=8.0.0, description=random device`.
- `metadata_definitions(id PK, key UNIQUE e.g. monitor|nodo|nombre|descripcion|hostname|host|servidor_log, value_type e.g. str|int|json, description)` — the reusable metadata structure table.
- `resource_metadata(resource_id FK, metadata_def_id FK, value JSON/TEXT, PK both)` — interchangeable dicts attached to any resource.
- `resource_groups(id PK, name UNIQUE, description)`.
- `resource_group_members(group_id FK, resource_id FK, PK both)`.
- `group_assignments(id PK, group_id FK→groups, principal_type ENUM user|role, principal_id INT, created_by FK→users)` — auto-assign group to one or more operators/roles.

**Fine-grained grants (object-level, complements RBAC codes)**

- `routine_grants(id PK, routine_id FK, principal_type ENUM user|role|group, principal_id INT, can_view BOOL, can_use BOOL)`.
- `resource_grants(id PK, resource_id FK nullable, group_id FK nullable (one set), principal_type, principal_id, can_view BOOL, can_use BOOL)`.
- Evaluation order in `services/rbac.py`: `is_superuser → role permission code → direct grant → group assignment + group grant`. Deny by default.

**Usage layer (execution relay, not execution)**

- `execution_modes(id PK, code UNIQUE e.g. direct|scheduler|voucher, description)` — adding a row + small service branch adds a new mode.
- `routine_usages(id PK, routine_id FK, resource_id FK nullable, requested_by FK→users, mode_id FK→modes, status ENUM pending|dispatched|running|done|failed, external_dispatch_id nullable (voucher ID from other system), schedule_at nullable, payload JSON, use_count INT default 1, created_at)`.
  - Voucher flow: `POST /usages {mode:voucher}` → store + return `external_dispatch_id` → `GET /usages/{id}/status` checks state (PoC: local state + stub for remote check).
  - Scheduler flow: store `schedule_at + payload`; actual triggering is external.
  - Direct flow: just a record with `status=dispatched`.
- `usage_limits(id PK, routine_id FK, scope_type ENUM global|user|role|group, scope_id nullable, max_uses INT, window ENUM total|daily|monthly, is_active BOOL)` — one-to-many per routine. Checked on fetch + usage creation.

**Beacon results + processor auth**

- `processor_services(id PK, name UNIQUE, token_hash (sha256, never plaintext), scopes JSON, is_active BOOL)`.
- `execution_results/beacons(id PK, usage_id FK→routine_usages, processor_id FK→processors, status e.g. ok|error|partial, result JSON, received_at)` — many beacons per usage (usage ↔ results = one-to-many).

**Tracking**

- `activity_logs(id PK, user_id FK nullable, action e.g. routine.fetch|routine.use|beacon.received|grant.changed, entity_type, entity_id nullable, meta JSON, ip nullable, created_at)` — append-only. Admin UI read-only (list/show, no edit/delete). Powers `most used routine`, `last time user got routine`, etc. via aggregation, not hardcoded columns.

**Statistics**

- `statistics_definitions(id PK, name UNIQUE e.g. most_used_routine|last_fetch_by_user, source_type ENUM internal|external, query_config JSON, required_params JSON e.g. ["user_id"], required_permission_code FK→permissions.code, is_active BOOL)`.
  - `internal`: `query_config` names a registered resolver (aggregation over usages/logs/beacons).
  - `external/unknown`: `query_config={url, method, headers_template, mapping}` + `required_params`; server does `httpx` fetch. Operators need the linked permission to read values.

Mermaid version to be saved in `docs/ER.md` in Stage 0/8 (same entities, `erDiagram` syntax).

---

## 4. Auth, RBAC, Admin, Logging, Docs

- **Auth:** `POST /api/v1/auth/token` (OAuth2 password flow, form-data) → `{access_token, refresh_token, token_type:bearer}`; `POST /auth/refresh`. `LocalProvider` verifies bcrypt. `BusinessSSOProvider` / OAuth2 (Google) as stub interface in `core/auth_providers.py`: `authenticate(credentials) → user`, `link_identity()` — new providers added without touching routers.
- **RBAC enforcement:** `Depends(get_current_user)` → `Depends(require_permission("routine:use"))` → `require_object_access(routine_id, resource_id)` in service layer. Seed `admin:*`, `operator: routine:view/use, resource:view/use, stats:view (gated per stat)`.
- **Admin UI (`/admin`):** `sqladmin` ModelViews for all tables; `activity_logs` + `execution_results` registered as read-only (`can_create=False, can_edit=False, can_delete=False`); guard: only `is_superuser` or `admin:manage` permission. Custom Jinja dashboard stub links to `/docs`.
- **Logging:** `RequestIDMiddleware` (X-Request-ID), uvicorn + app logger to stdout (JSON-ish for PoC), `ActivityLogger.log(user, action, entity...)` called from routine fetch, usage create, beacon ingest, grant/group changes.
- **Docs:** auto OpenAPI; every router has `tags`, Pydantic examples; `GET /health`, `GET /version`.

---

## 5. API Surface (v1, async, paginated)

- `/api/v1/auth/*` — token, refresh, `/{provider}/callback` stub.
- `/api/v1/users`, `/roles`, `/permissions` — admin manage; users self-read.
- `/api/v1/categories` — CRUD (admin write).
- `/api/v1/routines` — list/get (needs `routine:view` + grant), create/update/delete (admin), `GET /{id}/fetch` (needs `routine:use`, checks limits, writes activity log, returns content).
- `/api/v1/resources`, `/metadata-definitions`, `/resources/{id}/metadata` (put/delete per key), `/resource-groups` + `/{id}/members` + `/{id}/assignments`.
- `/api/v1/grants/routines`, `/grants/resources` — admin manage.
- `/api/v1/execution-modes` — list + admin create (extensibility point).
- `/api/v1/usages` — `POST` (operator with use-grant; enforces limits), `GET` list/detail, `GET /{id}/status` (incl. voucher `external_dispatch_id` state).
- `/api/v1/processors` — admin CRUD (token shown once on create, stored hashed).
- `/api/v1/beacons` — `POST` with `X-Processor-Token` (no JWT), `GET` (JWT, permission-gated), linked to `usage_id`.
- `/api/v1/activity-logs` — `GET` admin only.
- `/api/v1/stats/definitions` — admin CRUD; `/api/v1/stats/{name}?<params>` — checks `required_permission_code` + grants, then internal resolver or external fetch.

---

## 6. Staged Implementation (handoff-ready)

> General per-stage workflow: models → schemas → service → router → tests → seed update. Do not skip. Each stage lists entry requirements, tasks, and exit criteria so a different agent can take over.

### Stage 0 — Bootstrap & Foundations

- Entry: empty folder + this plan.
- Tasks: `pyproject/requirements` (fastapi, uvicorn, sqlalchemy[asyncio], aiosqlite, pydantic v2, pydantic-settings, python-jose or pyjwt, passlib[bcrypt], python-multipart, sqladmin, jinja2, httpx, pytest...), `.env.example`, `core/config.py`, `db/base.py` + `session.py`, `core/logging.py` + middleware, `main.py` with `/health`, `/docs`, `docs/ER.md` skeleton, `tests/test_health.py`, `README.md` run instructions.
- Exit: `uvicorn app.main:app --reload` serves `/health` + `/docs`; `pytest` green.

### Stage 1 — Identity, Auth & RBAC

- Entry: Stage 0 green.
- Tasks: models+schemas `users/roles/permissions/user_roles/role_permissions/auth_identities`; `security.py` (hash/verify/JWT); `auth_providers.py` (+business stub); `deps.py get_current_user/require_permission`; routers `auth/users/roles`; seed admin/operator; tests login/refresh/forbidden.
- Exit: `admin/admin123` + `operator/operator123` login; protected route returns 401/403 correctly.

### Stage 2 — Catalog: Categories, Routines, Resources, Metadata, Groups

- Entry: Stage 1 green.
- Tasks: models+schemas+routers for `routine_categories/routines/resources/metadata_definitions/resource_metadata/resource_groups/members/assignments`; seed `python|json` categories, `hello.py` routine, `ZY323S5GHW` resource + 7 metadata keys + group `lab-phones`; tests CRUD + metadata attach/detach + group membership.
- Exit: full catalog CRUD via API; seed data present.

### Stage 3 — Access Control (Grants + Group Auto-Assign)

- Entry: Stage 2 green.
- Tasks: `routine_grants/resource_grants` models/schemas/routers; `services/rbac.py` evaluator + `require_object_access`; group→principal resolution; seed grants (operator can view/use lab group + hello routine); tests allowed/denied matrix.
- Exit: operator without grant gets 403; with grant succeeds.

### Stage 4 — Usage Layer + Limits (direct/scheduler/voucher)

- Entry: Stage 3 green.
- Tasks: `execution_modes/routine_usages/usage_limits` + `services/usage_svc.py` (limit check scopes global/user/role/group × windows total/daily/monthly); routers `execution-modes/usages` incl. `POST /usages` + `GET /{id}/status`; voucher `external_dispatch_id` handling; tests limit-exceeded, scheduler payload, voucher flow.
- Exit: limits enforced (429/403); voucher ID returned and status readable.

### Stage 5 — Beacon Results + Processor Auth

- Entry: Stage 4 green.
- Tasks: `processor_services/execution_results` + `X-Processor-Token` auth (`get_processor`, sha256 compare); `POST /beacons` (processor only) + `GET` (JWT); usage→beacons one-to-many listing; tests valid/invalid token, beacon↔usage linkage.
- Exit: external processor can report with token; operators can read per permission.

### Stage 6 — Activity Tracking (log-level)

- Entry: Stage 5 green.
- Tasks: `activity_logs` append-only model + `services/activity.py`; hook into fetch/usage/beacon/grant changes (with IP + meta JSON); `GET /activity-logs` admin-only; tests most-used + last-fetch aggregations from logs.
- Exit: every fetch/usage/beacon creates a log row; admin can list, cannot edit/delete.

### Stage 7 — Statistics Engine (internal + unknown/external)

- Entry: Stage 6 green.
- Tasks: `statistics_definitions` CRUD (admin) + `services/stats_svc.py` resolvers (`most_used_routine`, `last_fetch_by_user`, `beacon_success_rate`) + generic external fetcher (`httpx` with timeout + `required_params` validation); `GET /stats/{name}` permission-gated; tests internal + mocked external (respx/httpx mock) + forbidden without permission.
- Exit: admin can define new stat without code change (for external type); operator access gated.

### Stage 8 — Admin UI, Docs Polish & Hardening

- Entry: Stages 0–7 green.
- Tasks: mount `sqladmin` at `/admin` with auth guard; read-only views for logs/results; finalize `docs/ER.md` diagram; security pass (JWT expiry, CORS, pagination caps, input validation, token redaction).
- Exit (POC acceptance): `uvicorn` serves; `/docs` + `/admin` usable; `pytest` green.

---

## 7. Security & Best Practices (per technology)

- **FastAPI:** async defs, Depends DI, response_model, status codes (401/403/404/429), pagination caps, CORS allowlist, trusted-host/request-size ready.
- **SQLAlchemy:** 2.0 typed ORM, async session per request, parameterized queries, migrations-ready (Alembic optional for PoC — `init_db` suffices), SQLite WAL, indexes on `username, identifier, (name,version), usage(routine_id, requested_by), beacon(usage_id), logs(created_at, action)`.
- **Pydantic v2:** `BaseModel` with `ConfigDict(from_attributes=True)`, strict types, `Field(examples=...)`, separate Create/Update/Read.
- **Auth:** bcrypt cost 12, JWT `sub+exp+jti`, short access (30m) + refresh (7d), secrets from env, processor tokens random 32B shown once + sha256 stored, constant-time compare.
- **Admin:** superuser/`admin:manage` guard, read-only logs/results, audit all grant changes.
- **Logging:** no secrets in logs, request IDs, activity meta as JSON.

---

## 8. Seed Data (Stage 8)

`app/db/seed.py`:

1. Seed: roles/permissions, `admin/admin123`, `operator/operator123`, categories `python|json`, routine `hello.py` (python), resource `ZY323S5GHW` + metadata dict, group `lab-phones` assigned to `operator` role, grants, `direct|scheduler|voucher` modes, processor `lab-runner` token, stats defs.
2. Manual verification: `uvicorn app.main:app --reload`, then `/docs`, `/admin` (admin login).

---

## 9. Acceptance Criteria (POC done)

- Terminology `routine` everywhere; categories include `python` + `json`.
- RBAC + grants + groups gate routine/resource access.
- Metadata defs reusable across resources; Moto G6 example works.
- Usages support direct/scheduler/voucher (+ easy extension); limits enforced; beacons linked per usage via token auth.
- Activity logs append-only, admin read-only; stats configurable incl. external with params + permission gate.
- `/admin` CRUD all tables (read-only logs); `/docs` complete; async; request+action logging.
- Demo passes; `pytest` green.

## 10. Handoff Notes for Next Agent

- Start at the lowest incomplete Stage (check `README`/code + `pytest`).
- Respect this file: do not reintroduce `script` naming; do not implement real execution — only relay + record.
- Keep changes inside this folder.
- Update `docs/ER.md` if models change; keep seed idempotent.

---

*End of plan. Awaiting user start signal — no implementation performed in this step.*
