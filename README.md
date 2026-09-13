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

See `plan.md §6`. Current: **Stage 7 done** (stats: `statistics_definitions` with
internal|external source, admin CRUD at `/stats/definitions`, value reads at
`/stats/{name}` gated on the linked permission code; internal resolvers
`most_used_template`, `last_fetch_by_user` (owner-or-admin for other user_ids),
`beacon_success_rate`; external fetcher via `httpx` with timeout, required-param
validation, optional dot-path mapping, 502 on failure; seed 3 defs on stats:view).
Next: **Stage 8 — Admin UI, Docs Polish, Demo & Hardening** (sqladmin, ER docs, demo script, security pass).

## Notes

- Async everywhere, SQLite via `aiosqlite`, `data/` auto-created (gitignored).
- Terminology rule: `template`, not `script`.
- No real execution — only relay + record (usages/beacons in later stages).
