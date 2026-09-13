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

See `plan.md §6`. Current: **Stage 5 done** (beacons: `processor_services` with
sha256 token auth via `X-Processor-Token` + `get_processor`, `execution_results`
one-to-many per usage; `POST /beacons` processor-only with `beacon:report` scope,
drives usage ok→done/error→failed/partial→running; `GET /beacons` JWT-gated on
`template:view` scoped to own usages; `/processors` admin CRUD with shown-once
token; usage status embeds beacon count/latest; seed lab-runner).
Next: **Stage 6 — Activity Tracking** (append-only logs from fetch/usage/beacon/grant changes).

## Notes

- Async everywhere, SQLite via `aiosqlite`, `data/` auto-created (gitignored).
- Terminology rule: `template`, not `script`.
- No real execution — only relay + record (usages/beacons in later stages).
