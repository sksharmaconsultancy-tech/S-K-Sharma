"""Iter 685 E2E repro — frozen snapshot vs edited master (VIPUL case).

Flow: create firm + STAFF employee with WRONG monthly compliance 16120 →
generate compliance run (snapshot freezes) → PATCH master to daily 300 →
reprocess (expect STILL 16120 — frozen by design) → refresh-master
(expect master columns 300×31 = 9300).
"""
import asyncio, json, sys
import httpx

BASE = "http://localhost:8001/api"
TOKEN = open("/tmp/skc_token.txt").read().strip()
H = {"Authorization": f"Bearer {TOKEN}"}
MONTH = "2026-07"


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        # 1. firm
        r = await c.post(f"{BASE}/companies", headers=H, json={
            "name": "VIPUL TEST 685", "company_code": "VT685",
            "office_lat": 25.35, "office_lng": 74.64})
        if r.status_code != 200:
            rr = await c.get(f"{BASE}/companies", headers=H)
            comps = rr.json() if isinstance(rr.json(), list) else rr.json().get("companies", [])
            cid = next((x["company_id"] for x in comps
                        if x.get("name") == "VIPUL TEST 685"), None)
            print("firm exists:", cid)
        else:
            j = r.json()
            cid = j.get("company_id") or (j.get("company") or {}).get("company_id")
        print("cid:", cid, r.status_code)
        if not cid:
            print(r.text[:300]); sys.exit(1)

        # 2. (employee already exists — reset done via mongo)
        r = None
        uid = "user_bd2c0918401d"  # created in an earlier attempt
        print("uid:", uid)

        # 3. generate compliance run (STAFF scope)
        r = await c.post(f"{BASE}/admin/compliance-salary-runs", headers=H, json={
            "month": MONTH, "company_id": cid, "month_days": 31,
            "employee_type": "STAFF"})
        run = r.json()
        run_id = run.get("run_id")
        row = next((x for x in run.get("rows", []) if x.get("user_id") == uid), {})
        print(f"GEN: run={run_id} mode={row.get('salary_mode')} rate={row.get('rate')} "
              f"M.Basic={row.get('basic_master')} M.Gross={row.get('gross_master')}")

        # 4. edit master → daily 300 (same PATCH the UI uses)
        r = await c.patch(f"{BASE}/admin/employees/{uid}/profile", headers=H, json={
            "compliance_salary_mode": "daily", "compliance_basic": 300})
        print("patch:", r.status_code, r.text[:120])

        # 5. reprocess — expect frozen 16120 (by design)
        r = await c.post(f"{BASE}/admin/compliance-salary-runs", headers=H, json={
            "month": MONTH, "company_id": cid, "month_days": 31,
            "employee_type": "STAFF"})
        run2 = r.json()
        row2 = next((x for x in run2.get("rows", []) if x.get("user_id") == uid), {})
        print(f"REPROCESS: mode={row2.get('salary_mode')} rate={row2.get('rate')} "
              f"M.Basic={row2.get('basic_master')} M.Gross={row2.get('gross_master')}")

        # 6. refresh master snapshot — expect 300/day → M 9300
        rid = run2.get("run_id") or run_id
        r = await c.post(f"{BASE}/admin/compliance-salary-runs/{rid}/refresh-master-snapshot",
                         headers=H, json={"reason": "rate fixed to 300/day"})
        print("refresh:", r.status_code)
        if r.status_code == 200:
            run3 = r.json().get("run", {})
            row3 = next((x for x in run3.get("rows", []) if x.get("user_id") == uid), {})
            print(f"REFRESH: mode={row3.get('salary_mode')} rate={row3.get('rate')} "
                  f"M.Basic={row3.get('basic_master')} M.Gross={row3.get('gross_master')}")
        else:
            print(r.text[:300])

asyncio.run(main())
