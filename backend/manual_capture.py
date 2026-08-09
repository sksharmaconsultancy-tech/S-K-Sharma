"""Iter 531/532 — Re-capture REAL portal screenshots for the User Manual.

Rules (user directives):
  * NEVER save an error screen (red overlay / crash page).
  * NEVER save a blank/empty-state screen — screens are captured WITH
    data. Temporary SAMPLE records (tagged ``manual_sample: True``) are
    seeded for Leave / ESIC Leave before capture and removed afterwards.
  * Data-driven params: the payslip/OT captures use the latest month
    that actually has a salary run.

Usage:  python manual_capture.py --base <portal-url> --token <session-token>
Writes PNGs to backend/assets/manual/ plus .last_capture.json metadata.
"""
import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BACKEND_DIR, "assets", "manual")

ERROR_MARKERS = ("Uncaught Error", "Call Stack", "Component Stack",
                 "Something went wrong", "Cannot read properties")
BLANK_MARKERS = ("No data for this month", "No leave requests",
                 "No OT recorded", "Missing employee",
                 "No records found", "No employees found",
                 "No ESIC leave entries", "Nothing here yet")


def _db():
    from dotenv import load_dotenv
    from pymongo import MongoClient
    load_dotenv(os.path.join(BACKEND_DIR, ".env"))
    return MongoClient(os.environ["MONGO_URL"])[
        os.environ.get("DB_NAME", "test_database")]


def _context(db) -> dict:
    """Pick the demo firm + employees + the month that HAS payroll data."""
    run = db.compliance_salary_runs.find_one(
        {"company_id": {"$ne": None}}, sort=[("month", -1)])
    cid = (run or {}).get("company_id")
    month = (run or {}).get("month") or date.today().strftime("%Y-%m")
    emps = list(db.users.find(
        {"company_id": cid, "role": "employee"},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1,
         "employee_code": 1}).limit(5))
    return {"company_id": cid, "month": month, "emps": emps,
            "payslip_uid": emps[0]["user_id"] if emps else ""}


def _best_payslip_uid(_base: str, token: str, ctx: dict) -> str:
    """Employee with the MOST present days (live punch-based payroll run)
    so the payslip capture is data-rich, never blank/zero."""
    import urllib.request
    m = ctx["month"]
    # call the backend directly — the script always runs on the server host
    api_base = os.environ.get("MANUAL_API_BASE", "http://localhost:8001")
    url = (f"{api_base}/api/admin/payroll/run?year={int(m[:4])}"
           f"&month={int(m[5:7])}&company_id={ctx['company_id']}")
    try:
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"})
        rows = json.loads(urllib.request.urlopen(
            req, timeout=60).read()).get("rows") or []
        rows.sort(key=lambda r: -(float(r.get("present_days") or 0)
                                  + 0.5 * float(r.get("half_days") or 0)))
        if rows and float(rows[0].get("present_days") or 0) > 0:
            return rows[0]["user_id"]
    except Exception as e:  # noqa: BLE001
        print("payslip pick fallback:", str(e)[:70])
    return ctx["payslip_uid"]


def seed_samples(db, ctx) -> None:
    """Temporary SAMPLE data so Leave/ESIC screens never capture blank."""
    m = ctx["month"]
    emps = ctx["emps"]
    if not emps:
        return
    # the employee used for the Employee Quick Guide must ALSO have a
    # sample leave so their "My Leave" capture is never blank
    star = db.users.find_one(
        {"user_id": ctx.get("payslip_uid")},
        {"_id": 0, "user_id": 1, "name": 1, "email": 1,
         "employee_code": 1})
    pick = ([star] if star else []) + emps
    leaves = []
    for i, (lt, d0, d1) in enumerate((("casual", 3, 4), ("sick", 10, 12),
                                      ("earned", 18, 20))):
        e = pick[i % len(pick)]
        leaves.append({
            "leave_id": f"lv_{uuid.uuid4().hex[:12]}",
            "user_id": e["user_id"], "company_id": ctx["company_id"],
            "user_name": e.get("name"), "user_email": e.get("email"),
            "leave_type": lt, "from_date": f"{m}-{d0:02d}",
            "to_date": f"{m}-{d1:02d}",
            "reason": "Sample entry (user manual)", "status": "approved",
            "admin_comment": None, "decided_by": "Manual Generator",
            "created_at": datetime.now().isoformat(),
            "manual_sample": True})
    db.leaves.insert_many(leaves)
    e = emps[0]
    db.esic_leaves.insert_one({
        "entry_id": f"esl_{uuid.uuid4().hex[:12]}",
        "company_id": ctx["company_id"], "user_id": e["user_id"],
        "employee_name": e.get("name"),
        "employee_code": e.get("employee_code"),
        "from_date": f"{m}-08", "to_date": f"{m}-09", "days": 2.0,
        "remarks": "Sample entry (user manual)", "reason": "Sickness",
        "has_certificate": False, "status": "pending",
        "created_by_name": "Manual Generator",
        "created_at": datetime.now().isoformat(),
        "manual_sample": True})


def cleanup_samples(db) -> None:
    db.leaves.delete_many({"manual_sample": True})
    db.esic_leaves.delete_many({"manual_sample": True})


def _page_problem(pg) -> str:
    """Return a marker string if the page shows an error OR a blank
    empty-state — such captures are never saved."""
    try:
        body = pg.inner_text("body", timeout=3000)[:6000]
    except Exception:  # noqa: BLE001
        return ""
    for mk in ERROR_MARKERS:
        if mk in body:
            return f"error: {mk}"
    for mk in BLANK_MARKERS:
        if mk in body:
            return f"blank: {mk}"
    return ""


def _employee_ctx(db, ctx) -> dict:
    """Pick an onboarded employee for the Employee Quick Guide captures
    and mint a TEMPORARY session for them (removed after capture)."""
    q = {"company_id": ctx["company_id"], "role": "employee",
         "onboarded": True, "active": {"$ne": False}}
    emp = (db.users.find_one({**q, "user_id": ctx["payslip_uid"]})
           or db.users.find_one(q))
    if not emp:
        return {}
    tok = f"manual_emp_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "session_token": tok, "user_id": emp["user_id"],
        "created_at": datetime.now().isoformat(),
        "expires_at": datetime.utcnow() + timedelta(hours=1),
        "manual_sample": True})
    return {"token": tok, "user_id": emp["user_id"],
            "name": emp.get("name")}


def capture_employee(b, base: str, emp: dict, ok: list, fail: list,
                     month: str = "") -> None:
    """Phone-size (390x844) captures of the EMPLOYEE app for the
    Employee Quick Guide."""
    vp = {"width": 390, "height": 844}
    # employee landing / sign-in (unauthenticated)
    cx = b.new_context(viewport=vp)
    lp = cx.new_page()
    try:
        lp.goto(base + "/", wait_until="domcontentloaded", timeout=60000)
        lp.wait_for_timeout(5000)
        if not _page_problem(lp):
            lp.screenshot(path=f"{OUT}/emp_login.png")
            ok.append("emp_login")
    except Exception as e:  # noqa: BLE001
        fail.append(f"emp_login: {str(e)[:80]}")
    cx.close()
    if not emp.get("token"):
        fail.append("employee captures skipped: no onboarded employee")
        return
    cx = b.new_context(viewport=vp)
    cx.add_init_script(
        "window.localStorage.setItem('llc_session_token', "
        f"'{emp['token']}');")
    pg = cx.new_page()
    mq = (f"?month={int(month[5:7])}&year={int(month[:4])}"
          if len(month) == 7 else "")
    for name, route, wait_ms in (
            ("emp_home", "/", 9000),
            ("emp_attendance", "/attendance", 8000),
            ("emp_leave", "/leave", 7000),
            ("emp_payslip", f"/payslip{mq}", 8000),
            ("emp_profile", "/profile", 7000)):
        try:
            pg.goto(base + route, wait_until="domcontentloaded",
                    timeout=60000)
            pg.wait_for_timeout(wait_ms)
            problem = _page_problem(pg)
            if problem:
                fail.append(f"{name}: {problem}")
                continue
            pg.screenshot(path=f"{OUT}/{name}.png")
            ok.append(name)
        except Exception as e:  # noqa: BLE001
            fail.append(f"{name}: {str(e)[:80]}")
    cx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    args = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2
    os.makedirs(OUT, exist_ok=True)
    db = _db()
    ctx = _context(db)
    ctx["payslip_uid"] = _best_payslip_uid(args.base, args.token, ctx)
    m = ctx["month"]
    mm, yy = int(m[5:7]), int(m[:4])
    # (name, route, wait_ms, click_text_or_None)
    shots = [
        ("dashboard", "/", 8000, None),
        ("firm_master", "/companies", 6000, None),
        ("employee_master", "/admin", 9000, None),
        ("attendance", "/attendance-grid", 9000, None),
        ("biometric", "/biometric-devices", 6000, None),
        ("leave", "/leaves", 6000, "All requests"),
        ("esic_leave", "/esic-leave", 7000, None),
        ("overtime", "/ot-report", 6000, m),
        ("compliance_salary", "/compliance-salary-run", 8000, None),
        ("actual_salary", "/salary-run", 7000, None),
        ("payslip",
         f"/payslip?user_id={ctx['payslip_uid']}&month={mm}&year={yy}",
         8000, None),
        ("bank", "/bank-transfer", 6000, None),
        ("reports", "/reports-center", 7000, None),
        ("monthly_payroll", "/monthly-payroll-report", 9000, None),
    ]
    ok, fail = [], []
    seed_samples(db, ctx)
    emp = _employee_ctx(db, ctx)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            cx = b.new_context(viewport={"width": 1440, "height": 900})
            cx.add_init_script(
                "window.localStorage.setItem('llc_session_token', "
                f"'{args.token}');")
            pg = cx.new_page()
            # unauthenticated login screen
            cx2 = b.new_context(viewport={"width": 1440, "height": 900})
            lp = cx2.new_page()
            try:
                lp.goto(args.base + "/admin-pin-login",
                        wait_until="domcontentloaded", timeout=60000)
                lp.wait_for_timeout(4000)
                if not _page_problem(lp):
                    lp.screenshot(path=f"{OUT}/login.png")
                    ok.append("login")
            except Exception as e:  # noqa: BLE001
                fail.append(f"login: {str(e)[:80]}")
            cx2.close()
            for name, route, wait_ms, click in shots:
                try:
                    pg.goto(args.base + route,
                            wait_until="domcontentloaded", timeout=60000)
                    pg.wait_for_timeout(wait_ms)
                    if click:
                        try:
                            pg.get_by_text(click, exact=True).first.click(
                                force=True, timeout=5000)
                            pg.wait_for_timeout(4000)
                        except Exception:  # noqa: BLE001
                            pass
                    problem = _page_problem(pg)
                    if problem:
                        # keep the previous GOOD screenshot on disk
                        fail.append(f"{name}: {problem}")
                        continue
                    pg.screenshot(path=f"{OUT}/{name}.png")
                    ok.append(name)
                except Exception as e:  # noqa: BLE001
                    fail.append(f"{name}: {str(e)[:80]}")
            capture_employee(b, args.base, emp, ok, fail, month=m)
            b.close()
    finally:
        cleanup_samples(db)
        db.user_sessions.delete_many({"manual_sample": True})
    with open(f"{OUT}/.last_capture.json", "w") as f:
        json.dump({"at": datetime.now().isoformat(timespec="seconds"),
                   "month_used": m, "ok": ok, "failed": fail}, f)
    print(f"captured {len(ok)} ok, {len(fail)} skipped/failed: {fail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
