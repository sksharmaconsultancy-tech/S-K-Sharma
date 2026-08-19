"""Iter 616 — Copy Last Month + reprocess 'With EXISTING Data' must match."""
import asyncio, os, uuid
from datetime import datetime, timezone, timedelta
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
P = F = 0
def chk(n, c, e=""):
    global P, F
    P, F = (P + 1, F) if c else (P, F + 1)
    print(("  ✅ " if c else "  ❌ ") + n, e if not c else "")

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    su = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"user_id": 1})
    tok = "t_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_one({"session_token": tok, "user_id": su["user_id"],
        "expires_at": now + timedelta(hours=1), "created_at": now, "auth_method": "password"})
    H = {"Authorization": f"Bearer {tok}"}
    body = {"month": "2026-08", "employee_type": "STAFF", "company_id": CID}
    async with httpx.AsyncClient(timeout=120) as c:
        # 1. Copy last month (2026-07 STAFF exists as draft)
        r = await c.post(f"{BASE}/admin/compliance-salary-runs", headers=H,
                         json={**body, "copy_last_month": True})
        chk("copy last month OK", r.status_code == 200, r.text[:200])
        run1 = r.json()["run"]
        chk("attendance_source=copied_last_month",
            str(run1.get("attendance_source", "")).startswith("copied_last_month"))
        # 2. Edit one row + save (simulate manual correction)
        rows = run1["rows"]
        rows[0]["others"] = 777.0
        rows[0]["gross_paid"] = round(float(rows[0].get("gross_paid") or 0) + 777, 2)
        rows[0]["net"] = round(float(rows[0].get("net") or 0) + 777, 2)
        r = await c.post(f"{BASE}/admin/compliance-salary-runs/{run1['run_id']}/save-rows",
                         headers=H, json={"rows": rows, "totals": run1["totals"]})
        chk("save-rows OK", r.status_code == 200, r.text[:150])
        # 3. Salary Process again "With EXISTING Data" (no fresh flag)
        r = await c.post(f"{BASE}/admin/compliance-salary-runs", headers=H, json=body)
        chk("reprocess existing OK", r.status_code == 200, r.text[:200])
        run2 = r.json()["run"]
        m1 = {x["user_id"]: x for x in rows}
        m2 = {x["user_id"]: x for x in run2["rows"]}
        chk("same employee set", set(m1) == set(m2))
        mism = []
        for uid, a in m1.items():
            b = m2.get(uid) or {}
            for k in ("present_days", "basic", "hra", "gross_paid", "pf_employee",
                      "esic_employee", "others", "net"):
                if round(float(a.get(k) or 0), 2) != round(float(b.get(k) or 0), 2):
                    mism.append((a.get("name"), k, a.get(k), b.get(k)))
        chk("ALL values MATCH after reprocess (no mismatch)", not mism, str(mism[:4]))
        chk("copied source kept on reprocess",
            str(run2.get("attendance_source", "")).startswith("copied_last_month"))
        chk("saved manual edit (777) kept",
            round(float((m2.get(rows[0]["user_id"]) or {}).get("others") or 0), 2) == 777.0)
        # 4. "From BLANK" must still rebuild fresh from attendance/master
        r = await c.post(f"{BASE}/admin/compliance-salary-runs", headers=H,
                         json={**body, "fresh": True})
        chk("fresh rebuild OK", r.status_code == 200, r.text[:150])
        run3 = r.json()["run"]
        chk("fresh rebuild NOT copied source",
            not str(run3.get("attendance_source", "")).startswith("copied_last_month"),
            run3.get("attendance_source"))
    # cleanup — remove all 2026-08 STAFF test runs
    d = await db.compliance_salary_runs.delete_many(
        {"month": "2026-08", "company_id": CID})
    await db.user_sessions.delete_one({"session_token": tok})
    print(f"cleaned {d.deleted_count} test runs\n==== {P} passed, {F} failed ====")
    raise SystemExit(1 if F else 0)

asyncio.run(main())
