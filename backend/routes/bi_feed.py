"""BI & Data Feed — live data endpoints for Power BI / Excel Power Query.

Admin side:
  GET  /api/admin/bi-feed/info?company_id=   — current key + feed URLs
  POST /api/admin/bi-feed/rotate-key         — generate / rotate the feed key

Public (key-authenticated, read-only JSON) — paste into Power BI's Web
connector or Excel → Get Data → From Web:
  GET /api/bi-feed/employees?key=...
  GET /api/bi-feed/attendance?key=...&month=YYYY-MM
  GET /api/bi-feed/salary?key=...&month=YYYY-MM
  GET /api/bi-feed/compliance?key=...&month=YYYY-MM

Sensitive PII (Aadhaar, PAN, bank account numbers, salaries structure) is
NOT exposed on the employees dataset.
"""
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api", tags=["bi-feed"])


class RotateBody(BaseModel):
    company_id: str


def _scope_cid(admin: dict, company_id: Optional[str]) -> str:
    if admin["role"] == "company_admin":
        return admin.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id required")
    return company_id


@router.get("/admin/bi-feed/info")
async def bi_feed_info(company_id: Optional[str] = None,
                       authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = _scope_cid(admin, company_id)
    c = await db.companies.find_one({"company_id": cid},
                                    {"_id": 0, "name": 1, "bi_feed_key": 1})
    if not c:
        raise HTTPException(status_code=404, detail="Firm not found")
    return {"company_id": cid, "firm_name": c.get("name"),
            "key": c.get("bi_feed_key") or None,
            "datasets": ["employees", "attendance", "salary", "compliance"]}


@router.post("/admin/bi-feed/rotate-key")
async def bi_feed_rotate(body: RotateBody,
                         authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    cid = _scope_cid(admin, body.company_id)
    key = f"bif_{secrets.token_hex(20)}"
    r = await db.companies.update_one(
        {"company_id": cid},
        {"$set": {"bi_feed_key": key, "bi_feed_key_rotated_at": now_iso()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Firm not found")
    return {"ok": True, "key": key}


async def _company_for_key(key: str) -> dict:
    if not key or not key.startswith("bif_"):
        raise HTTPException(status_code=401, detail="Invalid feed key")
    c = await db.companies.find_one({"bi_feed_key": key},
                                    {"_id": 0, "company_id": 1, "name": 1})
    if not c:
        raise HTTPException(status_code=401, detail="Invalid feed key")
    return c


@router.get("/bi-feed/employees")
async def feed_employees(key: str = Query(...)):
    c = await _company_for_key(key)
    rows = await db.users.find(
        {"role": "employee", "company_id": c["company_id"]},
        {"_id": 0, "employee_code": 1, "name": 1, "father_name": 1,
         "designation": 1, "department": 1, "employee_type": 1,
         "doj": 1, "dob": 1, "gender": 1, "active": 1, "pay_mode": 1,
         "bank_name": 1, "shift_name": 1}).to_list(10000)
    for r in rows:
        r["status"] = "Active" if r.pop("active", True) is not False else "Resigned"
    return {"firm": c["name"], "count": len(rows), "rows": rows}


@router.get("/bi-feed/attendance")
async def feed_attendance(key: str = Query(...), month: str = Query(...)):
    c = await _company_for_key(key)
    punches = await db.attendance.find(
        {"company_id": c["company_id"], "date": {"$regex": f"^{month}"},
         "status": {"$ne": "rejected"}},
        {"_id": 0, "user_id": 1, "date": 1, "kind": 1, "at": 1, "source": 1},
    ).to_list(200000)
    users: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({"role": "employee", "company_id": c["company_id"]},
                                 {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1}):
        users[u["user_id"]] = u
    day: Dict[tuple, Dict[str, Any]] = {}
    for p in punches:
        k = (p["user_id"], p["date"])
        d = day.setdefault(k, {"first_in": None, "last_out": None})
        t = (p.get("at") or "")[11:19]
        if p.get("kind") == "in" and (d["first_in"] is None or t < d["first_in"]):
            d["first_in"] = t
        if p.get("kind") == "out" and (d["last_out"] is None or t > d["last_out"]):
            d["last_out"] = t
    rows: List[Dict[str, Any]] = []
    for (uid, date), d in sorted(day.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        u = users.get(uid, {})
        hours = None
        if d["first_in"] and d["last_out"] and d["last_out"] > d["first_in"]:
            h1, m1 = int(d["first_in"][:2]), int(d["first_in"][3:5])
            h2, m2 = int(d["last_out"][:2]), int(d["last_out"][3:5])
            hours = round(((h2 * 60 + m2) - (h1 * 60 + m1)) / 60, 2)
        rows.append({"date": date, "employee_code": u.get("employee_code"),
                     "name": u.get("name"), "in_time": d["first_in"],
                     "out_time": d["last_out"], "work_hours": hours})
    return {"firm": c["name"], "month": month, "count": len(rows), "rows": rows}


def _flatten_run_rows(run: dict, users: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in run.get("rows", []):
        u = users.get(r.get("user_id"), {})
        out.append({
            "employee_code": u.get("employee_code") or r.get("employee_code"),
            "name": u.get("name") or r.get("name"),
            "present_days": r.get("present_days"),
            "ot_hours": r.get("ot_hours"),
            "gross": r.get("gross"),
            "basic": r.get("basic"),
            "pf": r.get("pf"),
            "esi": r.get("esi"),
            "total_deductions": r.get("total_deductions") or r.get("deductions_total"),
            "net": r.get("net"),
        })
    return out


async def _users_map(cid: str) -> Dict[str, Dict[str, Any]]:
    users: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find({"role": "employee", "company_id": cid},
                                 {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1}):
        users[u["user_id"]] = u
    return users


@router.get("/bi-feed/salary")
async def feed_salary(key: str = Query(...), month: str = Query(...)):
    c = await _company_for_key(key)
    run = await db.salary_runs.find_one(
        {"company_id": c["company_id"], "month": month}, {"_id": 0},
        sort=[("created_at", -1)])
    if not run:
        return {"firm": c["name"], "month": month, "count": 0, "rows": []}
    rows = _flatten_run_rows(run, await _users_map(c["company_id"]))
    return {"firm": c["name"], "month": month, "count": len(rows), "rows": rows}


@router.get("/bi-feed/compliance")
async def feed_compliance(key: str = Query(...), month: str = Query(...)):
    c = await _company_for_key(key)
    run = await db.compliance_salary_runs.find_one(
        {"company_id": c["company_id"], "month": month}, {"_id": 0},
        sort=[("created_at", -1)])
    if not run:
        return {"firm": c["name"], "month": month, "count": 0, "rows": []}
    rows = _flatten_run_rows(run, await _users_map(c["company_id"]))
    return {"firm": c["name"], "month": month, "count": len(rows), "rows": rows}
