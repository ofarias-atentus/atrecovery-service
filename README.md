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

See `plan.md §6`. Current: **Stage 4 done** (usage layer: `execution_modes`,
`template_usages`, `usage_limits`; `services/usage_svc.py` limit checks
global/user/role/group × total/daily/monthly; `POST /usages` with use-grant +
429 on exhaustion, `GET /{id}/status` with voucher `external_dispatch_id`;
scheduler requires `schedule_at`; fetch also checks limits; seed modes +
hello.py 10/day demo limit).
Next: **Stage 5 — Beacon Results + Processor Auth** (`X-Processor-Token`, results per usage).

## Notes

- Async everywhere, SQLite via `aiosqlite`, `data/` auto-created (gitignored).
- Terminology rule: `template`, not `script`.
- No real execution — only relay + record (usages/beacons in later stages).
