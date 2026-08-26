"""Iter 733 — BRANCH EXTRAS (user request, 5 features):
1. Branch-wise Budget vs Actual (P&L) — actual from existing compliance
   runs (engine untouched, reporting only).
2. Branch pending approvals — leaves + advances of a branch's employees.
3. Inter-branch movement register — transfers + temp assignments.
4. Branch-wise PF/ESIC split — latest compliance run grouped by branch.
5. STATE-WISE STATUTORY RULES — per-state PT slabs, LWF, minimum wages
   (editable master, seeded defaults) + monthly compliance report that
   maps each employee via branch → state. REPORT-ONLY: does not alter
   the compliance salary engine.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query

from server import db, get_user_from_token, now_iso, sub_admin_can_touch_company  # noqa: E402
from routes.statutory_extra_reports import _emit, _company, _num  # noqa: E402

router = APIRouter(prefix="/api/admin/branch-extras", tags=["branch-extras"])

# Seeded defaults (approx FY 2025-26 — admin can edit; verify latest
# state notifications before filing).
STATE_DEFAULTS = {
    "Rajasthan": {"pt_slabs": [], "lwf_employee": 0, "lwf_employer": 0,
                  "lwf_frequency": "none", "min_wage_daily": {"unskilled": 266, "semi_skilled": 278, "skilled": 290, "highly_skilled": 340}},
    "Maharashtra": {"pt_slabs": [[0, 7500, 0], [7501, 10000, 175], [10001, 999999999, 200]],
                    "lwf_employee": 25, "lwf_employer": 75, "lwf_frequency": "half_yearly",
                    "min_wage_daily": {"unskilled": 477, "semi_skilled": 500, "skilled": 523, "highly_skilled": 546}},
    "Karnataka": {"pt_slabs": [[0, 24999, 0], [25000, 999999999, 200]],
                  "lwf_employee": 50, "lwf_employer": 100, "lwf_frequency": "yearly",
                  "min_wage_daily": {"unskilled": 500, "semi_skilled": 520, "skilled": 540, "highly_skilled": 560}},
    "Gujarat": {"pt_slabs": [[0, 12000, 0], [12001, 999999999, 200]],
                "lwf_employee": 6, "lwf_employer": 12, "lwf_frequency": "half_yearly",
                "min_wage_daily": {"unskilled": 450, "semi_skilled": 460, "skilled": 470, "highly_skilled": 480}},
    "Madhya Pradesh": {"pt_slabs": [[0, 18750, 0], [18751, 25000, 125], [25001, 33333, 167], [33334, 999999999, 208]],
                       "lwf_employee": 10, "lwf_employer": 30, "lwf_frequency": "half_yearly",
                       "min_wage_daily": {"unskilled": 393, "semi_skilled": 427, "skilled": 486, "highly_skilled": 536}},
    "West Bengal": {"pt_slabs": [[0, 10000, 0], [10001, 15000, 110], [15001, 25000, 130], [25001, 40000, 150], [40001, 999999999, 200]],
                    "lwf_employee": 3, "lwf_employer": 15, "lwf_frequency": "half_yearly",
                    "min_wage_daily": {"unskilled": 397, "semi_skilled": 437, "skilled": 481, "highly_skilled": 529}},
    "Tamil Nadu": {"pt_slabs": [[0, 21000, 0], [21001, 30000, 135], [30001, 45000, 315], [45001, 60000, 690], [60001, 75000, 1025], [75001, 999999999, 1250]],
                   "lwf_employee": 20, "lwf_employer": 40, "lwf_frequency": "yearly",
                   "min_wage_daily": {"unskilled": 400, "semi_skilled": 420, "skilled": 440, "highly_skilled": 460}},
    "Telangana": {"pt_slabs": [[0, 15000, 0], [15001, 20000, 150], [20001, 999999999, 200]],
                  "lwf_employee": 10, "lwf_employer": 30, "lwf_frequency": "yearly",
                  "min_wage_daily": {"unskilled": 400, "semi_skilled": 420, "skilled": 440, "highly_skilled": 460}},
    "Andhra Pradesh": {"pt_slabs": [[0, 15000, 0], [15001, 20000, 150], [20001, 999999999, 200]],
                       "lwf_employee": 30, "lwf_employer": 70, "lwf_frequency": "yearly",
                       "min_wage_daily": {"unskilled": 400, "semi_skilled": 420, "skilled": 440, "highly_skilled": 460}},
    "Delhi": {"pt_slabs": [], "lwf_employee": 0.75, "lwf_employer": 2.25, "lwf_frequency": "half_yearly",
              "min_wage_daily": {"unskilled": 712, "semi_skilled": 784, "skilled": 862, "highly_skilled": 862}},
    "Haryana": {"pt_slabs": [], "lwf_employee": 31, "lwf_employer": 62, "lwf_frequency": "monthly",
                "min_wage_daily": {"unskilled": 420, "semi_skilled": 441, "skilled": 486, "highly_skilled": 510}},
}


async def _authz(authorization, company_id=None):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "company_admin":
        company_id = admin.get("company_id")
    if admin.get("role") == "sub_admin" and company_id:
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id required")
    return admin, company_id


async def _latest_run(company_id, month):
    return await db.compliance_salary_runs.find_one(
        {"company_id": company_id, "month": month},
        {"_id": 0, "rows": 1, "run_id": 1, "status": 1},
        sort=[("generated_at", -1)])


async def _branch_of_users(company_id):
    """user_id → branch name (home_branch_id → branches, else users.branch)."""
    branches = {b["branch_id"]: b for b in await db.branches.find(
        {}, {"_id": 0, "branch_id": 1, "name": 1, "state": 1}).to_list(500)}
    out = {}
    async for u in db.users.find({"company_id": company_id, "role": "employee"},
                                 {"_id": 0, "user_id": 1, "home_branch_id": 1, "branch": 1}):
        b = branches.get(u.get("home_branch_id"))
        out[u["user_id"]] = {"branch": (b or {}).get("name") or u.get("branch") or "Main",
                             "state": (b or {}).get("state") or ""}
    return out


# ── 1. BUDGET vs ACTUAL ──
@router.post("/budget")
async def set_budget(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, payload.get("company_id"))
    branch = (payload.get("branch") or "").strip() or "Main"
    month = str(payload.get("month") or "")[:7]
    await db.branch_budgets.update_one(
        {"company_id": company_id, "branch": branch, "month": month},
        {"$set": {"budget": _num(payload.get("budget")), "updated_at": now_iso()}},
        upsert=True)
    return {"ok": True}


@router.get("/pnl")
async def branch_pnl(company_id: Optional[str] = Query(None), month: str = Query(...),
                     fmt: str = Query("json"), authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    run = await _latest_run(company_id, month)
    umap = await _branch_of_users(company_id)
    actual: dict = {}
    for r in (run or {}).get("rows") or []:
        br = r.get("branch_name") or umap.get(r.get("user_id"), {}).get("branch") or "Main"
        a = actual.setdefault(br, {"gross": 0.0, "net": 0.0, "count": 0})
        a["gross"] += _num(r.get("gross_paid") or r.get("monthly_gross"))
        a["net"] += _num(r.get("net_payable") or r.get("net_salary"))
        a["count"] += 1
    budgets = {b["branch"]: _num(b.get("budget")) async for b in db.branch_budgets.find(
        {"company_id": company_id, "month": month}, {"_id": 0})}
    rows = []
    for br in sorted(set(list(actual.keys()) + list(budgets.keys()))):
        a = actual.get(br, {"gross": 0.0, "net": 0.0, "count": 0})
        bud = budgets.get(br, 0.0)
        rows.append({"branch": br, "employees": a["count"], "budget": round(bud, 2),
                     "actual_gross": round(a["gross"], 2),
                     "variance": round(bud - a["gross"], 2),
                     "utilization_pct": round(a["gross"] / bud * 100, 1) if bud else None})
    if fmt == "json":
        return {"rows": rows, "run_found": bool(run)}
    cols = [("Branch", "branch", False), ("Employees", "employees", False),
            ("Budget", "budget", True), ("Actual Gross", "actual_gross", True),
            ("Variance", "variance", True), ("Util %", "utilization_pct", False)]
    return _emit(fmt, title=f"Branch Budget vs Actual — {month}", subtitle="",
                 company=await _company(company_id), cols=cols, rows=rows,
                 fname_base=f"Branch_PnL_{month}")


# ── 2. BRANCH PENDING APPROVALS ──
@router.get("/pending-approvals")
async def branch_pending(company_id: Optional[str] = Query(None),
                         branch: Optional[str] = Query(None),
                         authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    umap = await _branch_of_users(company_id)
    uids = [uid for uid, m in umap.items() if not branch or m["branch"] == branch]
    names = {u["user_id"]: u.get("name") async for u in db.users.find(
        {"user_id": {"$in": uids}}, {"_id": 0, "user_id": 1, "name": 1})}
    out = []
    async for lv in db.leaves.find({"user_id": {"$in": uids}, "status": "pending"},
                                   {"_id": 0}).limit(300):
        out.append({"type": "Leave", "employee": names.get(lv["user_id"]),
                    "branch": umap.get(lv["user_id"], {}).get("branch"),
                    "detail": f"{lv.get('leave_type')} {lv.get('from_date')} → {lv.get('to_date')}",
                    "at": lv.get("created_at")})
    async for ad in db.advances.find({"user_id": {"$in": uids}, "status": "pending"},
                                     {"_id": 0}).limit(300):
        out.append({"type": "Advance", "employee": names.get(ad["user_id"]),
                    "branch": umap.get(ad["user_id"], {}).get("branch"),
                    "detail": f"₹{ad.get('amount')}", "at": ad.get("created_at")})
    return {"pending": out}


# ── 3. INTER-BRANCH MOVEMENTS ──
@router.get("/movements")
async def branch_movements(company_id: Optional[str] = Query(None),
                           month: Optional[str] = Query(None),
                           fmt: str = Query("json"),
                           authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    q: dict = {"company_id": company_id}
    rows = []
    for coll, kind in (("branch_transfers", "Permanent Transfer"),
                       ("branch_temp_assignments", "Temporary Assignment")):
        async for t in db[coll].find(q, {"_id": 0}).sort("created_at", -1).limit(500):
            eff = t.get("effective_date") or t.get("from_date") or ""
            if month and not str(eff).startswith(month):
                continue
            rows.append({"kind": kind, "employee": t.get("employee_name") or t.get("user_id"),
                         "from_branch": t.get("from_branch_name") or t.get("from_branch") or "-",
                         "to_branch": t.get("to_branch_name") or t.get("to_branch") or "-",
                         "effective": eff, "till": t.get("to_date") or "-",
                         "by": t.get("created_by") or "-", "status": t.get("status") or "active"})
    if fmt == "json":
        return {"rows": rows}
    cols = [("Type", "kind", False), ("Employee", "employee", False),
            ("From", "from_branch", False), ("To", "to_branch", False),
            ("Effective", "effective", False), ("Till", "till", False),
            ("By", "by", False), ("Status", "status", False)]
    return _emit(fmt, title=f"Inter-Branch Movement Register{' — ' + month if month else ''}",
                 subtitle="", company=await _company(company_id), cols=cols,
                 rows=rows, fname_base="Branch_Movements")


# ── 4. BRANCH-WISE PF/ESIC SPLIT ──
@router.get("/pf-esic-split")
async def pf_esic_split(company_id: Optional[str] = Query(None), month: str = Query(...),
                        fmt: str = Query("json"), authorization: Optional[str] = Header(None)):
    _, company_id = await _authz(authorization, company_id)
    run = await _latest_run(company_id, month)
    if not run:
        return {"rows": [], "run_found": False} if fmt == "json" else \
            HTTPException(status_code=404, detail="No salary run for month")
    umap = await _branch_of_users(company_id)
    agg: dict = {}
    for r in run.get("rows") or []:
        br = r.get("branch_name") or umap.get(r.get("user_id"), {}).get("branch") or "Main"
        a = agg.setdefault(br, {"count": 0, "pf_wages": 0.0, "pf_employee": 0.0,
                                "pf_employer": 0.0, "esic_wages": 0.0,
                                "esic_employee": 0.0, "esic_employer": 0.0})
        a["count"] += 1
        a["pf_wages"] += _num(r.get("pf_wages"))
        a["pf_employee"] += _num(r.get("pf_employee")) + _num(r.get("vpf_amount"))
        a["pf_employer"] += _num(r.get("pf_employer_total"))
        a["esic_wages"] += _num(r.get("esic_wage_base"))
        a["esic_employee"] += _num(r.get("esic_employee"))
        a["esic_employer"] += _num(r.get("esic_employer"))
    rows = [{"branch": br, **{k: round(v, 2) if isinstance(v, float) else v
                              for k, v in a.items()}} for br, a in sorted(agg.items())]
    if fmt == "json":
        return {"rows": rows, "run_found": True}
    cols = [("Branch", "branch", False), ("Emp", "count", False),
            ("PF Wages", "pf_wages", True), ("PF EE", "pf_employee", True),
            ("PF ER", "pf_employer", True), ("ESIC Wages", "esic_wages", True),
            ("ESIC EE", "esic_employee", True), ("ESIC ER", "esic_employer", True)]
    return _emit(fmt, title=f"Branch-wise PF/ESIC Split — {month}", subtitle="",
                 company=await _company(company_id), cols=cols, rows=rows,
                 fname_base=f"Branch_PF_ESIC_{month}")


# ── 5. STATE-WISE STATUTORY ──
@router.get("/states")
async def list_states(authorization: Optional[str] = Header(None)):
    await get_user_from_token(authorization)
    custom = {c["state"]: c async for c in db.state_compliance.find({}, {"_id": 0})}
    out = []
    for st in sorted(set(list(STATE_DEFAULTS.keys()) + list(custom.keys()))):
        cfg = custom.get(st) or {"state": st, **STATE_DEFAULTS.get(st, {})}
        cfg.setdefault("state", st)
        out.append(cfg)
    return {"states": out}


@router.post("/states")
async def save_state(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    state = (payload.get("state") or "").strip()
    if not state:
        raise HTTPException(status_code=400, detail="state required")
    cfg = {"state": state,
           "pt_slabs": payload.get("pt_slabs") or [],
           "lwf_employee": _num(payload.get("lwf_employee")),
           "lwf_employer": _num(payload.get("lwf_employer")),
           "lwf_frequency": payload.get("lwf_frequency") or "none",
           "min_wage_daily": payload.get("min_wage_daily") or {},
           "updated_by": admin.get("name"), "updated_at": now_iso()}
    await db.state_compliance.update_one({"state": state}, {"$set": cfg}, upsert=True)
    return {"ok": True}


@router.post("/branch-state")
async def set_branch_state(payload: dict = Body(...), authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    branch_id = payload.get("branch_id")
    state = (payload.get("state") or "").strip()
    if not (branch_id and state):
        raise HTTPException(status_code=400, detail="branch_id & state required")
    await db.branches.update_one({"branch_id": branch_id}, {"$set": {"state": state}})
    return {"ok": True}


def _pt_for(gross, slabs):
    for lo, hi, amt in slabs or []:
        if lo <= gross <= hi:
            return float(amt)
    return 0.0


@router.get("/state-report")
async def state_statutory_report(company_id: Optional[str] = Query(None),
                                 month: str = Query(...), fmt: str = Query("json"),
                                 default_state: str = Query("Rajasthan"),
                                 authorization: Optional[str] = Header(None)):
    """Per-employee PT / LWF / minimum-wage check by branch state.
    REPORTING ONLY — compliance salary engine untouched."""
    _, company_id = await _authz(authorization, company_id)
    run = await _latest_run(company_id, month)
    umap = await _branch_of_users(company_id)
    custom = {c["state"]: c async for c in db.state_compliance.find({}, {"_id": 0})}

    def scfg(st):
        return custom.get(st) or {"state": st, **STATE_DEFAULTS.get(st, {})}
    rows = []
    tot_pt = tot_lwf_e = tot_lwf_r = 0.0
    for r in (run or {}).get("rows") or []:
        m = umap.get(r.get("user_id")) or {}
        st = m.get("state") or default_state
        cfg = scfg(st)
        gross = _num(r.get("gross_paid") or r.get("monthly_gross"))
        pt = _pt_for(gross, cfg.get("pt_slabs"))
        lwf_e = _num(cfg.get("lwf_employee")) if cfg.get("lwf_frequency") == "monthly" else 0.0
        lwf_r = _num(cfg.get("lwf_employer")) if cfg.get("lwf_frequency") == "monthly" else 0.0
        mw = _num((cfg.get("min_wage_daily") or {}).get("unskilled"))
        daily = round(_num(r.get("gross_master") or r.get("monthly_gross")) / 26, 2)
        below = bool(mw and daily and daily < mw)
        tot_pt += pt
        tot_lwf_e += lwf_e
        tot_lwf_r += lwf_r
        rows.append({"code": r.get("employee_code"), "name": r.get("name"),
                     "branch": r.get("branch_name") or m.get("branch") or "Main",
                     "state": st, "gross": gross, "pt": pt,
                     "lwf_ee": lwf_e, "lwf_er": lwf_r,
                     "daily_rate": daily, "min_wage": mw,
                     "below_min_wage": "YES ⚠" if below else ""})
    if fmt == "json":
        return {"rows": rows, "totals": {"pt": round(tot_pt, 2),
                                         "lwf_employee": round(tot_lwf_e, 2),
                                         "lwf_employer": round(tot_lwf_r, 2)},
                "run_found": bool(run),
                "note": "PT/LWF frequency yearly/half-yearly wale states me monthly "
                        "column 0 rahta hai — due month me manual filing karein."}
    cols = [("Code", "code", False), ("Name", "name", False), ("Branch", "branch", False),
            ("State", "state", False), ("Gross", "gross", True), ("PT", "pt", True),
            ("LWF EE", "lwf_ee", True), ("LWF ER", "lwf_er", True),
            ("Daily Rate", "daily_rate", True), ("Min Wage", "min_wage", True),
            ("Below MW?", "below_min_wage", False)]
    return _emit(fmt, title=f"State-wise Statutory Report — {month}",
                 subtitle="PT / LWF / Minimum Wage check (branch → state)",
                 company=await _company(company_id), cols=cols, rows=rows,
                 fname_base=f"State_Statutory_{month}")
