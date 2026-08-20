"""Iter 627 — Shift Deployment Report: Summary Only vs Full Data."""
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
    # find a date with punches for this firm
    emp_ids = [u["user_id"] async for u in db.users.find(
        {"company_id": CID, "role": "employee"}, {"user_id": 1})]
    agg = await db.attendance.aggregate([
        {"$match": {"user_id": {"$in": emp_ids}, "kind": "in", "status": "approved"}},
        {"$group": {"_id": "$date", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 1}]).to_list(1)
    if not agg:
        print("NO punch data for firm — abort"); return
    d = agg[0]["_id"]
    print(f"Using date {d} ({agg[0]['n']} in-punches)")
    body = lambda so, fmt="json": {"company_id": CID, "report_key": "shift_deployment",
        "format": fmt, "filters": {"from_date": d, "to_date": d,
                                   **({"summary_only": True} if so else {})}}
    async with httpx.AsyncClient(timeout=120) as c:
        # 1. Full data (default) unchanged
        r = await c.post(f"{BASE}/admin/labour-reports/generate", headers=H, json=body(False))
        chk("full-data 200", r.status_code == 200, r.text[:200])
        full = r.json()
        chk("full-data has employee rows", len(full.get("rows", [])) > 2)
        chk("full-data cols unchanged", full["columns"][0] == "S.No." and "Employee Name" in full["columns"])
        # 2. Summary only
        r = await c.post(f"{BASE}/admin/labour-reports/generate", headers=H, json=body(True))
        chk("summary 200", r.status_code == 200, r.text[:200])
        s = r.json()
        cols, rows = s["columns"], s["rows"]
        chk("summary cols", cols == ["S.No.", "Department / Designation", "Deployed",
                                     "Present", "Half Day", "Hours", "OT Hrs", "Cost"], cols)
        chk("label — Summary Only", "Summary Only" in (s.get("report_label") or s.get("label") or ""),
            s.get("report_label") or s.get("label"))
        bands = [r0 for r0 in rows if str(r0[0]).startswith("▶")]
        chk("2 sections (Dept + Desig)", len(bands) == 2, bands)
        chk("dept section first", "DEPARTMENT" in str(bands[0][0]) if bands else False)
        chk("desig section second", "DESIGNATION" in str(bands[1][0]) if len(bands) > 1 else False)
        totals = [r0 for r0 in rows if str(r0[0]).startswith("GRAND TOTAL")]
        chk("2 grand totals", len(totals) == 2, totals)
        # no individual employee rows: every non-band/total row is a group row
        grp_rows = [r0 for r0 in rows if not str(r0[0]).startswith(("▶", "GRAND"))]
        chk("summary far fewer rows than full", len(rows) < len(full["rows"]),
            f"{len(rows)} vs {len(full['rows'])}")
        chk("group rows have numeric S.No.", all(isinstance(r0[0], int) for r0 in grp_rows))
        # dept section totals equal desig section totals (same employees)
        if len(totals) == 2:
            chk("dept vs desig totals match", totals[0][2:] == totals[1][2:],
                f"{totals[0]} vs {totals[1]}")
        # deployed sum sanity: full data GRAND TOTAL deployed count matches
        full_gt = [r0 for r0 in full["rows"] if str(r0[0]).startswith("GRAND TOTAL")]
        if full_gt and totals:
            n_full = int(str(full_gt[0][0]).split("·")[1].strip().split()[0])
            chk("deployed matches full-data grand total", totals[0][2] == n_full,
                f"{totals[0][2]} vs {n_full}")
        for r0 in rows[:8]:
            print("   ", r0)
        # 3. downloads work in summary mode
        for f in ("pdf", "excel", "csv"):
            r = await c.post(f"{BASE}/admin/labour-reports/generate", headers=H, json=body(True, f))
            chk(f"summary {f} download", r.status_code == 200 and len(r.json().get("file_base64", "")) > 100,
                r.text[:150])
        # 4. summary over a period (multi-day) works
        r = await c.post(f"{BASE}/admin/labour-reports/generate", headers=H, json={
            "company_id": CID, "report_key": "shift_deployment", "format": "json",
            "filters": {"from_date": d[:8] + "01", "to_date": d, "summary_only": True}})
        chk("summary multi-day 200", r.status_code == 200, r.text[:200])
    await db.user_sessions.delete_one({"session_token": tok})
    print(f"\nPASS {P} / FAIL {F}")

asyncio.run(main())
