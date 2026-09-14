# Future Improvements

Candidate follow-ups for the Template Management PoC, roughly ordered by
value/effort. Nothing here is required for the Stage 8 acceptance.

## Security & hardening

- **Rotate demo/dev secrets** — `JWT_SECRET` default and `SEED_PROCESSOR_TOKEN`
  patterns are dev-only. Fail startup when `ENV=prod` and defaults are unchanged.
- **Rate limiting** — throttle `/auth/token`, `/beacons` (token auth, no JWT)
  and `/usages` (429 paths exist, but no per-IP throttling yet).
- **Refresh-token rotation + reuse detection** — current refresh flow reuses the
  `jti` family naively; store token family and reject replays.
- **Audit sensitive reads** — log access to `/admin/*` and grant reads,
  not just mutations.
- **Processor token scopes per endpoint** — `beacon:report` is the only scope;
  add e.g. `usage:read` if processors ever need status polling.

## Data & migrations

- **Alembic migrations** — `init_db` (`create_all`) is fine for PoC, but any
  real deployment needs versioned migrations before the next schema change.
- **Move off SQLite** — Postgres + asyncpg for concurrency; WAL mode is already
  assumed but a single file won't scale past one replica.
- **Soft-delete consistency** — templates/resources deactivate, but categories,
  modes and definitions hard-delete. Pick one convention (and decide what
  historical rows must keep working).
- **DB-level uniqueness for grants** — duplicates are rejected in code (409);
  add partial/unique constraints (nullable `resource_id`/`group_id` complicates
  this on some backends — evaluate per Postgres).

## API & domain

- **Usage status state machine** — enforce legal transitions
  (`pending → dispatched → running → done|failed`) instead of last-beacon-wins.
- **Scheduler worker** — `scheduler` usages with a `cron` expression are stored
  but nothing dispatches them when due (external systems own execution; a local
  worker would contradict that). If ever needed: outbox/worker (APScheduler, arq,
  or Celery) + a `due` listing.
- **Voucher reconciliation** — `external_dispatch_id` state is local-only
  (stub). Implement the remote state check against the dispatching system.
- **Pagination metadata** — return `{items, total, limit, offset}` envelopes
  instead of bare lists for large collections.
- **Idempotency keys on POST /usages** — safe retries for flaky networks
  (voucher double-dispatch is the sharp edge).
- **Grant negative rules / expiry** — time-boxed grants (`valid_until`) and
  explicit denies for break-glass revocation.

## Admin & ops

- **Admin audit of admin actions** — admin-panel mutations bypass
  `log_activity` (separate sync session). Bridge them into `activity_logs`.
- **Structured JSON logging + correlation** — `X-Request-ID` exists; emit JSON
  logs and propagate the ID into activity `meta` for traceability.
- **Health/readiness split** — `/health` (liveness) vs `/ready` (DB + migrations
  check) for orchestrators.
- **Metrics endpoint** — counters for fetch/usage/beacon/grant events
  (Prometheus), reused by autoscaling and alerting.

## Testing & DX

- **Concurrency tests** — parallel usage creation against a low limit to prove
  no overshoot (needs row-level locking on Postgres; SQLite serializes).
- **Contract tests for the demo** — run `demo/demo.py` in CI against a fresh
  container instead of manually.
- **Seed profiles** — `--profile demo|minimal|load` instead of one fixed seed;
  load profile with a Faker-generated fleet for realistic limits testing.
- **Type + lint gate in CI** — add `mypy --strict` (or at least `--ignore-missing-imports`
  off) alongside the existing ruff + pytest gate.
