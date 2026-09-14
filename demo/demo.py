"""End-to-end PoC demo (Stage 8).

Expects a seeded server running: see README "Demo". Flow:
login both users → operator fetch → voucher usage → processor beacon →
usage status + beacons → denied case (ungranted template → 403) →
show activity logs. Exits non-zero on the first mismatch.
"""
from __future__ import annotations

import os
import sys

import httpx2

BASE = os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000")
PROCESSOR_TOKEN = os.environ.get("PROCESSOR_TOKEN", "lab-runner-demo-token")

PASS, FAIL = "PASS", "FAIL"
failures = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{PASS if condition else FAIL}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures += 1


def main() -> int:
    client = httpx2.Client(base_url=BASE, timeout=15.0)

    def login(username: str, password: str) -> dict[str, str]:
        r = client.post(
            "/api/v1/auth/token", data={"username": username, "password": password}
        )
        ok = r.status_code == 200
        check(f"login {username}", ok, "token issued" if ok else r.text[:120])
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    admin, operator = login("admin", "admin123"), login("operator", "operator123")

    templates = client.get("/api/v1/templates", headers=operator).json()
    hello = next(t for t in templates if t["name"] == "hello.py")
    check("operator lists granted templates", True, f"sees hello.py id={hello['id']}")

    fetch = client.get(f"/api/v1/templates/{hello['id']}/fetch", headers=operator)
    _content = fetch.json().get("content", "")
    _detail = _content["source"].strip() if isinstance(_content, dict) else str(_content).strip()
    check("operator fetch hello.py", fetch.status_code == 200, _detail)

    # Resource-first: pick the Moto G6 phone, list its executable templates.
    resources = client.get("/api/v1/resources", headers=operator).json()
    moto = next(r for r in resources if r["identifier"] == "ZY323S5GHW")
    runnable = client.get(f"/api/v1/resources/{moto['id']}/templates", headers=operator).json()
    check("resource lists its executable templates",
          any(t["name"] == "hello.py" for t in runnable),
          f"{len(runnable)} associated")

    usage = client.post(
        "/api/v1/usages", headers=operator,
        json={"template_id": hello["id"], "resource_id": moto["id"], "mode": "voucher"},
    ).json()
    vid = usage.get("external_dispatch_id", "")
    check("voucher usage returns dispatch id", vid.startswith("V-"), vid)

    beacon = client.post(
        "/api/v1/beacons", headers={"X-Processor-Token": PROCESSOR_TOKEN},
        json={"usage_id": usage["id"], "status": "ok", "result": {"rc": 0}},
    )
    check("processor beacon accepted", beacon.status_code == 201, beacon.text[:120])

    status = client.get(f"/api/v1/usages/{usage['id']}/status", headers=operator).json()
    check("usage done with beacon link",
          status["status"] == "done" and status["beacon_count"] == 1
          and status["external_dispatch_id"] == vid)
    beacons = client.get(f"/api/v1/beacons?usage_id={usage['id']}", headers=operator).json()
    check("beacons listed for usage", len(beacons) == 1 and beacons[0]["status"] == "ok")

    secret = client.post(
        "/api/v1/templates", headers=admin,
        json={"name": f"demo-secret-{os.getpid()}.py", "category_id": 1,
              "content": {"source": "x"}},
    ).json()
    denied = client.get(f"/api/v1/templates/{secret['id']}/fetch", headers=operator)
    check("ungranted fetch denied", denied.status_code == 403, f"got {denied.status_code}")

    logs = client.get("/api/v1/activity-logs", headers=admin).json()
    actions = {e["action"] for e in logs}
    check("activity logs recorded", {"template.fetch", "template.use", "beacon.received"} <= actions,
          f"{len(logs)} rows")
    for entry in logs[:5]:
        print(f"  log: {entry['action']} user={entry['user_id']} "
              f"{entry['entity_type']}={entry['entity_id']} ip={entry['ip']}")

    print(f"\ndemo {'PASSED' if failures == 0 else 'FAILED'} ({failures} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
