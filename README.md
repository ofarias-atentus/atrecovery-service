# Template Management PoC

FastAPI PoC to retrieve/maintain/categorize **templates** (never "scripts"). Execution is out-of-scope — see `plan.md`.

## Stage 0 — Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set a strong JWT_SECRET in prod (64-char: python3 -c "import secrets; print(secrets.token_urlsafe(64))")
python -m app.db.seed  # creates admin/admin123, operator/operator123 (dev only)
uvicorn app.main:app --reload
# health: http://127.0.0.1:8000/health | docs: /docs | login: POST /api/v1/auth/token
pytest -q
```

## Stages

See `plan.md §6`. Current: **Stage 8 done — PoC complete** (sqladmin at `/admin`
with local login guard for superuser/`admin:manage`, read-only activity-log and
beacon views, credential hashes excluded; finalized `docs/ER.md`; `demo/demo.py`
end-to-end; security pass below).

## Demo

```bash
pip install -r requirements.txt
rm -f data/app.db
SEED_PROCESSOR_TOKEN=lab-runner-demo-token python -m app.db.seed
uvicorn app.main:app --port 8000 &
PROCESSOR_TOKEN=lab-runner-demo-token python demo/demo.py
# docs: http://127.0.0.1:8000/docs | admin: http://127.0.0.1:8000/admin (admin/admin123)
```

Demo flow: login both users → operator fetch → voucher usage (`V-…`) →
processor beacon → usage status/beacons → `most_used_template` stat →
ungranted-template 403 → activity logs. Rotate the demo token via
`POST /api/v1/processors` afterwards (token shown once, stored hashed).

## Security notes (PoC pass)

- JWT access 30m + refresh 7d (env-tunable), secrets from env/`.env`.
- Processor tokens random 32B, shown once, sha256 at rest, constant-time compare.
- RBAC: coarse codes + object grants (deny by default); stats via per-user/role grants (no stats permission codes).
- Templates store JSON `content` validated against their category `input_schema`; resources store JSON `data` validated against their `resource_types.schema` (e.g. `mobile_device`); resource metadata entries are stored separately with their own `metadata_types.schema` (e.g. `monitor`), multiple per resource.
- Pagination capped at 100; Pydantic validation on all inputs; no hashes/tokens in reads.
- Prod TODO: strong `JWT_SECRET`, CORS allowlist, egress allowlist for external stats.

## Notes

- Async everywhere, SQLite via `aiosqlite`, `data/` auto-created (gitignored).
- Terminology rule: `template`, not `script`.
- No real execution — only relay + record (usages/beacons in later stages).
