"""Iter 300 — Legacy Import Wizard (PayrollCnslt SQL → portal).

User directive: import ONLY what the admin ticks — firm-wise mapping +
head-wise field selection, with a preview, nothing written until Start.

Scope:
  • Company/Firm mapping    — legacy FirmMaster (latest FnYear per FrimID)
                              mapped to existing portal firms.
  • Employee Master         — head-wise field groups (personal / contact /
                              ids / bank / salary / status).
  • Salary Process history  — ONLINE (SalaryTrans) + OFFLINE (SalaryTransoff)
                              → mongo collection ``legacy_salary_history``
                              (kept separate from live payroll data).

Endpoints (super_admin):
  GET  /api/admin/legacy-import/firms
  POST /api/admin/legacy-import/preview
  POST /api/admin/legacy-import/run          (background job)
  GET  /api/admin/legacy-import/jobs/{job_id}
  GET  /api/admin/legacy-salary              (viewer: months / rows)
"""
import asyncio
import difflib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from server import db, get_user_from_token, require_role  # noqa: E402
from routes.legacy_explorer import _cfg, _q  # noqa: E402

router = APIRouter(prefix="/api", tags=["legacy-import"])

FIELD_GROUPS = ["personal", "contact", "ids", "bank", "salary", "status"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _dbname() -> str:
    if not _cfg():
        raise HTTPException(status_code=503, detail="Legacy SQL Server is not configured yet")
    dbs = await _q(None, "SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name")
    if not dbs:
        raise HTTPException(status_code=404, detail="No legacy database restored")
    return dbs[0]["name"]


async def _super(authorization: Optional[str]) -> dict:
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    return admin


def _month_key(v: Any) -> Optional[str]:
    """FirstDayOfMonth datetime/iso → 'YYYY-MM'."""
    s = str(v or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else None


# --------------------------------------------------------------------------
# Firms
# --------------------------------------------------------------------------
@router.get("/admin/legacy-import/firms")
async def legacy_import_firms(authorization: Optional[str] = Header(None)):
    await _super(authorization)
    dbn = await _dbname()
    firms = await _q(
        dbn,
        "SELECT f.FrimID AS firm_no, f.FirmName AS firm_name, f.ShortName AS short_name, "
        "f.PFNo AS pf_no, f.ESINo AS esi_no, f.FnYear AS fn_year, f.IsActive AS is_active "
        "FROM FirmMaster f JOIN ("
        "  SELECT FrimID, MAX(FnYear) AS Fy FROM FirmMaster GROUP BY FrimID"
        ") mx ON mx.FrimID = f.FrimID AND mx.Fy = f.FnYear",
    )
    emp_counts = await _q(
        dbn,
        "SELECT FirmNo AS firm_no, COUNT(DISTINCT CASE WHEN EmpCode > 0 THEN EmpCode ELSE EmpID END) AS n "
        "FROM EmployeeMaster GROUP BY FirmNo",
    )
    on_counts = await _q(
        dbn, "SELECT FirmNo AS firm_no, COUNT(*) AS n, COUNT(DISTINCT MonthYear) AS months "
             "FROM SalaryTrans WHERE DeletedDate IS NULL GROUP BY FirmNo")
    off_counts = await _q(
        dbn, "SELECT FirmNo AS firm_no, COUNT(*) AS n, COUNT(DISTINCT MonthYear) AS months "
             "FROM SalaryTransoff WHERE DeletedDate IS NULL GROUP BY FirmNo")
    ec = {e["firm_no"]: e["n"] for e in emp_counts}
    oc = {e["firm_no"]: e for e in on_counts}
    fc = {e["firm_no"]: e for e in off_counts}

    portal = await db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}).to_list(300)
    pnames = [p["name"] for p in portal if p.get("name")]

    # Iter 300b (user) — firms already imported are locked (no re-import).
    done = {
        d["firm_no"]: d
        for d in await db.legacy_imported_firms.find({}, {"_id": 0}).to_list(2000)
    }

    out = []
    for f in firms:
        nm = str(f.get("firm_name") or "").strip()
        sug = None
        close = difflib.get_close_matches(nm.lower(), [p.lower() for p in pnames], n=1, cutoff=0.6)
        if close:
            for p in portal:
                if str(p.get("name") or "").lower() == close[0]:
                    sug = p
                    break
        out.append({
            "firm_no": f["firm_no"],
            "firm_name": nm,
            "short_name": f.get("short_name"),
            "pf_no": f.get("pf_no"),
            "esi_no": f.get("esi_no"),
            "fn_year": f.get("fn_year"),
            "employees": ec.get(f["firm_no"], 0),
            "online_rows": (oc.get(f["firm_no"]) or {}).get("n", 0),
            "online_months": (oc.get(f["firm_no"]) or {}).get("months", 0),
            "offline_rows": (fc.get(f["firm_no"]) or {}).get("n", 0),
            "offline_months": (fc.get(f["firm_no"]) or {}).get("months", 0),
            "suggested_company_id": (sug or {}).get("company_id"),
            "suggested_company_name": (sug or {}).get("name"),
            "already_imported": f["firm_no"] in done,
            "imported_at": (done.get(f["firm_no"]) or {}).get("imported_at"),
            "imported_into": (done.get(f["firm_no"]) or {}).get("company_name"),
        })
    # Iter 300b (user) — alphabetical order.
    out.sort(key=lambda x: x["firm_name"].lower())
    return {"db": dbn, "firms": out, "portal_firms": portal}


# --------------------------------------------------------------------------
# Preview / Run
# --------------------------------------------------------------------------
class FirmMap(BaseModel):
    firm_no: int
    company_id: str


class ImportBody(BaseModel):
    mappings: List[FirmMap]
    import_employees: bool = True
    employee_fields: List[str] = FIELD_GROUPS
    salary_online: bool = True
    salary_offline: bool = True
    # Iter 300e (user) — "change head then import": remap a default portal
    # field to another portal field, or 'skip' to not import that head.
    field_overrides: Dict[str, str] = {}
    # Iter 301b (user) — salary-history heads can be remapped/skipped too.
    salary_online_overrides: Dict[str, str] = {}
    salary_offline_overrides: Dict[str, str] = {}


# Identity keys of a history row — never remappable/skippable.
_HIST_PROTECTED = {"company_id", "firm_no", "kind", "month",
                   "emp_code", "emp_id", "user_id", "name"}


def _apply_hist_overrides(base: Dict[str, Any], ov: Dict[str, str]) -> None:
    for src, dst in (ov or {}).items():
        if src in _HIST_PROTECTED or src not in base:
            continue
        val = base.pop(src)
        if dst and str(dst).lower() != "skip" and dst != src and dst not in _HIST_PROTECTED:
            base[dst] = val


async def _legacy_employees(dbn: str, firm_no: int) -> List[dict]:
    """Latest AcYear record per employee (EmpCode, else EmpID) of a firm."""
    rows = await _q(
        dbn,
        "SELECT * FROM EmployeeMaster WHERE FirmNo = %s ORDER BY AcYear DESC, UID DESC",
        (firm_no,),
    )
    seen: Dict[Any, dict] = {}
    for r in rows:
        key = r.get("EmpCode") if (r.get("EmpCode") or 0) > 0 else f"id_{r.get('EmpID')}"
        if key not in seen:
            seen[key] = r
    return list(seen.values())


@router.post("/admin/legacy-import/preview")
async def legacy_import_preview(body: ImportBody, authorization: Optional[str] = Header(None)):
    await _super(authorization)
    dbn = await _dbname()
    out = []
    for m in body.mappings:
        firm: Dict[str, Any] = {"firm_no": m.firm_no, "company_id": m.company_id}
        comp = await db.companies.find_one({"company_id": m.company_id}, {"_id": 0, "name": 1})
        firm["company_name"] = (comp or {}).get("name")
        if body.import_employees:
            emps = await _legacy_employees(dbn, m.firm_no)
            existing_names = {
                str(u.get("name") or "").strip().lower()
                for u in await db.users.find(
                    {"company_id": m.company_id, "role": "employee"},
                    {"_id": 0, "name": 1}).to_list(20000)
            }
            existing = sum(
                1 for e in emps
                if str(e.get("EmpName") or "").strip().lower() in existing_names)
            firm["employees_total"] = len(emps)
            firm["employees_existing"] = existing
            firm["employees_new"] = len(emps) - existing
        if body.salary_online:
            n = await _q(dbn, "SELECT COUNT(*) AS n, COUNT(DISTINCT MonthYear) AS m FROM SalaryTrans "
                              "WHERE FirmNo = %s AND DeletedDate IS NULL", (m.firm_no,))
            firm["online_rows"] = n[0]["n"] if n else 0
            firm["online_months"] = n[0]["m"] if n else 0
        if body.salary_offline:
            n = await _q(dbn, "SELECT COUNT(*) AS n, COUNT(DISTINCT MonthYear) AS m FROM SalaryTransoff "
                              "WHERE FirmNo = %s AND DeletedDate IS NULL", (m.firm_no,))
            firm["offline_rows"] = n[0]["n"] if n else 0
            firm["offline_months"] = n[0]["m"] if n else 0
        out.append(firm)
    return {"db": dbn, "firms": out}


def _rx(s: Any) -> str:
    import re
    return re.escape(str(s or "").strip())


def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def _d(v: Any) -> Optional[str]:
    s = str(v or "")
    return s[:10] if len(s) >= 10 and s[4] == "-" else None


def _emp_doc_fields(
    e: dict, groups: List[str], structure: List[dict],
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Legacy EmployeeMaster row → portal user fields, per selected groups."""
    doc: Dict[str, Any] = {}
    if "personal" in groups:
        doc.update({
            "name": str(e.get("EmpName") or "").strip(),
            "father_name": (str(e.get("EmpFatherName") or "").strip() or None),
            "gender": (str(e.get("Gender") or "").strip() or None),
            "dob": _d(e.get("DOB")),
            "doj": _d(e.get("NewDOJ")) or _d(e.get("DOJ")),
            "marital_status": (str(e.get("MaritalStatus") or "").strip() or None),
            "designation": (str(e.get("Designation") or "").strip() or None),
            "department": (str(e.get("Department") or "").strip() or None),
            "employee_type": (str(e.get("EmpType") or "").strip() or None),
            "employee_group": (str(e.get("EmpType") or "").strip() or None),
            "salary_mode": ("daily" if str(e.get("PayBasis") or "").strip().upper() == "DAILY" else "monthly"),
        })
    if "contact" in groups:
        phone = str(e.get("PersMobileNo") or e.get("PermMobileNo") or "").strip()
        phone = "".join(ch for ch in phone if ch.isdigit())[-10:]
        doc.update({
            "phone": (phone if len(phone) == 10 else None),
            "email": (str(e.get("Email") or "").strip().lower() or None),
            "present_address": (str(e.get("PresentAdd") or "").strip() or None),
            "permanent_address": (str(e.get("PermanentAdd") or "").strip() or None),
            "address": (str(e.get("PresentAdd") or e.get("PermanentAdd") or "").strip() or None),
            "pincode": (str(e.get("PersPinCode") or e.get("PermPinCode") or "").strip() or None),
        })
    if "ids" in groups:
        doc.update({
            "pan_no": (str(e.get("PANNo") or "").strip() or None),
            "aadhaar_no": (str(e.get("AadharCardNo") or "").strip() or None),
            "uan_no": (str(e.get("UANNo") or "").strip() or None),
            "pf_no": (str(e.get("PFNumber") or e.get("PFNo") or "").strip() or None),
            "esi_ip_no": (str(e.get("ESINo") or "").strip() or None),
        })
    if "bank" in groups:
        doc.update({
            "bank_name": (str(e.get("BankName") or "").strip() or None),
            "bank_account": (str(e.get("AccountNo") or "").strip() or None),
            "bank_ifsc": (str(e.get("IFSCCode") or "").strip() or None),
            "account_holder": (str(e.get("NameOnBankAc") or "").strip() or None),
            "bank_address": (str(e.get("BankAddress") or "").strip() or None),
        })
    if "salary" in groups:
        allow = [
            {"head": str(s.get("SalHeadName") or "").strip(), "amount": float(s.get("Amount") or 0)}
            for s in structure
            if str(s.get("SalHeadType") or "").upper() == "ALLOWANCE" and _f(s.get("Amount"))
        ]
        doc.update({
            "basic_salary": _f(e.get("BasicSalary")),
            "compliance_basic": _f(e.get("BasicSalary")),
            "pf_basic": _f(e.get("PFBasicSalary")),
            "compliance_gross": _f(e.get("GrossPay")),
            "salary_monthly": _f(e.get("Salary")),
        })
        if allow:
            doc["compliance_salary_allowances"] = allow
    if "status" in groups:
        if e.get("IsResign"):
            doc.update({
                "resign_date": _d(e.get("ResignDate")),
                "exit_date": _d(e.get("ResignDate")),
                "employment_status": "resigned",
            })
    # Iter 300e (user) — apply head remaps chosen in the wizard: move a
    # value from its default portal field into another, or drop it (skip).
    for src, dst in (overrides or {}).items():
        if src in doc and dst != src:
            val = doc.pop(src)
            if dst and str(dst).lower() != "skip":
                doc[dst] = val
    return {k: v for k, v in doc.items() if v is not None or k in ("phone", "email")}


# Deduction/allowance head display names — SalaryHeadMaster SrNo → name.
async def _head_names(dbn: str) -> Dict[str, str]:
    heads = await _q(dbn, "SELECT SalHeadType, SalHead_SrNo, DispalyName, SalHeadName FROM SalaryHeadMaster")
    out: Dict[str, str] = {}
    for h in heads:
        t = str(h.get("SalHeadType") or "").upper()
        sr = h.get("SalHead_SrNo")
        nm = str(h.get("DispalyName") or h.get("SalHeadName") or "").strip()
        if not sr or not nm:
            continue
        if t == "ALLOWANCE":
            out[f"Earn{sr}"] = nm
        elif t in ("DEDUCTION", "DEDUCT"):
            out[f"Deduct{sr}"] = nm
    return out


# Iter 300d (user) — INTERLINK: Employee Type / Department / Designation
# values coming from the legacy data are auto-registered into the portal's
# General Masters for the mapped firm (so they appear in every dropdown).
async def _interlink_masters(company_id: str, values: Dict[str, set]):
    for mtype, names in values.items():
        if not names:
            continue
        existing = set()
        async for mm in db.masters.find(
            {"type": mtype, "company_id": {"$in": [company_id, "__global__", None]}},
            {"_id": 0, "name": 1},
        ):
            existing.add(str(mm.get("name") or "").strip().upper())
        for nm in sorted(names):
            nm = str(nm or "").strip()
            if not nm or nm.upper() in existing:
                continue
            doc = {
                "master_id": f"mst_{uuid.uuid4().hex[:12]}",
                "type": mtype,
                "company_id": company_id,
                "name": (nm.upper() if mtype == "group" else nm),
                "date": None,
                "created_at": _now(),
                "updated_at": _now(),
                "created_by": "legacy_import",
                "scope": "firm",
                "auto_registered": "legacy_import_interlink",
            }
            if mtype == "group":
                doc["member_user_ids"] = []
            await db.masters.insert_one(doc)
            existing.add(nm.upper())


async def _run_job(job_id: str, body: ImportBody):
    dbn = await _dbname()
    heads = await _head_names(dbn)

    async def _prog(**kw):
        await db.legacy_import_jobs.update_one({"job_id": job_id}, {"$set": {**kw, "updated_at": _now()}})

    totals = {"employees_created": 0, "employees_updated": 0, "employees_skipped": 0,
              "online_rows": 0, "offline_rows": 0}
    errors: List[str] = []
    try:
        for m in body.mappings:
            await _prog(status="running", current_firm=m.firm_no)
            emp_uid: Dict[Any, str] = {}

            # ---------------- Employees ----------------
            if body.import_employees:
                _ml: Dict[str, set] = {"group": set(), "department": set(), "designation": set()}
                emps = await _legacy_employees(dbn, m.firm_no)
                # head-wise structure rows for this firm (salary group)
                struct_by_emp: Dict[int, List[dict]] = {}
                if "salary" in body.employee_fields:
                    srows = await _q(
                        dbn,
                        "SELECT EmpID_FK, SalHeadType, SalHeadName, Amount "
                        "FROM EmployeeSalaryStructureDtl WHERE FirmID_FK = %s",
                        (m.firm_no,),
                    )
                    for s in srows:
                        struct_by_emp.setdefault(int(s.get("EmpID_FK") or 0), []).append(s)
                for e in emps:
                    try:
                        nm = str(e.get("EmpName") or "").strip()
                        if not nm:
                            totals["employees_skipped"] += 1
                            continue
                        fields = _emp_doc_fields(
                            e, body.employee_fields,
                            struct_by_emp.get(int(e.get("EmpID") or 0), []),
                            overrides=body.field_overrides)
                        # collect for General Masters interlink
                        if fields.get("employee_type"):
                            _ml["group"].add(str(fields["employee_type"]).strip().upper())
                        if fields.get("department"):
                            _ml["department"].add(str(fields["department"]).strip())
                        if fields.get("designation"):
                            _ml["designation"].add(str(fields["designation"]).strip())
                        # phone conflict → drop phone rather than fail
                        if fields.get("phone"):
                            clash = await db.users.find_one(
                                {"phone": fields["phone"], "role": "employee"}, {"_id": 1})
                            if clash:
                                fields["phone"] = None
                        code = e.get("EmpCode") if (e.get("EmpCode") or 0) > 0 else None
                        q = {"company_id": m.company_id, "role": "employee",
                             "name": {"$regex": f"^{_rx(nm)}$", "$options": "i"}}
                        existing = await db.users.find_one(q, {"_id": 0, "user_id": 1})
                        if existing:
                            fields.pop("phone", None)
                            fields.pop("email", None)
                            await db.users.update_one(
                                {"user_id": existing["user_id"]},
                                {"$set": {k: v for k, v in fields.items() if v is not None}})
                            totals["employees_updated"] += 1
                            uid = existing["user_id"]
                        else:
                            doc = {
                                "user_id": f"user_{uuid.uuid4().hex[:12]}",
                                "role": "employee",
                                "company_id": m.company_id,
                                "employee_code": (str(code) if code else None),
                                "is_onroll": True,
                                "onboarded": True,
                                "approval_status": "approved",
                                "has_pin": False,
                                "picture": None,
                                "created_at": _now(),
                                "legacy_imported": True,
                                "legacy_firm_no": m.firm_no,
                                "legacy_emp_id": e.get("EmpID"),
                                **fields,
                            }
                            doc.setdefault("name", nm)
                            doc.setdefault("phone", None)
                            doc.setdefault("email", None)
                            await db.users.insert_one(doc)
                            totals["employees_created"] += 1
                            uid = doc["user_id"]
                        if code is not None:
                            emp_uid[int(code)] = uid
                        emp_uid[f"id_{e.get('EmpID')}"] = uid
                    except Exception as ex:
                        totals["employees_skipped"] += 1
                        if len(errors) < 40:
                            errors.append(f"emp {e.get('EmpName')}: {str(ex)[:120]}")
                # Iter 300d — register Types/Departments/Designations into
                # the firm's General Masters (interlink).
                try:
                    await _interlink_masters(m.company_id, _ml)
                except Exception as ex:
                    if len(errors) < 40:
                        errors.append(f"masters interlink: {str(ex)[:120]}")
                await _prog(totals=totals)

            # ---------------- Salary history ----------------
            for kind, table in (("online", "SalaryTrans"), ("offline", "SalaryTransoff")):
                if kind == "online" and not body.salary_online:
                    continue
                if kind == "offline" and not body.salary_offline:
                    continue
                await db.legacy_salary_history.delete_many(
                    {"company_id": m.company_id, "kind": kind, "firm_no": m.firm_no})
                skip = 0
                while True:
                    rows = await _q(
                        dbn,
                        f"SELECT * FROM {table} WHERE FirmNo = %s AND DeletedDate IS NULL "
                        f"ORDER BY UID OFFSET {skip} ROWS FETCH NEXT 2000 ROWS ONLY",
                        (m.firm_no,),
                    )
                    if not rows:
                        break
                    docs = []
                    for r in rows:
                        mon = _month_key(r.get("FirstDayOfMonth"))
                        if not mon:
                            continue
                        code = r.get("EmpCode") if (r.get("EmpCode") or 0) > 0 else None
                        base = {
                            "company_id": m.company_id,
                            "firm_no": m.firm_no,
                            "kind": kind,
                            "month": mon,
                            "emp_code": code,
                            "emp_id": r.get("EmpID"),
                            "user_id": emp_uid.get(int(code)) if code else emp_uid.get(f"id_{r.get('EmpID')}"),
                            "name": str(r.get("EmpName") or "").strip(),
                            "employee_type": (str(r.get("EmpType") or "").strip() or None),
                            "month_days": r.get("MonthDays"),
                            "present_days": _f(r.get("PresentDays")) or 0,
                            "basic": _f(r.get("TBasicSalary")) or _f(r.get("BasicSalary")) or 0,
                            "gross": _f(r.get("GrossSalary")) or 0,
                            "net": _f(r.get("NetSalary")) or 0,
                        }
                        if kind == "online":
                            earn = {}
                            ded = {}
                            for i in range(1, 26):
                                v = _f(r.get(f"Earn{i}"))
                                if v:
                                    earn[heads.get(f"Earn{i}", f"Earn{i}")] = v
                            for i in range(1, 21):
                                v = _f(r.get(f"Deduct{i}"))
                                if v:
                                    ded[heads.get(f"Deduct{i}", f"Deduct{i}")] = v
                            base.update({
                                "earn_heads": earn, "deduct_heads": ded,
                                "pf_basic": _f(r.get("T_PFBasicSalary")),
                                "ee_pf": _f(r.get("EE_EPF")),
                                "er_pf": (_f(r.get("ER_EPF")) or 0) + (_f(r.get("ER_FPF")) or 0) or None,
                                "er_esi": _f(r.get("ER_ESI")),
                                "less_adv": _f(r.get("LessAdv")),
                                "less_other": _f(r.get("LessOther")),
                                "less_loan": _f(r.get("LessLoan")),
                                "less_total": _f(r.get("LessTotal")),
                                "ot_hours": _f(r.get("OTWorkHours")),
                            })
                        else:
                            base.update({
                                "rate": _f(r.get("SalaryRate")),
                                "w_basic": _f(r.get("WBasicSalary")),
                                "others": _f(r.get("TOther")),
                                "tds": _f(r.get("TDS")),
                                "work_hours": _f(r.get("WorkHours")),
                                "less_epf": _f(r.get("LessEPF")),
                                "less_esi": _f(r.get("LessESI")),
                                "less_adv": _f(r.get("LessAdv")),
                                "less_other": _f(r.get("LessOther")),
                                "less_loan": _f(r.get("LessLoan")),
                                "less_total": _f(r.get("LessTotal")),
                            })
                        _apply_hist_overrides(
                            base,
                            body.salary_online_overrides if kind == "online"
                            else body.salary_offline_overrides)
                        docs.append(base)
                    if docs:
                        await db.legacy_salary_history.insert_many(docs)
                        totals[f"{kind}_rows"] += len(docs)
                    skip += 2000
                    await _prog(totals=totals)

            # Iter 300b (user) — mark this firm DONE so it cannot be
            # imported twice.
            comp = await db.companies.find_one(
                {"company_id": m.company_id}, {"_id": 0, "name": 1})
            await db.legacy_imported_firms.update_one(
                {"firm_no": m.firm_no},
                {"$set": {
                    "firm_no": m.firm_no,
                    "company_id": m.company_id,
                    "company_name": (comp or {}).get("name"),
                    "job_id": job_id,
                    "imported_at": _now(),
                }},
                upsert=True,
            )
        await db.legacy_salary_history.create_index(
            [("company_id", 1), ("kind", 1), ("month", 1)])
        await db.legacy_salary_history.create_index([("user_id", 1), ("month", 1)])
        await _prog(status="done", totals=totals, errors=errors, finished_at=_now())
    except Exception as ex:
        errors.append(str(ex)[:300])
        await _prog(status="failed", totals=totals, errors=errors, finished_at=_now())


@router.post("/admin/legacy-import/run")
async def legacy_import_run(body: ImportBody, authorization: Optional[str] = Header(None)):
    admin = await _super(authorization)
    if not body.mappings:
        raise HTTPException(status_code=400, detail="Map at least one firm")
    # Iter 302d (user) — salary history can only be imported for firms
    # whose Employee Master is imported too (in this run or earlier).
    if (body.salary_online or body.salary_offline) and not body.import_employees:
        for m in body.mappings:
            emp_ok = await db.users.find_one(
                {"company_id": m.company_id, "role": "employee",
                 "legacy_imported": True}, {"_id": 1})
            if not emp_ok:
                raise HTTPException(
                    status_code=400,
                    detail="Salary import is only allowed for firms whose "
                           "Employee Master is already imported — tick "
                           "'Employee Master' for this firm or import "
                           "employees first.")
    # Iter 300b (user) — block re-import of firms already done.
    done_nos = {
        d["firm_no"] for d in await db.legacy_imported_firms.find(
            {"firm_no": {"$in": [m.firm_no for m in body.mappings]}},
            {"_id": 0, "firm_no": 1}).to_list(2000)
    }
    if done_nos:
        raise HTTPException(
            status_code=409,
            detail=f"These firms are ALREADY IMPORTED and cannot be imported again: "
                   f"{sorted(done_nos)}. Unselect them to continue.",
        )
    job_id = f"limp_{uuid.uuid4().hex[:10]}"
    await db.legacy_import_jobs.insert_one({
        "job_id": job_id, "status": "queued", "totals": {}, "errors": [],
        "mappings": [m.model_dump() for m in body.mappings],
        "started_by": admin.get("user_id"), "started_at": _now(),
    })
    asyncio.get_event_loop().create_task(_run_job(job_id, body))
    return {"job_id": job_id}


@router.get("/admin/legacy-import/jobs/{job_id}")
async def legacy_import_job(job_id: str, authorization: Optional[str] = Header(None)):
    await _super(authorization)
    j = await db.legacy_import_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return j


# --------------------------------------------------------------------------
# Viewer — imported salary history
# --------------------------------------------------------------------------
@router.get("/admin/legacy-salary")
async def legacy_salary_view(
    company_id: str = Query(...),
    kind: str = Query("online"),
    month: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin["role"] == "company_admin":
        company_id = admin["company_id"]
    q: dict = {"company_id": company_id, "kind": kind}
    if not month:
        months = await db.legacy_salary_history.distinct("month", q)
        return {"months": sorted(months, reverse=True)}
    q["month"] = month
    if search and search.strip():
        q["name"] = {"$regex": _rx(search.strip()), "$options": "i"}
    rows = await db.legacy_salary_history.find(q, {"_id": 0}).sort("name", 1).to_list(3000)
    return {"month": month, "kind": kind, "rows": rows, "count": len(rows)}


# --------------------------------------------------------------------------
# Iter 301 — Legacy vs Current comparison (spot-check migrated data)
# --------------------------------------------------------------------------
async def _cur_run_agg(coll, company_id: str, net_field: str, days_field: str,
                       gross_field: str) -> Dict[str, dict]:
    """Per-user summary of CURRENT payroll runs (months, last month/net)."""
    pipe = [
        {"$match": {"company_id": company_id}},
        {"$unwind": "$rows"},
        {"$match": {"rows.user_id": {"$ne": None}}},
        # one run can exist several times per month (reprocess / branch /
        # type runs) — collapse to user+month first so counts are real.
        {"$group": {
            "_id": {"u": "$rows.user_id", "m": "$month"},
            "net": {"$last": f"$rows.{net_field}"},
            "days": {"$last": f"$rows.{days_field}"},
            "gross": {"$last": f"$rows.{gross_field}"},
        }},
        {"$sort": {"_id.m": 1}},
        {"$group": {
            "_id": "$_id.u",
            "months": {"$sum": 1},
            "last_month": {"$last": "$_id.m"},
            "last_net": {"$last": "$net"},
            "last_days": {"$last": "$days"},
            "last_gross": {"$last": "$gross"},
        }},
    ]
    out: Dict[str, dict] = {}
    async for g in coll.aggregate(pipe):
        uid = g.pop("_id")
        out[uid] = g
    return out


@router.get("/admin/legacy-compare")
async def legacy_compare_list(
    company_id: str = Query(...),
    search: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    if admin["role"] == "company_admin":
        company_id = admin["company_id"]

    # legacy history per user+kind (keep last 3 months for a fair compare)
    pipe = [
        {"$match": {"company_id": company_id, "user_id": {"$ne": None}}},
        {"$sort": {"month": 1}},
        {"$group": {
            "_id": {"u": "$user_id", "k": "$kind"},
            "months": {"$sum": 1},
            "recent": {"$push": {
                "m": "$month", "b": "$basic", "g": "$gross", "n": "$net",
                "d": "$present_days", "md": "$month_days",
            }},
        }},
        {"$project": {"months": 1, "recent": {"$slice": ["$recent", -3]}}},
    ]
    legacy: Dict[str, dict] = {}
    async for g in db.legacy_salary_history.aggregate(pipe):
        u, k = g["_id"]["u"], g["_id"]["k"]
        last = (g.get("recent") or [{}])[-1]
        legacy.setdefault(u, {})[k] = {
            "months": g["months"], "last_month": last.get("m"),
            "last_basic": last.get("b"), "last_gross": last.get("g"),
            "last_net": last.get("n"), "last_days": last.get("d"),
            "last_month_days": last.get("md"),
            "_recent": g.get("recent") or [],
        }

    uq: dict = {"company_id": company_id, "role": "employee",
                "$or": [{"legacy_imported": True},
                        {"user_id": {"$in": list(legacy.keys())}}]}
    if search and search.strip():
        uq["$and"] = [{"$or": [
            {"name": {"$regex": _rx(search.strip()), "$options": "i"}},
            {"employee_code": {"$regex": _rx(search.strip()), "$options": "i"}},
        ]}]
    users = await db.users.find(uq, {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
        "basic_salary": 1, "compliance_gross": 1, "salary_monthly": 1,
        "salary_mode": 1, "legacy_imported": 1,
    }).sort("name", 1).to_list(20000)

    cur_act = await _cur_run_agg(db.salary_runs, company_id, "net_pay", "p_days", "total_gross")
    cur_cmp = await _cur_run_agg(db.compliance_salary_runs, company_id, "net", "present_days", "gross_paid")

    def _full_rate(r: dict) -> Optional[float]:
        """Earned basic of one month → estimated full-month rate.
        Scales BOTH directions (partial month up, extra/OT paid days down)."""
        try:
            b = float(r.get("b") or 0)
            d = float(r.get("d") or 0)
            md = float(r.get("md") or 0)
        except (TypeError, ValueError):
            return None
        if b <= 0 or d <= 0:
            return None
        return round(b * md / d, 0) if md > 0 else b

    out = []
    for u in users:
        uid = u["user_id"]
        leg = legacy.get(uid, {})
        leg_on = leg.get("online")
        master_basic = u.get("basic_salary")
        # Legacy SalaryTrans Basic is the EARNED basic (pro-rated by paid
        # days incl. OT/extra days) — normalise each of the LAST 3 months to
        # a full-month rate and flag only when NONE of them matches the
        # master within 2.5% (user: genuine rate changes only).
        candidates: List[float] = []
        if leg_on:
            candidates = [c for c in (_full_rate(r) for r in leg_on.pop("_recent", []))
                          if c is not None]
            leg_on["full_basic"] = candidates[-1] if candidates else None
        mismatch = bool(
            master_basic and candidates
            and all(
                abs(float(master_basic) - c) / max(float(master_basic), c) > 0.025
                for c in candidates))
        leg_off = leg.get("offline")
        if leg_off:
            leg_off.pop("_recent", None)
        out.append({
            **u,
            "legacy_online": leg_on,
            "legacy_offline": leg_off,
            "current_actual": cur_act.get(uid),
            "current_compliance": cur_cmp.get(uid),
            "mismatch_basic": mismatch,
        })
    n_leg = sum(1 for r in out if r["legacy_online"] or r["legacy_offline"])
    n_mis = sum(1 for r in out if r["mismatch_basic"])
    return {"rows": out, "count": len(out),
            "with_legacy": n_leg, "mismatches": n_mis}


@router.get("/admin/legacy-compare/{user_id}")
async def legacy_compare_detail(
    user_id: str, authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    u = await db.users.find_one({"user_id": user_id}, {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1,
        "basic_salary": 1, "compliance_gross": 1, "salary_monthly": 1,
        "pf_basic": 1, "salary_mode": 1, "doj": 1,
    })
    if not u:
        raise HTTPException(status_code=404, detail="Employee not found")
    if admin["role"] == "company_admin" and u.get("company_id") != admin.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your firm")

    months: Dict[str, dict] = {}

    def _slot(m: str) -> dict:
        return months.setdefault(m, {"month": m})

    async for r in db.legacy_salary_history.find(
            {"user_id": user_id}, {"_id": 0}).sort("month", 1):
        _slot(r["month"])[f"legacy_{r['kind']}"] = {
            "days": r.get("present_days"), "basic": r.get("basic"),
            "gross": r.get("gross"), "net": r.get("net"),
        }
    async for g in db.salary_runs.aggregate([
        {"$match": {"company_id": u["company_id"]}},
        {"$unwind": "$rows"},
        {"$match": {"rows.user_id": user_id}},
        {"$project": {"_id": 0, "month": 1, "r": "$rows"}},
    ]):
        _slot(g["month"])["actual"] = {
            "days": g["r"].get("p_days"), "basic": g["r"].get("basic"),
            "gross": g["r"].get("total_gross"), "net": g["r"].get("net_pay"),
        }
    async for g in db.compliance_salary_runs.aggregate([
        {"$match": {"company_id": u["company_id"]}},
        {"$unwind": "$rows"},
        {"$match": {"rows.user_id": user_id}},
        {"$project": {"_id": 0, "month": 1, "r": "$rows"}},
    ]):
        _slot(g["month"])["compliance"] = {
            "days": g["r"].get("present_days"), "basic": g["r"].get("basic"),
            "gross": g["r"].get("gross_paid"), "net": g["r"].get("net"),
        }
    rows = [months[m] for m in sorted(months.keys(), reverse=True)]
    return {"employee": u, "months": rows, "count": len(rows)}


# --------------------------------------------------------------------------
# Iter 302 (user) — PUBLISH legacy ONLINE months into the Compliance Salary
# Process as FINALIZED (locked) runs, so they appear in the month list and
# in every report (register, PF ECR, ESIC) like normally processed salary.
# --------------------------------------------------------------------------
def _head_pick(heads: Dict[str, Any], *needles: str) -> float:
    """Sum the values of head names containing any needle (case-insens)."""
    tot = 0.0
    for k, v in (heads or {}).items():
        ku = str(k).upper()
        if any(n in ku for n in needles):
            try:
                tot += float(v or 0)
            except (TypeError, ValueError):
                pass
    return tot


def _legacy_row_to_compliance(r: dict, u: dict) -> dict:
    """One legacy_salary_history ONLINE row → compliance run row."""
    earn = r.get("earn_heads") or {}
    ded = r.get("deduct_heads") or {}
    gross = float(r.get("gross") or 0)
    net = float(r.get("net") or 0)
    basic = float(r.get("basic") or 0)
    hra = _head_pick(earn, "HRA", "HOUSE RENT")
    conv = _head_pick(earn, "CONV")
    med = _head_pick(earn, "MED")
    spl = _head_pick(earn, "SPECIAL", "SPL")
    ot_pay = _head_pick(earn, "OT ", "OVERTIME", "OVER TIME")
    others = max(0.0, round(gross - basic - hra - conv - med - spl - ot_pay, 2))
    pf_wages = float(r.get("pf_basic") or 0)
    pf_emp = float(r.get("ee_pf") or 0)
    er_pf = float(r.get("er_pf") or 0)
    # EPFO split: EPS = 8.33% of capped PF wages, EPF = remainder.
    eps = round(min(pf_wages, 15000.0) * 0.0833) if er_pf else 0.0
    eps = min(eps, er_pf)
    esic_er = float(r.get("er_esi") or 0)
    esic_ee = _head_pick(ded, "ESI")
    if not esic_ee and esic_er and gross:
        esic_ee = round(gross * 0.0075, 2)  # statutory employee share
    pt = _head_pick(ded, "PROF", "PTAX", "P.TAX", "P TAX")
    if not pt and "PT" in ded:
        pt = _head_pick(ded, "PT")
    tds = _head_pick(ded, "TDS")
    return {
        "user_id": r.get("user_id"),
        "name": r.get("name"),
        "employee_code": (u or {}).get("employee_code"),
        "father_name": (u or {}).get("father_name"),
        "designation": (u or {}).get("designation"),
        "uan_no": (u or {}).get("uan_no"),
        "esi_ip_no": (u or {}).get("esi_ip_no"),
        "employee_type": r.get("employee_type") or (u or {}).get("employee_type"),
        "is_onroll": True,
        "salary_mode": (u or {}).get("salary_mode") or "monthly",
        "month_days": r.get("month_days"),
        "present_days": float(r.get("present_days") or 0),
        "half_days": 0,
        "ot_hours": float(r.get("ot_hours") or 0),
        "basic": basic,
        "hra": hra, "conveyance": conv, "medical": med,
        "special": spl, "others": others,
        "monthly_gross": gross, "gross_paid": gross, "ot_pay": ot_pay,
        "stat_wage_base": gross,
        "pf_applicable": bool(pf_emp or pf_wages),
        "pf_wages": pf_wages, "pf_employee": pf_emp,
        "pf_employer_epf": round(er_pf - eps, 2), "pf_employer_eps": eps,
        "pf_employer_total": er_pf,
        "esic_applicable": bool(esic_er or esic_ee),
        "esic_wage_base": (gross if (esic_er or esic_ee) else 0),
        "esic_employee": esic_ee, "esic_employer": esic_er,
        "pt_state": None, "pt": pt, "tds": tds,
        "total_deduction": round(max(0.0, gross - net), 2),
        "net": net,
        "legacy_imported": True,
        "company_id": r.get("company_id"),
    }


_CMP_TOTAL_KEYS = (
    "basic", "hra", "conveyance", "medical", "special", "others",
    "monthly_gross", "gross_paid", "ot_pay",
    "pf_wages", "pf_employee", "pf_employer_epf", "pf_employer_eps", "pf_employer_total",
    "esic_wage_base", "esic_employee", "esic_employer",
    "pt", "tds", "total_deduction", "net",
)


async def _publish_compliance_job(job_id: str, company_id: str, admin_uid: str,
                                  lock: bool = False,
                                  only_months: Optional[List[str]] = None):
    async def _prog(**kw):
        await db.legacy_import_jobs.update_one(
            {"job_id": job_id}, {"$set": {**kw, "updated_at": _now()}})

    published: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []
    try:
        months = sorted(await db.legacy_salary_history.distinct(
            "month", {"company_id": company_id, "kind": "online"}))
        if only_months:
            keep = set(only_months)
            months = [m for m in months if m in keep]
        users: Dict[str, dict] = {}
        async for u in db.users.find(
                {"company_id": company_id, "role": "employee"},
                {"_id": 0, "user_id": 1, "employee_code": 1, "father_name": 1,
                 "designation": 1, "uan_no": 1, "esi_ip_no": 1,
                 "employee_type": 1, "salary_mode": 1}):
            users[u["user_id"]] = u
        for mon in months:
            try:
                # NEVER overwrite an existing run for that month (real or
                # previously published) — publishing is strictly additive.
                if await db.compliance_salary_runs.find_one(
                        {"company_id": company_id, "month": mon}, {"_id": 1}):
                    skipped.append(mon)
                    continue
                hrows = await db.legacy_salary_history.find(
                    {"company_id": company_id, "kind": "online", "month": mon},
                    {"_id": 0}).sort("name", 1).to_list(20000)
                rows = [_legacy_row_to_compliance(r, users.get(r.get("user_id")) or {})
                        for r in hrows]
                totals = {k: round(sum(float(r.get(k) or 0) for r in rows), 2)
                          for k in _CMP_TOTAL_KEYS}
                y, mn = int(mon[:4]), int(mon[5:7])
                run = {
                    "run_id": f"csrun_{uuid.uuid4().hex[:12]}",
                    "month": mon, "year": y, "month_number": mn,
                    "month_days": int(max((r.get("month_days") or 0) for r in hrows) or 30),
                    "default_month_days": 30,
                    "company_id": company_id,
                    "employee_type": None,
                    "is_onroll_filter": None,
                    "structure_pct": {}, "statutory_cfg": {},
                    "employees_count": len(rows),
                    "rows": rows,
                    "totals": totals,
                    "attendance_source": "legacy_import",
                    "legacy_imported": True,
                    # Iter 302b (user) — publish UNLOCKED first ("we will
                    # check, then lock accordingly"); lock-compliance
                    # endpoint finalizes everything afterwards.
                    "finalized": bool(lock),
                    **({"finalized_at": _now(), "finalized_by": admin_uid} if lock else {}),
                    "generated_by": admin_uid,
                    "generated_at": _now(),
                }
                await db.compliance_salary_runs.insert_one(run)
                published.append(mon)
            except Exception as ex:
                if len(errors) < 40:
                    errors.append(f"{mon}: {str(ex)[:120]}")
            await _prog(totals={"published": len(published), "skipped": len(skipped),
                                "months_total": len(months)})
        await _prog(status="done", errors=errors, finished_at=_now(),
                    totals={"published": len(published), "skipped": len(skipped),
                            "months_total": len(months),
                            "published_months": published[:60],
                            "skipped_months": skipped[:60]})
    except Exception as ex:
        errors.append(str(ex)[:300])
        await _prog(status="failed", errors=errors, finished_at=_now())


class PublishBody(BaseModel):
    company_id: str
    lock: bool = False
    # Iter 302c (user) — publish only the SELECTED months.
    months: Optional[List[str]] = None


@router.post("/admin/legacy-salary/publish-compliance")
async def legacy_publish_compliance(
    body: PublishBody, authorization: Optional[str] = Header(None),
):
    admin = await _super(authorization)
    # Iter 302d (user) — salary publish only for firms whose Employee
    # Master was already imported (rows must link to portal employees).
    emp_ok = await db.users.find_one(
        {"company_id": body.company_id, "role": "employee",
         "legacy_imported": True}, {"_id": 1})
    if not emp_ok:
        raise HTTPException(
            status_code=400,
            detail="Employee Master of this firm is NOT imported yet — import "
                   "employees first (Legacy Import Wizard), then publish salary.")
    months = await db.legacy_salary_history.distinct(
        "month", {"company_id": body.company_id, "kind": "online"})
    if body.months:
        months = [m for m in months if m in set(body.months)]
    if not months:
        raise HTTPException(
            status_code=404,
            detail="No imported ONLINE salary months for this firm — run the "
                   "Legacy Import Wizard first (or select at least one month).")
    job_id = f"lpub_{uuid.uuid4().hex[:10]}"
    await db.legacy_import_jobs.insert_one({
        "job_id": job_id, "type": "publish_compliance", "status": "running",
        "company_id": body.company_id, "totals": {}, "errors": [],
        "started_by": admin.get("user_id"), "started_at": _now(),
    })
    asyncio.get_event_loop().create_task(
        _publish_compliance_job(job_id, body.company_id, admin.get("user_id"),
                                lock=body.lock, only_months=body.months))
    return {"job_id": job_id, "months": len(months)}


@router.post("/admin/legacy-salary/lock-compliance")
async def legacy_lock_compliance(
    body: PublishBody, authorization: Optional[str] = Header(None),
):
    """Iter 302b (user) — after checking, LOCK all published legacy months
    (finalize every legacy_imported compliance run of the firm)."""
    admin = await _super(authorization)
    r = await db.compliance_salary_runs.update_many(
        {"company_id": body.company_id, "legacy_imported": True,
         "finalized": {"$ne": True}},
        {"$set": {"finalized": True, "finalized_at": _now(),
                  "finalized_by": admin.get("user_id")}})
    return {"ok": True, "locked": r.modified_count}
