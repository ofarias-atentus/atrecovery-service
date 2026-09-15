# Tutorial — First Steps with Atrecovery Service

A hands-on walkthrough to get familiar with what this service does. Estimated time: 25–35 minutes.

## What is this?

A FastAPI app to **retrieve, maintain, and categorize routines** (never "scripts").
It does **not** execute anything — it only relays usage requests and records results
reported back by external processor services.

The moving parts, in one sentence each:

| Concept | What it is |
|---|---|
| Routine | A JSON document (e.g. `hello.py`), validated against its category's `input_schema` |
| Category | A routine kind (`python`, `json`) that owns the `input_schema` |
| Resource | A JSON device record (e.g. the `Moto G6 3` phone), validated against its `resource_types.schema` (e.g. `mobile_device`) |
| Metadata | A separate typed JSON record attached to a resource (e.g. `monitor`); a resource can have several |
| Resource group | A named box of devices (`lab-phones`); members = what's inside, assignments = who gets it (§5) |
| Grant | Permission row that gives a user/role access to a routine or resource (deny by default) |
| Usage | A relayed "please run this routine" request (`direct`, `scheduler`, or `voucher` mode) |
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

## 2. Browse the catalog (categories → routines)

```bash
# What routine kinds exist? Note python's input_schema: every routine in it needs {"source": ...}
curl -s http://127.0.0.1:8000/api/v1/categories -H "Authorization: Bearer $OP" | python3 -m json.tool

# What routines can the operator see? (Just hello.py — access is grant-gated.)
curl -s http://127.0.0.1:8000/api/v1/routines -H "Authorization: Bearer $OP" | python3 -m json.tool
```

Takeaway: `content` is JSON, and the **category** owns the schema, not the routine.

## 3. Fetch a routine (this is the core "retrieve" action)

```bash
# Grab hello.py's id from the previous output, then:
TPL=<paste-hello.py-id>
curl -s http://127.0.0.1:8000/api/v1/routines/$TPL/fetch \
  -H "Authorization: Bearer $OP" | python3 -m json.tool
# → {"id":...,"name":"hello.py","content":{"language":"python","source":"print(...)",...}}
```

Try the same with `$ADMIN` — works too (superusers bypass grants). Now see deny-by-default:
as admin, create a routine nobody granted to the operator, then fetch it as operator and
watch it fail with **403**:

```bash
SECRET=$(curl -s -X POST http://127.0.0.1:8000/api/v1/routines \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"secret.py","category_id":1,"content":{"source":"top secret"}}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/routines/$SECRET/fetch \
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

# Validation works the same as routines — this is rejected (422), monitor requires all 5 keys:
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

## 6. Execute from the resource — direct, scheduler, voucher

This is the "execution is out-of-scope" loop: pick a device, see its routines,
record a request, and an external service later reports the result. Routines never
execute standalone — every usage names a `resource_id`, and the pair must be
**associated** (closed world: unassociated → 422). Three modes exist
(`GET /api/v1/execution-modes` lists them); all three need `routine:use` plus
use-grants on **both** the routine and the resource.

Start resource-first — ask the Moto G6 what it can run (seed associates it with `hello.py`):

```bash
curl -s http://127.0.0.1:8000/api/v1/resources/$RES/routines \
  -H "Authorization: Bearer $OP" | python3 -m json.tool
# → [{"name":"hello.py",...}] — only associated routines you hold a use-grant on
```

### 6a. Direct — fire and record (status is `dispatched` right away)

`mode` defaults to `direct`, so the smallest possible usage names routine + resource:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$RES}" | python3 -m json.tool
# → {"mode":"direct","status":"dispatched","external_dispatch_id":null,...}
```

### 6b. Scheduler — record a cron expression (external systems own execution)

Scheduler mode **requires** `cron` (validated, 5-field format) and optionally
stores a `payload`. The service only records the row — the *external executor* reads
`cron` (plus the read-time `next_fire_at` hint) and decides when to fire. Nothing
here ticks or dispatches (see `imprv.md`).

```bash
# Missing cron → 422. Try it to see the guard:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$RES,\"mode\":\"scheduler\"}" | python3 -m json.tool
# → {"detail":"scheduler mode requires cron"}

# Malformed cron → 422 as well:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$RES,\"mode\":\"scheduler\",\"cron\":\"every sometimes\"}" | python3 -m json.tool

# Every 15 min + payload → status stays "pending" until the executor reports:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$RES,\"mode\":\"scheduler\",\"cron\":\"*/15 * * * *\",\"payload\":{\"name\":\"ops\"}}" \
  | python3 -m json.tool
# → {"mode":"scheduler","status":"pending","cron":"*/15 * * * *","next_fire_at":"...","payload":{"name":"ops"},...}
```

Cron-driven executors report repeatedly, so beacons accept an `idem_key` owned by
the reporter: repeating a seen `(usage_id, idem_key)` replays the stored beacon
(**200**) instead of appending a duplicate (**201**). Each accepted beacon bumps
the usage `use_count`:

```bash
# (needs USAGE from §6c and a processor token; replace the key per fire)
curl -s -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "X-Processor-Token: lab-runner-demo-token" -H "Content-Type: application/json" \
  -d "{\"usage_id\":$USAGE,\"status\":\"ok\",\"idem_key\":\"cron-001\"}" | python3 -m json.tool  # → 201
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "X-Processor-Token: lab-runner-demo-token" -H "Content-Type: application/json" \
  -d "{\"usage_id\":$USAGE,\"status\":\"ok\",\"idem_key\":\"cron-001\"}"  # → 200, same row
```

### 6c. Voucher — get a dispatch id, then report a beacon

```bash
# 1) Operator runs hello.py on the Moto G6 in voucher mode → external dispatch id V-…
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$RES,\"mode\":\"voucher\"}" | python3 -m json.tool
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

### 6d. The closed world: associations are enforced, not advisory

Three rejections to try, one per guard layer (grants are checked before associations):

```bash
# 403 — secret.py was never granted to the operator (grant check runs first):
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$SECRET,\"resource_id\":$RES}" | python3 -m json.tool

# 422 — no resource at all: routines never execute standalone:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL}" | python3 -m json.tool

# 422 — Pixel from §5 runs nothing: associate first (admin), then it executes:
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$PIX}" | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8000/api/v1/resources/$PIX/routines \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL}" | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$PIX}" | python3 -m json.tool  # → 201
```

### 6e. Report the result with a beacon (close the loop on a dispatched usage)

A usage is just a request — the result arrives separately as a **beacon** posted
by the external processor. Take a `direct` dispatch like this one (create it with
the §6a call; ids below assume a fresh seed):

```json
{
    "id": 1,
    "routine_id": 1,
    "resource_id": 1,
    "requested_by": 2,
    "mode": "direct",
    "status": "dispatched",
    "external_dispatch_id": null,
    "cron": null,
    "next_fire_at": null,
    "payload": null,
    "use_count": 1,
    "created_at": "2026-09-15T15:04:49"
}
```

```bash
# 0) You need a processor token, NOT a JWT. Either seed with a known one:
#    SEED_PROCESSOR_TOKEN=lab-runner-demo-token python -m app.db.seed
#    ...or mint a fresh processor as admin (the token is shown once):
curl -s -X POST http://127.0.0.1:8000/api/v1/processors \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"my-runner"}' | python3 -m json.tool
# → {"id":...,"name":"my-runner","scopes":["beacon:report"],"is_active":true,"token":"..."}
# Save it:  PTOKEN=<paste-token>   (or PTOKEN=lab-runner-demo-token for the seeded runner)
```

The beacon body is tiny — `usage_id` + `status` + an optional free-form `result`
dict. The status drives the usage lifecycle: `ok` → `done`, `error` → `failed`,
`partial` → `running`:

```bash
# 1) The executor ran hello.py on the Moto G6 and it worked — report success:
curl -s -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "X-Processor-Token: $PTOKEN" -H "Content-Type: application/json" \
  -d '{"usage_id":1,"status":"ok","result":{"rc":0,"stdout":"hello from routine hello.py"}}' \
  | python3 -m json.tool
# → 201 {"id":1,"usage_id":1,"processor_id":1,"status":"ok",
#         "result":{"rc":0,"stdout":"hello from routine hello.py"},
#         "idem_key":null,"received_at":"..."}

# 2) The usage flipped dispatched → done. Each accepted beacon also bumps use_count (1 → 2):
curl -s http://127.0.0.1:8000/api/v1/usages/1/status \
  -H "Authorization: Bearer $OP" | python3 -m json.tool
# → {"id":1,"mode":"direct","status":"done","beacon_count":1,"latest_beacon_status":"ok",...}
curl -s http://127.0.0.1:8000/api/v1/usages/1 \
  -H "Authorization: Bearer $OP" | python3 -c "import sys,json; u=json.load(sys.stdin); print(u['status'], u['use_count'])"
# → done 2
```

The other two outcomes work the same way — new usage each time, since one beacon
per outcome is clearest to follow:

```bash
# error → failed (executor reports what went wrong in result):
U2=$(curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$RES}" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "X-Processor-Token: $PTOKEN" -H "Content-Type: application/json" \
  -d "{\"usage_id\":$U2,\"status\":\"error\",\"result\":{\"rc\":1,\"stderr\":\"boom\"}}" | python3 -m json.tool
# → 201 {"status":"error",...}
curl -s http://127.0.0.1:8000/api/v1/usages/$U2/status \
  -H "Authorization: Bearer $OP" | python3 -m json.tool
# → {"status":"failed","beacon_count":1,"latest_beacon_status":"error",...}

# partial → running (still working; report again when finished):
U3=$(curl -s -X POST http://127.0.0.1:8000/api/v1/usages \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d "{\"routine_id\":$TPL,\"resource_id\":$RES}" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "X-Processor-Token: $PTOKEN" -H "Content-Type: application/json" \
  -d "{\"usage_id\":$U3,\"status\":\"partial\",\"result\":{\"pct\":50}}" | python3 -m json.tool
# → 201 {"status":"partial",...}  (usage is now "running")
```

Read back what landed, and know the three rejections:

```bash
# All beacons for usage 1 (operator sees only own usages; admin sees all):
curl -s "http://127.0.0.1:8000/api/v1/beacons?usage_id=1" \
  -H "Authorization: Bearer $OP" | python3 -m json.tool

# 401 — beacon auth is X-Processor-Token, never the JWT Authorization header:
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "Authorization: Bearer $OP" -H "Content-Type: application/json" \
  -d '{"usage_id":1,"status":"ok"}'   # → 401

# 404 — unknown usage id:
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/v1/beacons \
  -H "X-Processor-Token: $PTOKEN" -H "Content-Type: application/json" \
  -d '{"usage_id":9999,"status":"ok"}'   # → 404

# 403 — the processor was created without the beacon:report scope
```

Tip: for cron-driven executors that fire repeatedly, add `"idem_key":"cron-001"`
(§6b): repeating a seen `(usage_id, idem_key)` replays the stored row (**200**)
instead of appending a duplicate (**201**).

### 6f. List usages

```bash
# Operators see only their own usages; admins see everyone's (try both tokens):
curl -s http://127.0.0.1:8000/api/v1/usages -H "Authorization: Bearer $OP" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/v1/usages?routine_id=$TPL" \
  -H "Authorization: Bearer $ADMIN" | python3 -m json.tool
```

One guard to know about: an unknown `mode` is rejected with 422.

## 7. Peek at the audit trail and the admin UI

```bash
# Every fetch/usage/beacon/grant change appends here (admin only, read-only):
curl -s http://127.0.0.1:8000/api/v1/activity-logs \
  -H "Authorization: Bearer $ADMIN" | python3 -m json.tool | head -50
```

Then open http://127.0.0.1:8000/admin and log in as `admin` / `admin123`:
CRUD every table, read-only logs/beacons, credential hashes hidden.

## 8. Run the tests

```bash
# Test suite (uses throwaway temp DBs, never touches ./data/app.db):
pytest -q
```

## Reset / troubleshooting

| Symptom | Fix |
|---|---|
| `422` creating a routine | `content` must satisfy the **category's** `input_schema` (python needs `{"source": ...}`); extra fields like per-routine `input_schema` are rejected |
| `422` creating a resource/metadata | `data` must satisfy the type's `schema` (check `/resource-types` or `/metadata-types`) |
| `403` on fetch/read | Normal: no grant. Log in as admin and add one (`POST /api/v1/grants/...`) |
| `422` on usage, missing resource | Usages always name a `resource_id` — routines never execute standalone |
| `422` on usage, not associated | Pair the routine to the device first (`POST /resources/{id}/routines`); empty devices run nothing |
| `401` on beacons | Beacon auth uses `X-Processor-Token`, not the JWT `Authorization` header |
| Weird state after pulling changes | Schema changed? `rm -f data/app.db && python -m app.db.seed` and restart |

## Where to look next

- `docs/ER.md` — database diagram + table overview
- `app/api/v1/` — one file per domain (`routines.py`, `resources.py`, `metadata_types.py`, `usages.py`, `beacons.py`, `grants.py`, …)
- `app/db/seed.py` — every piece of demo data in one place (`CATEGORY_DEFS`, `RESOURCE_TYPE_DEFS`, `METADATA_TYPE_DEFS`, `RESOURCE_DEFS`, …)
