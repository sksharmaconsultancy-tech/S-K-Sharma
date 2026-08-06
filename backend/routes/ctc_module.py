"""Iter 500 — CTC MANAGEMENT MODULE, PHASE 1 (additive only — the existing
Gross payroll engine is NOT touched).

Collections (new): ctc_structures, ctc_revisions, ctc_audit_log.
Additive fields: companies.salary_structure_mode ("gross"|"ctc"|"mixed"),
users.salary_mode / monthly_ctc / annual_ctc / ctc_structure_id /
ctc_effective_date.

Formula engine: components with calc = percent (of basic/gross/ctc, with
optional base_cap e.g. PF 15000), fixed, or balance; min/max clamps;
sequence ordering; employer-side components resolved by fixed-point
iteration (gross = CTC − employer cost).
"""
import sys
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

sys.path.append("/app/backend")
from server import db, get_user_from_token, require_role, now_iso  # noqa: E402

router = APIRouter(prefix="/api/admin/ctc", tags=["ctc"])

WRITE_ROLES = ["super_admin", "sub_admin"]
READ_ROLES = ["super_admin", "sub_admin", "company_admin"]


async def _auth(authorization: Optional[str], write: bool = False):
    user = await get_user_from_token(authorization)
    require_role(user, WRITE_ROLES if write else READ_ROLES)
    return user


async def _audit(by: dict, action: str, company_id: str, ref: str, detail: Any):
    await db.ctc_audit_log.insert_one({
        "at": now_iso(), "by": by.get("user_id"), "by_name": by.get("name"),
        "action": action, "company_id": company_id, "ref_id": ref,
        "detail": detail})


# ---------------------------------------------------------------------------
# Default templates (auto-seeded per company)
# ---------------------------------------------------------------------------
def _c(key, label, typ, calc, value=0.0, base="gross", seq=0, base_cap=None,
       hidden=False, minv=None, maxv=None):
    return {"key": key, "label": label, "type": typ, "calc": calc,
            "value": value, "base": base, "seq": seq, "base_cap": base_cap,
            "hidden": hidden, "min": minv, "max": maxv}


def _default_templates(cid: str, by: str) -> List[Dict[str, Any]]:
    common = {"company_id": cid, "status": "active", "is_template": True,
              "effective_from": now_iso()[:10], "applicable": {},
              "created_at": now_iso(), "created_by": by}
    t1 = {**common, "structure_id": f"ctc_{uuid.uuid4().hex[:10]}",
          "name": "Standard Office CTC", "is_default": True,
          "description": "Basic 50% of Gross · HRA 40% of Basic · Special "
                         "Allowance balance · Employer PF/ESIC · Gratuity",
          "includes": {"employer_pf": True, "employer_esic": True,
                       "gratuity": True, "bonus": False},
          "components": [
              _c("basic", "Basic", "earning", "percent", 50, "gross", 1),
              _c("hra", "HRA", "earning", "percent", 40, "basic", 2),
              _c("special", "Special Allowance", "earning", "balance", 0, "gross", 3),
              _c("emp_pf", "Employer PF", "employer", "percent", 12, "basic", 10, 15000),
              _c("emp_esic", "Employer ESIC", "employer", "percent", 3.25, "gross", 11, 21000),
              _c("gratuity", "Gratuity", "employer", "percent", 4.81, "basic", 12),
              _c("bonus", "Bonus", "employer", "percent", 8.33, "basic", 13, hidden=True),
              _c("ded_pf", "Employee PF", "deduction", "percent", 12, "basic", 20, 15000),
              _c("ded_esic", "Employee ESIC", "deduction", "percent", 0.75, "gross", 21, 21000),
          ]}
    t2 = {**common, "structure_id": f"ctc_{uuid.uuid4().hex[:10]}",
          "name": "Compliance / Labour CTC", "is_default": False,
          "description": "Basic = compliance wage share · DA · Other "
                         "Allowance balance · Employer PF/ESIC · Bonus · Gratuity",
          "includes": {"employer_pf": True, "employer_esic": True,
                       "gratuity": True, "bonus": True},
          "components": [
              _c("basic", "Basic (Compliance Wage)", "earning", "percent", 60, "gross", 1),
              _c("da", "DA", "earning", "percent", 0, "gross", 2),
              _c("hra", "HRA", "earning", "percent", 0, "basic", 3, hidden=True),
              _c("other", "Other Allowance", "earning", "balance", 0, "gross", 4),
              _c("emp_pf", "Employer PF", "employer", "percent", 12, "basic", 10, 15000),
              _c("emp_esic", "Employer ESIC", "employer", "percent", 3.25, "gross", 11, 21000),
              _c("bonus", "Bonus", "employer", "percent", 8.33, "basic", 12),
              _c("gratuity", "Gratuity", "employer", "percent", 4.81, "basic", 13),
              _c("ded_pf", "Employee PF", "deduction", "percent", 12, "basic", 20, 15000),
              _c("ded_esic", "Employee ESIC", "deduction", "percent", 0.75, "gross", 21, 21000),
          ]}
    t3 = {**common, "structure_id": f"ctc_{uuid.uuid4().hex[:10]}",
          "name": "Flexible / Custom CTC", "is_default": False,
          "description": "Blank template — build your own components, "
                         "formulas, percentages and sequence.",
          "includes": {}, "components": []}
    return [t1, t2, t3]


async def _ensure_templates(cid: str, by: str):
    n = await db.ctc_structures.count_documents(
        {"company_id": cid, "status": {"$ne": "deleted"}})
    if n == 0:
        await db.ctc_structures.insert_many(_default_templates(cid, by))


# ---------------------------------------------------------------------------
# Formula engine
# ---------------------------------------------------------------------------
def calc_ctc_breakup(monthly_ctc: float, components: List[Dict[str, Any]]) -> Dict[str, Any]:
    comps = sorted([c for c in components if not c.get("hidden")],
                   key=lambda c: c.get("seq") or 0)

    def amount(c, gross: float, basic: float) -> float:
        calc = c.get("calc")
        if calc == "fixed":
            v = float(c.get("value") or 0)
        elif calc == "percent":
            base_map = {"basic": basic, "gross": gross, "ctc": monthly_ctc}
            base = base_map.get(c.get("base") or "gross", gross)
            cap = c.get("base_cap")
            if cap:
                base = min(base, float(cap))
            # eligibility-style cap on GROSS bases (ESIC): if the cap is on
            # gross and gross exceeds it → not applicable.
            if cap and (c.get("base") or "gross") == "gross" and gross > float(cap):
                return 0.0
            v = base * float(c.get("value") or 0) / 100.0
        else:
            return 0.0  # balance handled separately
        if c.get("min") is not None:
            v = max(v, float(c["min"]))
        if c.get("max") is not None:
            v = min(v, float(c["max"]))
        return round(v, 2)

    gross = monthly_ctc
    basic = 0.0
    out_e: List[Dict[str, Any]] = []
    out_er: List[Dict[str, Any]] = []
    out_d: List[Dict[str, Any]] = []
    for _ in range(10):  # fixed-point iteration: gross = CTC − employer cost
        basic = 0.0
        for c in comps:
            if c["key"] == "basic" or (c.get("type") == "earning" and "basic" in c["key"]):
                basic = amount(c, gross, gross)
                break
        employer = sum(amount(c, gross, basic) for c in comps if c.get("type") == "employer")
        new_gross = round(monthly_ctc - employer, 2)
        if abs(new_gross - gross) < 0.5:
            gross = new_gross
            break
        gross = new_gross
    gross = max(0.0, gross)

    earn_named = 0.0
    balance_comp = None
    for c in comps:
        if c.get("type") != "earning":
            continue
        if c.get("calc") == "balance":
            balance_comp = c
            continue
        v = amount(c, gross, basic)
        earn_named += v
        out_e.append({"key": c["key"], "label": c["label"], "amount": v})
    if balance_comp is not None:
        v = round(max(0.0, gross - earn_named), 2)
        out_e.append({"key": balance_comp["key"], "label": balance_comp["label"], "amount": v})
    for c in comps:
        if c.get("type") == "employer":
            out_er.append({"key": c["key"], "label": c["label"],
                           "amount": amount(c, gross, basic)})
        elif c.get("type") == "deduction":
            out_d.append({"key": c["key"], "label": c["label"],
                          "amount": amount(c, gross, basic)})
    employer_total = round(sum(x["amount"] for x in out_er), 2)
    ded_total = round(sum(x["amount"] for x in out_d), 2)
    gross_total = round(sum(x["amount"] for x in out_e), 2)
    return {"monthly_ctc": round(monthly_ctc, 2), "basic": round(basic, 2),
            "gross": gross_total, "earnings": out_e,
            "employer_contributions": out_er, "employer_total": employer_total,
            "deductions": out_d, "deduction_total": ded_total,
            "net_salary": round(gross_total - ded_total, 2),
            "verify_ctc": round(gross_total + employer_total, 2)}


# ---------------------------------------------------------------------------
# Firm mode
# ---------------------------------------------------------------------------
@router.get("/firm-mode/{company_id}")
async def get_firm_mode(company_id: str, authorization: Optional[str] = Header(None)):
    await _auth(authorization)
    c = await db.companies.find_one({"company_id": company_id},
                                    {"_id": 0, "salary_structure_mode": 1})
    if c is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"mode": c.get("salary_structure_mode") or "gross"}


@router.put("/firm-mode/{company_id}")
async def put_firm_mode(company_id: str, body: Dict[str, Any],
                        authorization: Optional[str] = Header(None)):
    user = await _auth(authorization, write=True)
    mode = (body.get("mode") or "gross").lower()
    if mode not in ("gross", "ctc", "mixed"):
        raise HTTPException(status_code=400, detail="mode must be gross|ctc|mixed")
    await db.companies.update_one({"company_id": company_id},
                                  {"$set": {"salary_structure_mode": mode}})
    await _audit(user, "firm_mode_change", company_id, company_id, {"mode": mode})
    return {"ok": True, "mode": mode}


# ---------------------------------------------------------------------------
# Structures CRUD
# ---------------------------------------------------------------------------
@router.get("/structures")
async def list_structures(company_id: str = Query(...),
                          authorization: Optional[str] = Header(None)):
    user = await _auth(authorization)
    await _ensure_templates(company_id, user["user_id"])
    items = await db.ctc_structures.find(
        {"company_id": company_id, "status": {"$ne": "deleted"}},
        {"_id": 0}).sort("created_at", 1).to_list(200)
    return {"structures": items}


@router.post("/structures")
async def create_structure(body: Dict[str, Any],
                           authorization: Optional[str] = Header(None)):
    user = await _auth(authorization, write=True)
    cid = body.get("company_id")
    if not cid or not (body.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="company_id and name required")
    doc = {"structure_id": f"ctc_{uuid.uuid4().hex[:10]}", "company_id": cid,
           "name": body["name"].strip(), "description": body.get("description") or "",
           "status": "active", "is_template": False,
           "is_default": bool(body.get("is_default")),
           "effective_from": body.get("effective_from") or now_iso()[:10],
           "applicable": body.get("applicable") or {},
           "includes": body.get("includes") or {},
           "components": body.get("components") or [],
           "created_at": now_iso(), "created_by": user["user_id"]}
    await db.ctc_structures.insert_one({**doc})
    await _audit(user, "structure_create", cid, doc["structure_id"], doc["name"])
    return {"ok": True, "structure": doc}


@router.put("/structures/{structure_id}")
async def update_structure(structure_id: str, body: Dict[str, Any],
                           authorization: Optional[str] = Header(None)):
    user = await _auth(authorization, write=True)
    cur = await db.ctc_structures.find_one({"structure_id": structure_id}, {"_id": 0})
    if not cur:
        raise HTTPException(status_code=404, detail="Structure not found")
    upd = {k: body[k] for k in ("name", "description", "status", "effective_from",
                                "applicable", "includes", "components",
                                "is_default") if k in body}
    upd["updated_at"] = now_iso()
    upd["updated_by"] = user["user_id"]
    await db.ctc_structures.update_one({"structure_id": structure_id}, {"$set": upd})
    await _audit(user, "structure_update", cur["company_id"], structure_id,
                 list(upd.keys()))
    return {"ok": True}


@router.delete("/structures/{structure_id}")
async def delete_structure(structure_id: str,
                           authorization: Optional[str] = Header(None)):
    user = await _auth(authorization, write=True)
    cur = await db.ctc_structures.find_one({"structure_id": structure_id}, {"_id": 0})
    if not cur:
        raise HTTPException(status_code=404, detail="Structure not found")
    used = await db.users.count_documents({"ctc_structure_id": structure_id,
                                           "deleted": {"$ne": True}})
    if used:
        raise HTTPException(status_code=400,
                            detail=f"{used} employee(s) are assigned to this structure — reassign them first")
    await db.ctc_structures.update_one({"structure_id": structure_id},
                                       {"$set": {"status": "deleted",
                                                 "deleted_at": now_iso()}})
    await _audit(user, "structure_delete", cur["company_id"], structure_id, cur["name"])
    return {"ok": True}


@router.post("/preview")
async def preview(body: Dict[str, Any], authorization: Optional[str] = Header(None)):
    await _auth(authorization)
    ctc = float(body.get("monthly_ctc") or 0)
    if ctc <= 0:
        raise HTTPException(status_code=400, detail="monthly_ctc must be > 0")
    comps = body.get("components")
    if comps is None:
        s = await db.ctc_structures.find_one(
            {"structure_id": body.get("structure_id")}, {"_id": 0, "components": 1})
        if not s:
            raise HTTPException(status_code=404, detail="Structure not found")
        comps = s["components"]
    return {"breakup": calc_ctc_breakup(ctc, comps)}


# ---------------------------------------------------------------------------
# Employee register + assignment + revisions
# ---------------------------------------------------------------------------
@router.get("/employees")
async def ctc_register(company_id: str = Query(...),
                       authorization: Optional[str] = Header(None)):
    await _auth(authorization)
    smap = {s["structure_id"]: s["name"] async for s in db.ctc_structures.find(
        {"company_id": company_id}, {"_id": 0, "structure_id": 1, "name": 1})}
    rows = []
    async for u in db.users.find(
            {"company_id": company_id, "role": "employee", "deleted": {"$ne": True}},
            {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
             "salary_mode": 1, "monthly_ctc": 1, "annual_ctc": 1,
             "ctc_structure_id": 1, "ctc_effective_date": 1,
             "monthly_salary": 1, "gross_salary": 1, "department": 1,
             "designation": 1}).sort("name", 1):
        rows.append({
            "user_id": u["user_id"], "employee_code": u.get("employee_code") or "",
            "name": u.get("name") or "", "department": u.get("department") or "",
            "designation": u.get("designation") or "",
            "salary_mode": u.get("salary_mode") or "gross",
            "gross_salary": u.get("gross_salary") or u.get("monthly_salary") or 0,
            "monthly_ctc": u.get("monthly_ctc") or 0,
            "annual_ctc": u.get("annual_ctc") or 0,
            "structure": smap.get(u.get("ctc_structure_id") or "") or "",
            "structure_id": u.get("ctc_structure_id") or "",
            "effective_date": u.get("ctc_effective_date") or ""})
    return {"rows": rows}


@router.post("/assign")
async def assign(body: Dict[str, Any], authorization: Optional[str] = Header(None)):
    user = await _auth(authorization, write=True)
    uid = body.get("user_id")
    emp = await db.users.find_one({"user_id": uid}, {
        "_id": 0, "user_id": 1, "company_id": 1, "name": 1, "salary_mode": 1,
        "monthly_ctc": 1, "ctc_structure_id": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    mode = (body.get("salary_mode") or "gross").lower()
    if mode not in ("gross", "ctc"):
        raise HTTPException(status_code=400, detail="salary_mode must be gross|ctc")
    upd: Dict[str, Any] = {"salary_mode": mode}
    if mode == "ctc":
        ctc = float(body.get("monthly_ctc") or 0)
        if ctc <= 0:
            raise HTTPException(status_code=400, detail="monthly_ctc required for CTC mode")
        if not body.get("structure_id"):
            raise HTTPException(status_code=400, detail="structure_id required for CTC mode")
        upd.update({"monthly_ctc": round(ctc, 2),
                    "annual_ctc": round(ctc * 12, 2),
                    "ctc_structure_id": body["structure_id"],
                    "ctc_effective_date": body.get("effective_date") or now_iso()[:10]})
    rev = {"rev_id": f"rev_{uuid.uuid4().hex[:10]}",
           "company_id": emp["company_id"], "user_id": uid,
           "old_mode": emp.get("salary_mode") or "gross", "new_mode": mode,
           "old_ctc": emp.get("monthly_ctc") or 0,
           "new_ctc": upd.get("monthly_ctc") or 0,
           "old_structure_id": emp.get("ctc_structure_id") or "",
           "new_structure_id": upd.get("ctc_structure_id") or "",
           "effective_date": upd.get("ctc_effective_date") or now_iso()[:10],
           "reason": (body.get("reason") or "").strip(),
           "approved_by": user.get("name") or user["user_id"],
           "created_at": now_iso(), "created_by": user["user_id"]}
    await db.users.update_one({"user_id": uid}, {"$set": upd})
    await db.ctc_revisions.insert_one({**rev})
    await _audit(user, "ctc_assign" if mode == "ctc" else "gross_assign",
                 emp["company_id"], uid, rev)
    return {"ok": True, "revision": rev}


@router.get("/summary")
async def ctc_summary(company_id: str = Query(...),
                      authorization: Optional[str] = Header(None)):
    """Phase 3 — CTC dashboard: counts by mode, total monthly/annual CTC,
    employer cost and the per-structure distribution."""
    await _auth(authorization)
    smap = {s["structure_id"]: s async for s in db.ctc_structures.find(
        {"company_id": company_id, "status": {"$ne": "deleted"}}, {"_id": 0})}
    total = ctc_cnt = 0
    tot_ctc = tot_emp_cost = tot_net = 0.0
    by_structure: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(
            {"company_id": company_id, "role": "employee",
             "deleted": {"$ne": True}},
            {"_id": 0, "salary_mode": 1, "monthly_ctc": 1,
             "ctc_structure_id": 1}):
        total += 1
        if str(u.get("salary_mode") or "").lower() != "ctc" \
                or float(u.get("monthly_ctc") or 0) <= 0:
            continue
        ctc_cnt += 1
        ctc = float(u["monthly_ctc"])
        tot_ctc += ctc
        s = smap.get(u.get("ctc_structure_id") or "")
        if s:
            bk = calc_ctc_breakup(ctc, s.get("components") or [])
            tot_emp_cost += bk["employer_total"]
            tot_net += bk["net_salary"]
            b = by_structure.setdefault(s["structure_id"], {
                "structure_id": s["structure_id"], "name": s.get("name"),
                "employees": 0, "monthly_ctc": 0.0})
            b["employees"] += 1
            b["monthly_ctc"] = round(b["monthly_ctc"] + ctc, 2)
    return {"total_employees": total, "ctc_employees": ctc_cnt,
            "gross_employees": total - ctc_cnt,
            "total_monthly_ctc": round(tot_ctc, 2),
            "total_annual_ctc": round(tot_ctc * 12, 2),
            "total_employer_cost": round(tot_emp_cost, 2),
            "total_net_payout": round(tot_net, 2),
            "avg_monthly_ctc": round(tot_ctc / ctc_cnt, 2) if ctc_cnt else 0,
            "by_structure": sorted(by_structure.values(),
                                   key=lambda b: -b["monthly_ctc"])}


@router.get("/yearly-projection")
async def yearly_projection(company_id: str = Query(...),
                            fy_start: int = Query(...),
                            authorization: Optional[str] = Header(None)):
    """Appraisal-season report: per employee — projected annual cost (CTC /
    Gross ×12) vs the ACTUAL paid + employer statutory cost YTD, aggregated
    from the Compliance Salary runs of the financial year (Apr–Mar)."""
    await _auth(authorization)
    months = [f"{fy_start}-{m:02d}" for m in range(4, 13)] + \
             [f"{fy_start + 1}-{m:02d}" for m in range(1, 4)]
    # Latest run row per (user, month) — later generated_at wins.
    paid: Dict[str, Dict[str, dict]] = {}
    async for run in db.compliance_salary_runs.find(
            {"company_id": company_id, "month": {"$in": months}},
            {"_id": 0, "month": 1, "rows": 1}).sort("generated_at", 1):
        for r in run.get("rows") or []:
            uid = r.get("user_id")
            if uid:
                paid.setdefault(uid, {})[run["month"]] = r

    smap = {s["structure_id"]: s async for s in db.ctc_structures.find(
        {"company_id": company_id, "status": {"$ne": "deleted"}}, {"_id": 0})}
    rows: List[Dict[str, Any]] = []
    async for u in db.users.find(
            {"company_id": company_id, "role": "employee",
             "deleted": {"$ne": True}},
            {"_id": 0, "user_id": 1, "employee_code": 1, "name": 1,
             "department": 1, "designation": 1, "salary_mode": 1,
             "monthly_ctc": 1, "ctc_structure_id": 1, "compliance_gross": 1,
             "salary_monthly": 1, "gross_salary": 1,
             "monthly_salary": 1}).sort("name", 1):
        is_ctc = str(u.get("salary_mode") or "").lower() == "ctc" \
            and float(u.get("monthly_ctc") or 0) > 0
        if is_ctc:
            monthly_cost = round(float(u["monthly_ctc"]), 2)
            _s = smap.get(u.get("ctc_structure_id") or "")
            proj_employer = calc_ctc_breakup(
                monthly_cost, _s.get("components") or [])["employer_total"] \
                if _s else 0.0
        else:
            monthly_cost = round(float(
                u.get("compliance_gross") or u.get("salary_monthly")
                or u.get("gross_salary") or u.get("monthly_salary") or 0), 2)
            proj_employer = 0.0
        mrows = paid.get(u["user_id"], {})
        if monthly_cost <= 0 and mrows:
            # Daily-rated / structure-only masters: fall back to the
            # engine's full-month gross from the latest processed run.
            _last = mrows[max(mrows.keys())]
            monthly_cost = round(float(_last.get("monthly_gross") or 0), 2)
        months_paid = len(mrows)
        gross_ytd = round(sum(float(r.get("gross_paid") or 0)
                              for r in mrows.values()), 2)
        net_ytd = round(sum(float(r.get("net") or 0)
                            for r in mrows.values()), 2)
        employer_ytd = round(sum(
            float(r.get("pf_employer_total") or 0)
            + float(r.get("esic_employer") or 0)
            for r in mrows.values()), 2)
        total_cost_ytd = round(gross_ytd + employer_ytd, 2)
        if monthly_cost <= 0 and months_paid == 0:
            continue
        projected_ytd = round(months_paid * monthly_cost, 2)
        # CTC already includes the employer side → compare against total
        # cost; Gross projection excludes it → compare gross-to-gross.
        actual_basis = total_cost_ytd if is_ctc else gross_ytd
        projected_annual = round(monthly_cost * 12, 2)
        rows.append({
            "user_id": u["user_id"],
            "employee_code": u.get("employee_code") or "",
            "name": u.get("name") or "",
            "department": u.get("department") or "",
            "designation": u.get("designation") or "",
            "salary_mode": "ctc" if is_ctc else "gross",
            "monthly_cost": monthly_cost,
            "projected_annual": projected_annual,
            "projected_employer_monthly": proj_employer,
            "months_paid": months_paid,
            "gross_paid_ytd": gross_ytd,
            "net_paid_ytd": net_ytd,
            "employer_ytd": employer_ytd,
            "total_cost_ytd": total_cost_ytd,
            "projected_ytd": projected_ytd,
            "variance_ytd": round(projected_ytd - actual_basis, 2),
            "utilization_pct": round(actual_basis / projected_annual * 100, 1)
            if projected_annual > 0 else 0.0,
        })
    totals = {k: round(sum(float(r[k]) for r in rows), 2)
              for k in ("monthly_cost", "projected_annual", "gross_paid_ytd",
                        "net_paid_ytd", "employer_ytd", "total_cost_ytd",
                        "projected_ytd", "variance_ytd")}
    return {"fy": f"{fy_start}-{str(fy_start + 1)[2:]}", "months": months,
            "rows": rows, "totals": totals}


@router.get("/increment-letter/{rev_id}.pdf")
async def increment_letter_pdf(rev_id: str,
                               authorization: Optional[str] = Header(None)):
    """One-click Salary Increment / Revision letter from a CTC revision:
    firm letterhead + OLD vs NEW CTC breakup + difference + signatory."""
    from fastapi.responses import Response
    from utils.ctc_increment_letter import build_increment_letter_pdf
    await _auth(authorization)
    rev = await db.ctc_revisions.find_one({"rev_id": rev_id}, {"_id": 0})
    if not rev:
        raise HTTPException(status_code=404, detail="Revision not found")
    emp = await db.users.find_one({"user_id": rev["user_id"]}, {
        "_id": 0, "name": 1, "employee_code": 1, "designation": 1,
        "department": 1}) or {}
    company = await db.companies.find_one(
        {"company_id": rev["company_id"]},
        {"_id": 0, "name": 1, "address": 1, "phone": 1, "email": 1}) or {}

    async def _bk(ctc: float, sid: str):
        if ctc <= 0 or not sid:
            return None
        s = await db.ctc_structures.find_one({"structure_id": sid},
                                             {"_id": 0, "components": 1})
        return calc_ctc_breakup(ctc, s["components"]) if s else None

    old_bk = await _bk(float(rev.get("old_ctc") or 0),
                       rev.get("old_structure_id") or "")
    new_bk = await _bk(float(rev.get("new_ctc") or 0),
                       rev.get("new_structure_id") or "")
    s_new = await db.ctc_structures.find_one(
        {"structure_id": rev.get("new_structure_id") or ""},
        {"_id": 0, "name": 1}) or {}
    pdf = build_increment_letter_pdf(
        employee=emp, company=company, revision=rev,
        old_breakup=old_bk, new_breakup=new_bk,
        new_structure_name=s_new.get("name") or "")
    fn = f"Increment_Letter_{emp.get('employee_code') or rev['user_id']}_{(rev.get('effective_date') or '')[:10]}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@router.get("/revisions")
async def revisions(company_id: str = Query(...),
                    user_id: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    await _auth(authorization)
    q: Dict[str, Any] = {"company_id": company_id}
    if user_id:
        q["user_id"] = user_id
    items = await db.ctc_revisions.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(500)
    names = {u["user_id"]: u.get("name") async for u in db.users.find(
        {"user_id": {"$in": [i["user_id"] for i in items]}},
        {"_id": 0, "user_id": 1, "name": 1})}
    smap = {s["structure_id"]: s["name"] async for s in db.ctc_structures.find(
        {"company_id": company_id}, {"_id": 0, "structure_id": 1, "name": 1})}
    for i in items:
        i["employee_name"] = names.get(i["user_id"]) or i["user_id"]
        i["old_structure"] = smap.get(i.get("old_structure_id") or "") or ""
        i["new_structure"] = smap.get(i.get("new_structure_id") or "") or ""
    return {"revisions": items}
