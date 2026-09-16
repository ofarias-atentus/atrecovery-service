# DESIGN.md

## Project Overview

Atrecovery Service is an async FastAPI application for retrieving, maintaining,
and categorizing **routines**. Use the term "routine" everywhere; do not
introduce "script" terminology. The service dispatches and records routine
usage through external processors. It does not execute routines.

## Setup And Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.db.seed
uvicorn app.main:app --reload
```

- Set a strong `JWT_SECRET` in production. The seed creates development-only
  `admin/admin123` and `operator/operator123` users.
- Run the test suite with `pytest -q`.
- Run linting with `ruff check .`.
- The service is available at `/health`; OpenAPI docs are at `/docs`; the admin
  is at `/admin`.

## Repository Layout

- `app/main.py`: application factory, middleware, lifecycle, and router setup.
- `app/api/v1/`: async REST routers, grouped by domain.
- `app/models/`: SQLAlchemy ORM models.
- `app/schemas/`: Pydantic request and response models.
- `app/services/`: domain logic for authorization, validation, activity,
  routine usage, and bulk resource import (`resource_import.py`).
- `app/core/`: settings, dependencies, security, logging, and time helpers.
- `app/db/`: declarative base, async session lifecycle, and idempotent seed.
- `app/admin/`: sqladmin configuration and access controls.
- `tests/`: async API tests and fixtures.
- `docs/`: tutorial and database ER documentation.

## Implementation Rules

- Target Python 3.11+ and keep I/O paths async. Use `async def`,
  `AsyncSession`, and FastAPI dependency injection through `Depends`.
- Obtain database sessions through `app.db.session.get_db`; do not create
  ad-hoc engines or sessions in routers.
- Keep domain changes aligned across model, schema, service, router, seed, and
  tests. Use separate Create, Update, and Read schemas and explicit
  `response_model` declarations.
- Preserve list pagination with `limit` and `offset`; `limit` must not exceed 100.
- Validate routine content, resource data, and resource metadata against their
  configured JSON schemas before persistence.
- Route bulk resource imports through `app/services/resource_import.py` so the
  CSV API, JSON API, and admin UI share validation. Imports are atomic:
  validate every row first, upsert by `Resource.identifier == device_id`, and
  roll back the whole file on any row error.
- For imports, require active `mobile_device` and `monitor` types, normalize
  timestamps to naive UTC strings and `activo` to boolean, and store an empty
  `servidor_log` as `""`. Respect the CSV limits (2 MiB, 1000 rows) and the
  exact required header set.
- Declare static resource routes such as `/import/csv` and `/import/json`
  before `/{resource_id}` so the dynamic route does not capture them.
- Categories are admin-only by seed: reads require `category:view`, writes
  require `category:manage`. Grant these codes explicitly to non-admin roles
  when read/write access is needed.
- `ProcessorService.details` is nullable free-form JSON for dynamic info.
  Accept it on processor create, return it on reads, support it on
  `PATCH /api/v1/processors/{id}`, and keep it editable in the Admin GUI.
- Start every Admin `ModelView.column_list` with `id` (link tables without an
  `id` PK keep their composite keys instead).
- Use `is_active` soft deactivation where the existing domain keeps historical
  records, rather than deleting referenced data.
- Use `app.core.time.utcnow_naive()` for persisted/domain timestamps. JWT
  claims are the exception and use aware UTC timestamps.
- `Base.metadata.create_all()` is the current schema lifecycle. No migration
  framework is configured, so assess local database compatibility carefully
  when modifying models.

## Security And Authorization

- RBAC and object-level grants are deny-by-default. Preserve both the coarse
  permission check and the applicable routine/resource grant check.
- Do not weaken admin-only, processor-token, or read-only audit-log controls.
  Bulk resource import is admin-only: REST endpoints must use `require_admin()`,
  and the `/admin/resource-import` view relies on the existing `AdminAuth`
  session guard.
- Never return or log password hashes, raw processor tokens, JWT secrets, or
  other credentials. Processor tokens are shown once, stored hashed, and
  compared in constant time.
- Preserve routine usage and beacon history when changing catalog or access
  behavior.

## Testing And Documentation

- Add or update async API tests for behavior changes. Reuse the `client`
  fixture in `tests/conftest.py`; it provisions a temporary SQLite database
  and must never touch `data/app.db`.
- Run `pytest -q` and `ruff check .` before completing a change when the
  relevant tooling is available.
- Update `docs/ER.md` for model or relationship changes. Update
  `docs/TUTORIAL.md` for user-visible API or workflow changes.
