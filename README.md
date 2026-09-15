# Atrecovery Service

FastAPI service to retrieve/maintain/categorize **routines** (never "scripts").

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

See `plan.md §6`. Current: **Stage 8 done** (sqladmin at `/admin`
with local login guard for superuser/`admin:manage`, read-only activity-log and
beacon views, credential hashes excluded; finalized `docs/ER.md`;
security pass below).

## Security notes

- JWT access 30m + refresh 7d (env-tunable), secrets from env/`.env`.
- Processor tokens random 32B, shown once, sha256 at rest, constant-time compare.
- RBAC: coarse codes + object grants (deny by default).
- Routines store JSON `content` validated against their category `input_schema`; resources store JSON `data` validated against their `resource_types.schema` (e.g. `mobile_device`); resource metadata entries are stored separately with their own `metadata_types.schema` (e.g. `monitor`), multiple per resource.
- Pagination capped at 100; Pydantic validation on all inputs; no hashes/tokens in reads.
- Prod TODO: strong `JWT_SECRET`, CORS allowlist.

## Notes

- Async everywhere, SQLite via `aiosqlite`, `data/` auto-created (gitignored).
- Terminology rule: `routine`, not `script`.
- No real execution — only relay + record (usages/beacons in later stages).
