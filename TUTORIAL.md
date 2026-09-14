# Tutorial — First Steps with the Template Management PoC

A hands-on walkthrough to get familiar with what this PoC does. Estimated time: 25–35 minutes.

## What is this?

A FastAPI app to **retrieve, maintain, and categorize templates** (never "scripts").
It does **not** execute anything — it only relays usage requests and records results
reported back by external processor services.

The moving parts, in one sentence each:

| Concept | What it is |
|---|---|
| Template | A JSON document (e.g. `hello.py`), validated against its category's `input_schema` |
| Category | A template kind (`python`, `json`) that owns the `input_schema` |
| Resource | A JSON device record (e.g. the `Moto G6 3` phone), validated against its `resource_types.schema` (e.g. `mobile_device`) |
| Metadata | A separate typed JSON record attached to a resource (e.g. `monitor`); a resource can have several |
| Resource group | A named box of devices (`lab-phones`); members = what's inside, assignments = who gets it (§5) |
| Grant | Permission row that gives a user/role access to a template or resource (deny by default) |
| Usage | A relayed "please run this template" request (`direct`, `scheduler`, or `voucher` mode) |
| Beacon | A result posted back by an external processor for a usage (auth via `X-Processor-Token`, not JWT) |

Demo users (created by the seed): **admin / admin123** (superuser, sees everything) and
**operator / operator123** (only sees what was granted to the `operator` role).

## 0. Setup (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # defaults are fine for local play
rm -f data/app.db      # only if you re-seed after a schema change
python -m app.db.seed  # creates users, hello.py, Moto G6 3, lab-phones group, grants
uvicorn app.main:app --reload
```

Check it works: open http://127.0.0.1:8000/health (`{"status":"ok",...}`) and
http://127.0.0.1:8000/docs (interactive API docs — you can do this whole tutorial there too).

> All commands below assume the server runs at `http://127.0.0.1:8000`.

## 1. Log in and save your tokens

```bash
# admin token
ADMIN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/token \
  -d "username=admin&password=admin123" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# operator token
OP=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/token \
  -d "username=operator&password=operator123" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "admin token: ${ADMIN:0:20}... / operator token: ${OP:0:20}..."
```

Use them as `-H "Authorization: Bearer $OP"` (or `$ADMIN`).

## 2. Browse the catalog (categories → templates)

```bash
# What template kinds exist? Note python's input_schema: every template in it needs {"source": ...}
curl -s http://127.0.0.1:8000/api/v1/categories -H "Authorization: Bearer $OP" | python3 -m json.tool

# What templates can the operator see? (Just hello.py — access is grant-gated.)
curl -s http://127.0.0.1:8000/api/v1/templates -H "Authorization: Bearer $OP" | python3 -m json.tool
```

Takeaway: `content` is JSON, and the **category** owns the schema, not the template.

## 3. Fetch a template (this is the core "retrieve" action)

```bash
# Grab hello.py's id from the previous output, then:
TPL=<paste-hello.py-id>
curl -s http://127.0.0.1:8000/api/v1/templates/$TPL/fetch \
  -H "Authorization: Bearer $OP" | python3 -m json.tool
# → {"id":...,"name":"hello.py","content":{"language":"python","source":"print(...)",...}}
```

Try the same with `$ADMIN` — works too (superusers bypass grants). Now see deny-by-default:
as admin, create a template nobody granted to the operator, then fetch it as operator and
watch it fail with **403**:

```bash
SECRET=$(curl -s -X POST http://127.0.0.1:8000/api/v1/templates \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"secret.py","category_id":1,"content":{"source":"top secret"}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/templates/$SECRET/fetch \
  -H "Authorization: Bearer $OP"   # → 403
```

## 4. Look at resources, types, and metadata

```bash
# Types: mobile_device validates device data, monitor validates metadata
curl -s http://127.0.0.1:8000/api/v1/resource-types -H "Authorization: Bearer $OP" | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/v1/metadata-types -H "Authorization: Bearer $OP" | python3 -m json.tool

# The seed phone: data is pure device info...
curl -s http://127.0.0.1:8000/api/v1/resources -H "Authorization: Bearer $OP" | python3 -m json.tool
# → {"identifier":"ZY323S5GHW","resource_type_name":"mobile_device",
#     "data":{"udid":"ZY323S5GHW","nombre":"Moto G6 3","plataforma":"android",...},
#     "metadata":[{"metadata_type_name":"monitor","data":{"monitor":"monitor-01",...}}]}
```

Takeaway: **device data and monitoring data live apart** — `data` on the resource,
`monitor` as a separate typed entry. One resource can hold several such entries.

```bash
# List just the metadata of that phone:
RES=<paste-resource-id>
curl -s http://127.0.0.1:8000/api/v1/resources/$RES/metadata \
  -H "Authorization: Bearer $OP" | python3 -m json.tool

# Validation works the same as templates — this is rejected (422), monitor requires all 5 keys:
curl -s -X POST http://127.0.0.1:8000/api/v1/resources/$RES/metadata \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"metadata_type":"monitor","data":{"monitor":"m1"}}'
```

## 5. Share devices with resource groups

A group is a named box of devices with **two separate lists** — don't mix them up:

- **members** = which devices are inside (`resource_group_members`)
- **assignments** = which users/roles get the box (`group_assignments`)

Neither list alone grants access. Access comes from a **grant** row pointing at the
group (`POST /api/v1/grants/resources` with `group_id`). The payoff: add a new phone
to a granted group and it's instantly visible — no new grant row needed.

Hands-on: build a second group from scratch and watch the operator go from 403 → 200.

```bash
# 1) As admin: new group + new phone (mobile_device data needs udid/nombre/plataforma)
GRP=$(curl -s -X POST http://127.0.0.1:8000/api/v1/resource-groups \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"demo-phones","description":"Tutorial group"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
PIX=$(curl -s -X POST http://127.0.0.1:8000/api/v1/resources \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"Pixel","identifier":"PIXEL01","data":{"udid":"PIXEL01","nombre":"Pixel","plataforma":"android"}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2) Put the phone in the box (members):
curl -s -X POST http://127.0.0.1:8000/api/v1/resource-groups/$GRP/members \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d "{\"resource_id\":$PIX}" | python3 -m json.tool
# → {"name":"demo-phones","resources":["PIXEL01"],"assignments":[]}

# 3) Operator still locked out (403) — members alone grant nothing:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/resources/$PIX \
  -H "Authorization: Bearer $OP"   # → 403

# 4) Hand the box to the operator role (assignments) + switch access on (grant):
RID=$(curl -s http://127.0.0.1:8000/api/v1/roles -H "Authorization: Bearer $ADMIN" \
  | python3 -c "import sys,json; print(next(r['id'] for r in json.load(sys.stdin) if r['name']=='operator'))")
curl -s -X POST http://127.0.0.1:8000/api/v1/resource-groups/$GRP/assignments \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d "{\"principal_type\":\"role\",\"principal_id\":$RID}" | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8000/api/v1/grants/resources \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d "{\"group_id\":$GRP,\"principal_type\":\"role\",\"principal_id\":$RID,\"can_view\":true,\"can_use\":true}" | python3 -m json.tool

# 5) Operator sees the phone now — and any phone added to demo-phones later is automatic:
curl -s http://127.0.0.1:8000/api/v1/resources/$PIX \
  -H "Authorization: Bearer $OP" | python3 -m json.tool  # → 200

# Audit helper — which boxes reach the operator (direct + via roles)?
OPID=$(curl -s http://127.0.0.1:8000/api/v1/users -H "Authorization: Bearer $ADMIN" \
  | python3 -c "import sys,json; print(next(u['id'] for u in json.load(sys.stdin) if u['username']=='operator'))")
curl -s http://127.0.0.1:8000/api/v1/resource-groups/by-principal/user/$OPID \
  -H "Authorization: Bearer $ADMIN" | python3 -m json.tool
# → lab-phones (seed) + demo-phones
```

Takeaway: **members** say what's inside, **assignments** say who gets it, **grants**
switch access on. The seed's `lab-phones` is exactly this pattern pre-built: Moto G6
inside, assigned + granted to the `operator` role.

## 6. Relay usages — direct, scheduler, voucher

This is the "execution is out-of-scope" loop: you record a request, an external
service later reports the result. Three modes exist (`GET /api/v1/execution-modes`
lists them); all three need `template:use` plus a use-grant on the template.

### 6a. Direct — fire and record (status is `dispatched` right away)

`mode` defaults to `direct`, so the smallest possible usage is just a template id:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"template_id\":$TPL}" | python3 -m json.tool
# → {"mode":"direct","status":"dispatched","external_dispatch_id":null,...}
```

### 6b. Scheduler — store a future run (nothing dispatches it automatically)

Scheduler mode **requires** `schedule_at` and optionally stores a `payload`.
The PoC only records the row — a real scheduler worker would pick it up later
(see `imprv.md`).

```bash
# Missing schedule_at → 422. Try it to see the guard:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"template_id\":$TPL,\"mode\":\"scheduler\"}" | python3 -m json.tool
# → {"detail":"scheduler mode requires schedule_at"}

# With a date + payload → status stays "pending" until something external acts:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"template_id\":$TPL,\"mode\":\"scheduler\",\"schedule_at\":\"2030-01-01T00:00:00\",\"payload\":{\"name\":\"ops\"}}" \
  | python3 -m json.tool
# → {"mode":"scheduler","status":"pending","schedule_at":"2030-01-01T00:00:00","payload":{"name":"ops"},...}
```

### 6c. Voucher — get a dispatch id, then report a beacon

```bash
# 1) Operator requests hello.py in voucher mode → you get an external dispatch id V-…
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"template_id\":$TPL,\"mode\":\"voucher\"}" | python3 -m json.tool
# Read "id" and "external_dispatch_id" (starts with V-) from the output, then:
USAGE=<paste-usage-id>

# 2) The external processor reports the result. NOTE: no JWT here — token header instead.
#    For a seeded dev DB the lab-runner token was printed by the seed; for the demo token use:
curl -s -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "X-Processor-Token: lab-runner-demo-token" -H "Content-Type: application/json" \
  -d "{\"usage_id\":$USAGE,\"status\":\"ok\",\"result\":{\"rc\":0}}" | python3 -m json.tool
# (If that token is rejected, you seeded with a random token: create a fresh processor as admin —
#  POST /api/v1/processors {"name":"my-runner"} — it returns "token": use that value once.)

# 3) Check the usage status and its beacons:
curl -s http://127.0.0.1:8000/api/v1/usages/$USAGE/status \
  -H "Authorization: Bearer $OP" | python3 -m json.tool
# → {"status":"done","beacon_count":1,...}
curl -s "http://127.0.0.1:8000/api/v1/beacons?usage_id=$USAGE" \
  -H "Authorization: Bearer $OP" | python3 -m json.tool
```

### 6d. Target a resource (needs a use-grant on it too)

Pass `resource_id` to aim a usage at a device. The operator holds a use-grant on the
`lab-phones` group, so the seed phone works; an ungranted resource gives 403:

```bash
# Works — Moto G6 3 is in the granted lab-phones group:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"template_id\":$TPL,\"resource_id\":$RES,\"mode\":\"direct\"}" | python3 -m json.tool

# 403 — secret.py from step 3 was never granted to the operator:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"template_id\":$SECRET}" | python3 -m json.tool
```

### 6e. List usages and watch the limits

```bash
# Operators see only their own usages; admins see everyone's (try both tokens):
curl -s http://127.0.0.1:8000/api/v1/usages -H "Authorization: Bearer $OP" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/v1/usages?template_id=$TPL" \
  -H "Authorization: Bearer $ADMIN" | python3 -m json.tool
```

Two guards to know about: an unknown `mode` is rejected with 422, and exhausted
usage limits answer **429**. The seed puts a 10/day global limit on `hello.py`
(`GET /api/v1/usage-limits` as admin to inspect) — hammer the fetch endpoint in a
loop and you'll see fetch flip to 429 too, since fetches check limits as well.

## 7. Peek at the audit trail and the admin UI

```bash
# Every fetch/usage/beacon/grant change appends here (admin only, read-only):
curl -s http://127.0.0.1:8000/api/v1/activity-logs \
  -H "Authorization: Bearer $ADMIN" | python3 -m json.tool | head -50
```

Then open http://127.0.0.1:8000/admin and log in as `admin` / `admin123`:
CRUD every table, read-only logs/beacons, credential hashes hidden.

## 8. Run the automated end-to-end demo and the tests

```bash
# Fresh DB + known processor token + demo (mirrors steps 1–7 automatically):
rm -f data/app.db
SEED_PROCESSOR_TOKEN=lab-runner-demo-token python -m app.db.seed
uvicorn app.main:app --port 8000 &
PROCESSOR_TOKEN=lab-runner-demo-token python demo/demo.py

# Test suite (uses throwaway temp DBs, never touches ./data/app.db):
pytest -q
```

## Reset / troubleshooting

| Symptom | Fix |
|---|---|
| `422` creating a template | `content` must satisfy the **category's** `input_schema` (python needs `{"source": ...}`); extra fields like per-template `input_schema` are rejected |
| `422` creating a resource/metadata | `data` must satisfy the type's `schema` (check `/resource-types` or `/metadata-types`) |
| `403` on fetch/read | Normal: no grant. Log in as admin and add one (`POST /api/v1/grants/...`) |
| `401` on beacons | Beacon auth uses `X-Processor-Token`, not the JWT `Authorization` header |
| Weird state after pulling changes | Schema changed? `rm -f data/app.db && python -m app.db.seed` and restart |

## Where to look next

- `docs/ER.md` — database diagram + table overview
- `demo/demo.py` — the whole flow in ~90 lines of Python
- `app/api/v1/` — one file per domain (`templates.py`, `resources.py`, `metadata_types.py`, `usages.py`, `beacons.py`, `grants.py`, …)
- `app/db/seed.py` — every piece of demo data in one place (`CATEGORY_DEFS`, `RESOURCE_TYPE_DEFS`, `METADATA_TYPE_DEFS`, `RESOURCE_DEFS`, …)
