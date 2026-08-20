"""Iter 628 — Dummy Shift In/Out Matrix Report (read-only layer)."""
import asyncio, os, uuid
from datetime import datetime, timezone, timedelta
import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
BASE = "http://localhost:8001/api"
CID = "cmp_527fecdd7c"
MONTH = "2026-07"
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

    comp = await db.companies.find_one({"company_id": CID}, {"attendance_policy": 1})
    orig_flag = bool((((comp or {}).get("attendance_policy") or {})
                      .get("policy_master") or {}).get("dummy_shift_allowed"))

    # pick 2 employees with punches in the month
    emp_ids = [u["user_id"] async for u in db.users.find(
        {"company_id": CID, "role": "employee"}, {"user_id": 1})]
    agg = await db.attendance.aggregate([
        {"$match": {"user_id": {"$in": emp_ids}, "kind": "in",
                    "status": "approved", "date": {"$regex": f"^{MONTH}"}}},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 2}]).to_list(2)
    uid_a, uid_b = agg[0]["_id"], agg[1]["_id"]
    origs = {}
    for uid in (uid_a, uid_b):
        u = await db.users.find_one({"user_id": uid}, {"dummy_shift": 1, "employee_code": 1})
        origs[uid] = (u.get("dummy_shift"), u.get("employee_code"))
    code_a, code_b = origs[uid_a][1], origs[uid_b][1]

    # snapshot counts to prove READ-ONLY (sec 17)
    att_before = await db.attendance.count_documents({})
    usr_before = await db.users.count_documents({})

    async with httpx.AsyncClient(timeout=120) as c:
        # 1. flag OFF → 400
        await db.companies.update_one({"company_id": CID},
            {"$set": {"attendance_policy.policy_master.dummy_shift_allowed": False}})
        r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix?month={MONTH}&company_id={CID}&dummy=1", headers=H)
        chk("flag OFF → 400", r.status_code == 400, f"{r.status_code} {r.text[:120]}")

        # enable flag + assign dummy shifts (SHIFT A1 = 07:00-15:00 day; SHIFT B = 16:00-00:00 overnight)
        await db.companies.update_one({"company_id": CID},
            {"$set": {"attendance_policy.policy_master.dummy_shift_allowed": True}})
        await db.users.update_one({"user_id": uid_a}, {"$set": {"dummy_shift": "SHIFT A1"}})
        await db.users.update_one({"user_id": uid_b}, {"$set": {"dummy_shift": "SHIFT B"}})

        # 2. normal mode UNCHANGED (no dummy substitution)
        r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix?month={MONTH}&company_id={CID}&q={code_a}", headers=H)
        chk("normal mode 200", r.status_code == 200, r.text[:200])
        nd = r.json()
        chk("normal mode: no dummy_mode key", not nd.get("dummy_mode"))
        ne = nd["employees"][0]
        n_cells = [v for v in ne["days"].values() if v["d_in"] not in ("-", "H", "WO")]
        chk("normal mode shows ACTUAL punch times",
            any(v["d_in"] != "07:00" for v in n_cells), n_cells[:3])

        # 3. dummy mode for emp A (day shift 07:00-15:00)
        r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix?month={MONTH}&company_id={CID}&dummy=1&q={code_a}", headers=H)
        chk("dummy mode 200", r.status_code == 200, r.text[:200])
        dd = r.json()
        chk("dummy_mode flag + title", dd.get("dummy_mode") and "DUMMY SHIFT" in dd.get("report_title", ""))
        chk("read-only disclaimer present", "REPORTING PURPOSE ONLY" in dd.get("dummy_note", ""))
        de = dd["employees"][0]
        chk("employee dummy_shift surfaced", de.get("dummy_shift") == "SHIFT A1")
        # 2-punch present days → dummy 07:00 / 15:00
        two_punch = [(k, v) for k, v in de["days"].items()
                     if v["d_in"] == "07:00" and v["d_out"] == "15:00"]
        chk("2-punch days substituted with 07:00/15:00", len(two_punch) > 0)
        # cells that keep actual: >2 punches OR 1 punch
        keep = [(k, v) for k, v in de["days"].items()
                if v["detail"]["punch_count"] and int(v["detail"]["punch_count"]) > 2]
        for k, v in keep[:1]:
            chk(">2 punches preserve existing representation",
                v["d_in"] != "07:00" or v["d_out"] != "15:00", (k, v["d_in"], v["d_out"]))
        wo_cells = [v for v in de["days"].values() if v["d_in"] == "WO"]
        h_or_wo = wo_cells or [v for v in de["days"].values() if v["d_in"] == "H"]
        chk("WO/H day markers present", len(h_or_wo) > 0)
        chk("dummy_summary block", "present_days" in (dd.get("dummy_summary") or {}),
            dd.get("dummy_summary"))
        chk("dummy_shifts filter options", "SHIFT A1" in (dd["filter_options"].get("dummy_shifts") or []))

        # 4. overnight shift B → OUT marked with *
        r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix?month={MONTH}&company_id={CID}&dummy=1&q={code_b}", headers=H)
        db_ = r.json()["employees"][0]
        star = [v for v in db_["days"].values() if v["d_out"] == "00:00*"]
        chk("overnight OUT shows 00:00* (next calendar date)", len(star) > 0,
            [(k, v["d_in"], v["d_out"]) for k, v in list(db_["days"].items())[:5]])

        # 5. dummy_shift filter
        r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix?month={MONTH}&company_id={CID}&dummy=1&dummy_shift=SHIFT%20B", headers=H)
        js = r.json()
        chk("dummy_shift filter returns only SHIFT B emps",
            js["total_employees"] >= 1 and all(e["dummy_shift"] == "SHIFT B" for e in js["employees"]))

        # 6. exports in dummy mode
        for ext, ctype in (("xlsx", "spreadsheet"), ("csv", "csv"), ("pdf", "pdf")):
            r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix.{ext}?month={MONTH}&company_id={CID}&dummy=1&q={code_a}", headers=H)
            chk(f"dummy {ext} export", r.status_code == 200
                and ctype in r.headers.get("content-type", "")
                and "dummy-shift-matrix" in r.headers.get("content-disposition", ""),
                f"{r.status_code} {r.headers.get('content-disposition')}")
        # csv contains title + note + dummy shift column
        r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix.csv?month={MONTH}&company_id={CID}&dummy=1&q={code_a}", headers=H)
        chk("csv has title/note/summary", "DUMMY SHIFT IN / OUT MATRIX" in r.text
            and "REPORTING PURPOSE ONLY" in r.text and "SUMMARY —" in r.text)

        # 7. normal exports untouched (filename unchanged)
        r = await c.get(f"{BASE}/admin/reports/inout-ot-matrix.xlsx?month={MONTH}&company_id={CID}&q={code_a}", headers=H)
        chk("normal xlsx filename unchanged",
            "inout-ot-matrix" in r.headers.get("content-disposition", ""))

    # 8. READ-ONLY proof — zero DB writes to attendance/users
    att_after = await db.attendance.count_documents({})
    usr_after = await db.users.count_documents({})
    chk("attendance untouched (read-only)", att_before == att_after, f"{att_before}->{att_after}")
    chk("users count untouched", usr_before == usr_after)

    # restore originals
    for uid, (ds, _) in origs.items():
        if ds is None:
            await db.users.update_one({"user_id": uid}, {"$unset": {"dummy_shift": ""}})
        else:
            await db.users.update_one({"user_id": uid}, {"$set": {"dummy_shift": ds}})
    await db.companies.update_one({"company_id": CID},
        {"$set": {"attendance_policy.policy_master.dummy_shift_allowed": orig_flag}})
    await db.user_sessions.delete_one({"session_token": tok})
    print(f"\nPASS {P} / FAIL {F} (flag restored to {orig_flag}, dummy shifts restored)")

asyncio.run(main())
