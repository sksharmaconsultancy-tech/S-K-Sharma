"""Iter 630 — CONFORMANCE TEST: Allowance Enable/Disable & Freeze Salary
Reconciliation contract (user 7-rule spec). Runs on scratch month 2025-12,
firm Kankani, test employee TNF40186C (Basic 16000 + HRA 3000 monthly).
Everything created is deleted and every toggled setting restored."""
import asyncio, os, uuid
from datetime import datetime, timezone, timedelta
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
MONTH = "2025-12"
UID = "user_94e190f2843e"   # TEST NF 2244b / TNF40186C
P = F = 0
def chk(n, c, e=""):
    global P, F
    P, F = (P + 1, F) if c else (P, F + 1)
    print(("  ✅ " if c else "  ❌ ") + n, e if not c else "")

def row_of(run, uid=UID):
    for r in run.get("rows") or []:
        if r.get("user_id") == uid:
            return r
    return {}

async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]
    su = await db.users.find_one({"email": "sksharmaconsultancy@gmail.com"}, {"user_id": 1})
    tok = "t_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.user_sessions.insert_one({"session_token": tok, "user_id": su["user_id"],
        "expires_at": now + timedelta(hours=1), "created_at": now, "auth_method": "password"})
    H = {"Authorization": f"Bearer {tok}"}

    fm0 = await db.firm_masters.find_one({"company_id": CID}, {"_id": 0, "allowances": 1})
    orig_hra = (fm0.get("allowances") or {}).get("HRA")
    emp0 = await db.users.find_one({"user_id": UID}, {"_id": 0, "salary_structure_compliance": 1})
    run_id = None
    try:
        # imported sheet entry: 26 days, freeze gross 20000
        await db.compliance_import_entries.delete_many({"company_id": CID, "month": MONTH})
        await db.compliance_import_entries.insert_one({
            "company_id": CID, "month": MONTH, "user_id": UID,
            "present_days": 26, "gross_earning": 20000.0,
            "deduction_head": "", "deduction_amount": 0, "tds": 0, "other_less": 0})
        async with httpx.AsyncClient(timeout=300) as c:
            # ── RUN 1: HRA enabled ──
            r = await c.post(f"{BASE}/admin/compliance-salary-runs", headers=H,
                             json={"month": MONTH, "company_id": CID,
                                   "month_days": 31, "use_imported_sheet": True})
            chk("run 1 created", r.status_code == 200, r.text[:300])
            run = r.json().get("run") or r.json()
            run_id = run.get("run_id")
            r1 = row_of(run)
            hra1 = float(r1.get("hra") or 0)
            gp1 = float(r1.get("gross_paid") or 0)
            adj1 = float(r1.get("ot_pay") or 0) + float(r1.get("others") or 0)
            pf1 = float(r1.get("pf") or 0)
            print(f"    run1: hra={hra1} gross_paid={gp1} adj(ot+others)={adj1} pf={pf1}")
            chk("RULE2: Gross Paid == Imported Freeze Gross (20000)", abs(gp1 - 20000) < 1, gp1)
            chk("HRA present while enabled", hra1 > 0, hra1)
            chk("RULE2: difference sits in OT/Other Allowance", adj1 > 0, adj1)

            # RULE4/6 — stored source data untouched by the run
            emp1 = await db.users.find_one({"user_id": UID}, {"_id": 0, "salary_structure_compliance": 1})
            imp1 = await db.compliance_import_entries.find_one({"company_id": CID, "month": MONTH, "user_id": UID}, {"_id": 0})
            chk("RULE4: Employee Master structure unchanged (HRA still 3000 stored)",
                emp1 == emp0, emp1)
            chk("RULE4: imported sheet entry unchanged (gross 20000, days 26)",
                imp1["gross_earning"] == 20000.0 and imp1["present_days"] == 26)

            # ── DISABLE HRA in Firm Master ──
            await db.firm_masters.update_one({"company_id": CID}, {"$set": {"allowances.HRA": False}})
            # RULE5(a): saved run must NOT change without explicit Reprocess
            r = await c.get(f"{BASE}/admin/compliance-salary-runs/{run_id}", headers=H)
            r_norep = row_of(r.json().get("run") or r.json())
            chk("RULE5: disabling alone does NOT modify the saved run",
                abs(float(r_norep.get("hra") or 0) - hra1) < 0.01, r_norep.get("hra"))

            # ── REPROCESS with HRA disabled ──
            r = await c.post(f"{BASE}/admin/compliance-salary-runs/{run_id}/reprocess",
                             headers=H, json={"use_imported_sheet": True})
            chk("reprocess (HRA off) ok", r.status_code == 200, r.text[:300])
            run2 = r.json().get("run") or {}
            r2 = row_of(run2)
            hra2 = float(r2.get("hra") or 0)
            gp2 = float(r2.get("gross_paid") or 0)
            adj2 = float(r2.get("ot_pay") or 0) + float(r2.get("others") or 0)
            basic2 = float(r2.get("basic") or 0)
            print(f"    run2: hra={hra2} basic={basic2} gross_paid={gp2} adj={adj2}")
            chk("RULE1: disabled editable head calculates as 0", hra2 == 0.0, hra2)
            chk("RULE6: Basic (fixed component) untouched by the mask",
                abs(basic2 - float(r1.get("basic") or 0)) < 0.01, basic2)
            chk("RULE2: Gross Paid STILL == imported 20000 after disable",
                abs(gp2 - 20000) < 1, gp2)
            chk("RULE3: difference reallocated ONLY into OT/Other Allowance "
                "(adjustment grew by the masked HRA)",
                abs((adj2 - adj1) - hra1) < 1, f"Δadj={adj2 - adj1} vs hra={hra1}")
            emp2 = await db.users.find_one({"user_id": UID}, {"_id": 0, "salary_structure_compliance": 1})
            chk("RULE4: stored HRA=3000 SURVIVES the disable (mask is calc-only)",
                emp2 == emp0)

            # ── RE-ENABLE HRA ──
            await db.firm_masters.update_one({"company_id": CID}, {"$set": {"allowances.HRA": True}})
            r = await c.get(f"{BASE}/admin/compliance-salary-runs/{run_id}", headers=H)
            r_norep2 = row_of(r.json().get("run") or r.json())
            chk("RULE5: re-enabling alone does NOT modify the processed run",
                float(r_norep2.get("hra") or 0) == 0.0, r_norep2.get("hra"))

            # ── REPROCESS with HRA back on → restored ──
            r = await c.post(f"{BASE}/admin/compliance-salary-runs/{run_id}/reprocess",
                             headers=H, json={"use_imported_sheet": True})
            run3 = r.json().get("run") or {}
            r3 = row_of(run3)
            hra3 = float(r3.get("hra") or 0)
            gp3 = float(r3.get("gross_paid") or 0)
            adj3 = float(r3.get("ot_pay") or 0) + float(r3.get("others") or 0)
            pf3 = float(r3.get("pf") or 0)
            print(f"    run3: hra={hra3} gross_paid={gp3} adj={adj3} pf={pf3}")
            chk("RULE1/5: Reprocess RESTORES the saved allowance value",
                abs(hra3 - hra1) < 0.01, f"{hra3} vs {hra1}")
            chk("RULE2: gross back to imported 20000", abs(gp3 - 20000) < 1, gp3)
            chk("adjustment shrinks back to original", abs(adj3 - adj1) < 1,
                f"{adj3} vs {adj1}")
            chk("RULE5: statutory recalculated identically on restore",
                abs(pf3 - pf1) < 0.01, f"{pf3} vs {pf1}")
    finally:
        # full cleanup + restore
        if run_id:
            await db.compliance_salary_runs.delete_many({"run_id": run_id})
        await db.compliance_salary_runs.delete_many({"month": MONTH, "company_id": CID})
        await db.compliance_import_entries.delete_many({"company_id": CID, "month": MONTH})
        for coll in ("compliance_master_snapshots", "compliance_monthly_snapshots",
                     "freeze_salary_snapshots"):
            await db[coll].delete_many({"month": MONTH, "company_id": CID})
        await db.firm_masters.update_one({"company_id": CID},
                                         {"$set": {"allowances.HRA": orig_hra}})
        await db.user_sessions.delete_one({"session_token": tok})
    print(f"\nPASS {P} / FAIL {F} (run deleted, snapshots purged, HRA restored to {orig_hra})")

asyncio.run(main())
