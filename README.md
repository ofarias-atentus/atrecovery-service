# Template Management PoC

FastAPI PoC to retrieve/maintain/categorize **templates** (never "scripts"). Execution is out-of-scope — see `plan.md`.

## Stage 0 — Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust JWT_SECRET in prod
uvicorn app.main:app --reload
# health: http://127.0.0.1:8000/health | docs: /docs | version: /version
pytest -q
```

## Stages

See `plan.md §6`. Current: **Stage 0 done** (bootstrap: config, async SQLite, logging+request-ID, health/docs, tests).
Next: **Stage 1 — Identity, Auth & RBAC** (users/roles/permissions, JWT, providers, seed admin/operator).

## Notes

- Async everywhere, SQLite via `aiosqlite`, `data/` auto-created (gitignored).
- Terminology rule: `template`, not `script`.
- No real execution — only relay + record (usages/beacons in later stages).
