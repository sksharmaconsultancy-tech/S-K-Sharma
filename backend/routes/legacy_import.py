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

from fastapi import APIRouter, Body, Header, HTTPException, Query
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


_MON3 = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05",
         "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
         "nov": "11", "dec": "12"}


def _month_key_any(*vals: Any) -> Optional[str]:
    """Iter 344 — derive 'YYYY-MM' from ANY legacy month column.
    Handles FirstDayOfMonth datetime/iso, MonthYear text like 'Feb 2019' /
    'February-2019' / '02-2019' / '2019-02' / '022019' / 201902."""
    for v in vals:
        if v is None or v == "":
            continue
        s = str(v).strip()
        # ISO datetime / 'YYYY-MM...'
        if len(s) >= 7 and s[4] in "-/" and s[:4].isdigit():
            return f"{s[:4]}-{s[5:7]}"
        low = s.lower().replace(",", " ").replace("-", " ").replace("/", " ")
        parts = [p for p in low.split() if p]
        if len(parts) == 2:
            a, b = parts
            # 'Feb 2019' / 'February 2019'
            if a[:3] in _MON3 and b.isdigit() and len(b) == 4:
                return f"{b}-{_MON3[a[:3]]}"
            # '2019 Feb'
            if b[:3] in _MON3 and a.isdigit() and len(a) == 4:
                return f"{a}-{_MON3[b[:3]]}"
            # '02 2019'
            if a.isdigit() and b.isdigit() and len(b) == 4 and 1 <= int(a) <= 12:
                return f"{b}-{int(a):02d}"
            # '2019 02'
            if a.isdigit() and b.isdigit() and len(a) == 4 and 1 <= int(b) <= 12:
                return f"{a}-{int(b):02d}"
        # '201902' or 201902 / '022019'
        if s.isdigit() and len(s) == 6:
            if 1 <= int(s[4:]) <= 12:
                return f"{s[:4]}-{s[4:]}"
            if 1 <= int(s[:2]) <= 12:
                return f"{s[2:]}-{s[:2]}"
    return None


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
        # Iter 305 (user, "data not match") — count EXACTLY like the import
        # does: the latest AcYear record per employee (EmpCode else EmpID),
        # with Active / Resigned split taken from that latest record.
        "SELECT FirmNo AS firm_no, COUNT(*) AS n, "
        "SUM(CASE WHEN ISNULL(IsResign, 0) = 1 THEN 1 ELSE 0 END) AS resigned "
        "FROM (SELECT FirmNo, IsResign, ROW_NUMBER() OVER ("
        "  PARTITION BY FirmNo, (CASE WHEN ISNULL(EmpCode, 0) > 0 THEN CAST(EmpCode AS VARCHAR(20)) "
        "                        ELSE 'id_' + CAST(EmpID AS VARCHAR(20)) END) "
        "  ORDER BY AcYear DESC, UID DESC) AS rn FROM EmployeeMaster) t "
        "WHERE rn = 1 GROUP BY FirmNo",
    )
    on_counts = await _q(
        dbn, "SELECT FirmNo AS firm_no, COUNT(*) AS n, COUNT(DISTINCT MonthYear) AS months "
             "FROM SalaryTrans WHERE DeletedDate IS NULL GROUP BY FirmNo")
    off_counts = await _q(
        dbn, "SELECT FirmNo AS firm_no, COUNT(*) AS n, COUNT(DISTINCT MonthYear) AS months "
             "FROM SalaryTransoff WHERE DeletedDate IS NULL GROUP BY FirmNo")
    ec = {e["firm_no"]: e["n"] for e in emp_counts}
    rc = {e["firm_no"]: int(e.get("resigned") or 0) for e in emp_counts}
    oc = {e["firm_no"]: e for e in on_counts}
    fc = {e["firm_no"]: e for e in off_counts}

    # Iter 342 (user bug — firm created then undo → "not showing in list"):
    # the portal list was capped at 300 firms, so newer firms fell off the
    # mapping dropdown while the duplicate-name check still found them.
    portal = await db.companies.find({}, {"_id": 0, "company_id": 1, "name": 1}).to_list(5000)
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
            "employees_resigned": rc.get(f["firm_no"], 0),
            "employees_active": max(0, ec.get(f["firm_no"], 0) - rc.get(f["firm_no"], 0)),
            "online_rows": (oc.get(f["firm_no"]) or {}).get("n", 0),
            "online_months": (oc.get(f["firm_no"]) or {}).get("months", 0),
            "offline_rows": (fc.get(f["firm_no"]) or {}).get("n", 0),
            "offline_months": (fc.get(f["firm_no"]) or {}).get("months", 0),
            "suggested_company_id": (sug or {}).get("company_id"),
            "suggested_company_name": (sug or {}).get("name"),
            "already_imported": f["firm_no"] in done,
            "imported_at": (done.get(f["firm_no"]) or {}).get("imported_at"),
            "imported_into": (done.get(f["firm_no"]) or {}).get("company_name"),
            "imported_company_id": (done.get(f["firm_no"]) or {}).get("company_id"),
        })
    # Iter 300b (user) — alphabetical order.
    out.sort(key=lambda x: x["firm_name"].lower())
    return {"db": dbn, "firms": out, "portal_firms": portal}


# --------------------------------------------------------------------------
# Preview / Run
# --------------------------------------------------------------------------
class FirmMap(BaseModel):
    firm_no: int
    # Iter 303 (user) — when the old firm has no match in the portal's Firm
    # Master, create_new=True creates it (with the legacy PF/ESI settings).
    company_id: Optional[str] = None
    create_new: bool = False


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
    # Iter 305 (user) — matched-name confirm: per firm (key = str(firm_no)),
    # the list of matched employee names to REPLACE (update). Matched names
    # NOT in the list are left untouched; new employees always import.
    replace_names: Optional[Dict[str, List[str]]] = None


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
        if m.create_new and not m.company_id:
            firm["company_name"] = "➕ NEW FIRM (will be created in Firm Master)"
            firm["create_new"] = True
        else:
            comp = await db.companies.find_one({"company_id": m.company_id}, {"_id": 0, "name": 1})
            firm["company_name"] = (comp or {}).get("name")
        if body.import_employees:
            emps = await _legacy_employees(dbn, m.firm_no)
            existing_names = set()
            existing_codes = set()
            if not (m.create_new and not m.company_id):
                for u in await db.users.find(
                        {"company_id": m.company_id, "role": "employee"},
                        {"_id": 0, "name": 1, "employee_code": 1}).to_list(20000):
                    if u.get("employee_code"):
                        existing_codes.add(str(u["employee_code"]).strip())
                    else:
                        existing_names.add(str(u.get("name") or "").strip().lower())
            # Iter 332 — count like the import: code-first matching.
            existing = 0
            for e in emps:
                code = e.get("EmpCode") if (e.get("EmpCode") or 0) > 0 else None
                if code is not None and str(code) in existing_codes:
                    existing += 1
                elif str(e.get("EmpName") or "").strip().lower() in existing_names:
                    existing += 1
            firm["employees_total"] = len(emps)
            firm["employees_existing"] = existing
            firm["employees_new"] = len(emps) - existing
            # Iter 331 (user request) — show which legacy allowance heads
            # will be set on the Firm Master (enabled or created).
            if "salary" in body.employee_fields:
                from routes.firm_master import ALLOWANCE_LABELS
                catalog = {x.strip().lower(): x for x in ALLOWANCE_LABELS}
                if m.company_id:
                    async for mm in db.masters.find(
                        {"type": "allowance",
                         "company_id": {"$in": [m.company_id, "__global__", None]}},
                        {"_id": 0, "name": 1},
                    ):
                        n_ = str(mm.get("name") or "").strip()
                        if n_:
                            catalog.setdefault(n_.lower(), n_)
                srows = await _q(
                    dbn,
                    "SELECT DISTINCT SalHeadName FROM EmployeeSalaryStructureDtl "
                    "WHERE FirmID_FK = %s AND UPPER(SalHeadType) LIKE 'ALLOW%%' "
                    "AND Amount > 0",
                    (m.firm_no,))
                heads_info = []
                for s in srows or []:
                    h = str(s.get("SalHeadName") or "").strip()
                    if not h:
                        continue
                    label = catalog.get(h.lower())
                    heads_info.append({
                        "head": h,
                        "label": label or h,
                        "action": "enable" if label else "create",
                        "bucket": _BUCKET_LABEL[_allow_bucket(h)],
                    })
                firm["allowance_heads"] = sorted(
                    heads_info, key=lambda x: x["head"].lower())
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


async def _parse_legacy_firm(dbn: str, firm_no: int) -> Dict[str, Any]:
    """Read the legacy FirmMaster row and normalise it into the portal's
    Firm-Master shaped settings (used by preview AND create)."""
    import re as _re

    rows = await _q(
        dbn,
        "SELECT TOP 1 * FROM FirmMaster WHERE FrimID = %s ORDER BY FnYear DESC",
        (firm_no,))
    if not rows:
        raise HTTPException(status_code=404, detail=f"Legacy firm {firm_no} not found")
    raw = rows[0]
    # normalised column lookup — legacy column names vary (Address/Add1/…).
    norm = {_re.sub(r"[^A-Z0-9]", "", str(k).upper()): v for k, v in raw.items()}

    def pick(*cands: str) -> Optional[str]:
        for c in cands:
            v = norm.get(c)
            if v is not None and str(v).strip() and str(v).strip().lower() not in ("none", "null", "0"):
                return str(v).strip()
        return None

    addr1 = pick("ADDRESS", "ADDRESS1", "ADD1", "FIRMADDRESS", "REGADDRESS")
    addr2 = pick("ADDRESS2", "ADD2")
    city = pick("CITY", "DISTRICT")
    state = pick("STATE")
    pin = pick("PINCODE", "PIN", "PINNO")
    return {
        "firm_no": firm_no,
        "name": pick("FIRMNAME") or f"Legacy Firm {firm_no}",
        "short_name": pick("SHORTNAME"),
        "address1": addr1, "address2": addr2,
        "city": city, "state": state, "pin_code": pin,
        "full_address": ", ".join(x for x in [addr1, addr2, city, state, pin] if x) or None,
        "email_1": pick("EMAIL", "EMAILID", "EMAIL1", "MAILID"),
        "email_2": pick("EMAIL2"),
        "start_date": pick("STARTDATE", "ESTDATE", "DOC", "REGDATE"),
        "business_nature": pick("BUSINESSNATURE", "NATUREOFBUSINESS", "NATURE"),
        "pf_no": pick("PFNO", "EPFNO", "PFCODE"),
        "esi_no": pick("ESINO", "ESICNO", "ESICODE"),
        "bank": {
            "account_no": pick("ACCOUNTNO", "ACNO", "BANKACNO", "BANKACCOUNTNO"),
            "account_name": pick("ACCOUNTNAME", "ACNAME", "NAMEONBANKAC"),
            "bank_name": pick("BANKNAME", "BANK"),
            "branch_name": pick("BRANCHNAME", "BRANCH", "BANKBRANCH"),
            "ifsc": pick("IFSCCODE", "IFSC"),
        },
        "docs": {"PAN": pick("PANNO", "PAN", "PANCARDNO"),
                 "TAN": pick("TANNO", "TAN"),
                 "GST": pick("GSTNO", "GSTIN", "GSTNUMBER"),
                 "LIN": pick("LINNO", "LIN")},
        "owner": pick("OWNERNAME", "PROPRIETOR", "CONTACTPERSON", "AUTHORISEDPERSON"),
        "phone": pick("MOBILENO", "MOBILE", "PHONENO", "PHONE", "CONTACTNO"),
        # Iter 303c (user) — statutory portal CREDENTIALS from legacy.
        "pf_user_id": pick("PFUSERID", "EPFUSERID", "PFLOGINID", "PFLOGIN", "PFUSER", "PFUSERNAME"),
        "pf_password": pick("PFPASSWORD", "EPFPASSWORD", "PFPWD", "PFPASS"),
        "esi_user_id": pick("ESIUSERID", "ESICUSERID", "ESILOGINID", "ESILOGIN", "ESIUSER", "ESIUSERNAME"),
        "esi_password": pick("ESIPASSWORD", "ESICPASSWORD", "ESIPWD", "ESIPASS"),
    }


@router.get("/admin/legacy-import/firm-preview/{firm_no}")
async def legacy_firm_preview(firm_no: int, authorization: Optional[str] = Header(None)):
    """Iter 303b (user) — 'show first what you get after create firm'."""
    await _super(authorization)
    dbn = await _dbname()
    p = await _parse_legacy_firm(dbn, firm_no)
    # never expose raw passwords in the preview — masked indicators only.
    p["pf_password"] = "••••••" if p.get("pf_password") else None
    p["esi_password"] = "••••••" if p.get("esi_password") else None
    dup = await db.companies.find_one(
        {"name": {"$regex": f"^{_rx(p['name'])}$", "$options": "i"}},
        {"_id": 0, "company_id": 1, "name": 1})
    p["duplicate_company"] = dup
    return p


async def _create_company_from_legacy(dbn: str, firm_no: int, admin_uid: str) -> str:
    """Iter 303 (user) — create a NEW portal firm from the legacy FirmMaster
    row, carrying over its SETTINGS too: name, address, emails, phone,
    PF/ESI registrations, bank details and PAN/TAN/GST document numbers."""
    from server import Company, _policy_for_category
    from routes.firm_master import _empty_master

    p = await _parse_legacy_firm(dbn, firm_no)
    name = p["name"]
    dup = await db.companies.find_one(
        {"name": {"$regex": f"^{_rx(name)}$", "$options": "i"}},
        {"_id": 0, "company_id": 1})
    if dup:
        return dup["company_id"]

    company = Company(
        name=name, address=p["full_address"], office_lat=0.0, office_lng=0.0,
        geofence_radius_m=200, compliance_enabled=True,
    ).model_dump()
    company["attendance_policy"] = _policy_for_category(None, None)
    company["created_by"] = admin_uid
    company["legacy_imported"] = True
    company["legacy_firm_no"] = firm_no
    await db.companies.insert_one(company)

    # ---- Firm Master settings from the legacy row ----
    fm = _empty_master(company["company_id"], name)
    fm["registered_address"].update(
        {"address1": p["address1"], "address2": p["address2"], "city": p["city"],
         "state": p["state"], "pin_code": p["pin_code"]})
    fm["header"]["email_1"] = p["email_1"]
    fm["header"]["email_2"] = p["email_2"]
    fm["header"]["start_date"] = p["start_date"]
    fm["header"]["business_nature"] = p["business_nature"]
    if p["pf_no"]:
        fm["epf"]["epf_no"] = p["pf_no"]
        fm["epf"]["applicable"] = True
    if p["esi_no"]:
        fm["esi"]["esi_no"] = p["esi_no"]
        fm["esi"]["applicable"] = True
    # Iter 303c (user) — carry over portal credentials from legacy.
    if p.get("pf_user_id"):
        fm["epf"]["epf_user_id"] = p["pf_user_id"]
    if p.get("pf_password"):
        fm["epf"]["epf_password"] = p["pf_password"]
    if p.get("esi_user_id"):
        fm["esi"]["esi_user_id"] = p["esi_user_id"]
    if p.get("esi_password"):
        fm["esi"]["esi_password"] = p["esi_password"]
    fm["bank"].update(p["bank"])
    for d in fm.get("compliance_docs") or []:
        du = str(d.get("description") or "").upper()
        for key, val in (p["docs"] or {}).items():
            if val and key in du and not d.get("number"):
                d["number"] = val
    # GST has no fixed label in the catalog — append it as its own doc.
    if (p["docs"] or {}).get("GST"):
        fm["compliance_docs"].append(
            {"description": "GST NO.", "number": p["docs"]["GST"],
             "issue_date": None, "expiry_date": None})
    # Portal logins list — fill PF / ESI login rows from legacy credentials.
    for pl in fm.get("portal_logins") or []:
        lt = str(pl.get("login_type") or "").upper()
        if "PF" in lt and p.get("pf_user_id"):
            pl["user_name"] = p["pf_user_id"]
            pl["password"] = p.get("pf_password")
        if "ESI" in lt and p.get("esi_user_id"):
            pl["user_name"] = p["esi_user_id"]
            pl["password"] = p.get("esi_password")
    if p["phone"] or p["owner"]:
        fm["contact_persons"] = [{"name": p["owner"], "mobile": p["phone"], "position": "Owner"}]
    fm["updated_at"] = _now()
    fm["updated_by"] = admin_uid
    await db.firm_masters.update_one(
        {"company_id": company["company_id"]}, {"$set": fm}, upsert=True)
    return company["company_id"]


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
        # Iter 333 (user bug: allowances not fetching) — match the head
        # type loosely: ALLOWANCE / ALLOWANCES / Allow… all count.
        allow = [
            {"head": str(s.get("SalHeadName") or "").strip(), "amount": float(s.get("Amount") or 0)}
            for s in structure
            if str(s.get("SalHeadType") or "").strip().upper().startswith("ALLOW")
            and _f(s.get("Amount"))
        ]
        # Iter 347 (user bug: SUVIDHI — old DB salary structure ≠ portal
        # structure) — the old software's CURRENT structure lives head-wise
        # in EmployeeSalaryStructureDtl; EmployeeMaster.BasicSalary/GrossPay
        # can be STALE (old revision). Prefer the structure's BASIC head and
        # derive Gross = Basic + allowances whenever structure rows exist.
        struct_basic = 0.0
        for s in structure:
            t = str(s.get("SalHeadType") or "").strip().upper()
            n = str(s.get("SalHeadName") or "").strip().lower()
            if t.startswith("BASIC") or (not t.startswith("ALLOW")
                                         and not t.startswith("DEDUCT")
                                         and "basic" in n):
                struct_basic = _f(s.get("Amount")) or 0.0
                break
        basic = struct_basic or _f(e.get("BasicSalary"))
        gross = _f(e.get("GrossPay"))
        if structure and (struct_basic or allow):
            struct_gross = (struct_basic or _f(e.get("BasicSalary")) or 0.0) \
                + sum(a["amount"] for a in allow)
            if struct_gross > 0:
                gross = struct_gross
        doc.update({
            "basic_salary": basic,
            "compliance_basic": basic,
            "pf_basic": _f(e.get("PFBasicSalary")),
            "compliance_gross": gross,
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


# Iter 331 (user request) — legacy allowance heads AUTO-SET on the Firm
# Master. Every allowance head found in the old database (per firm) is
# matched against the Firm Master Allowances catalog and switched ON; a
# head with no matching label is CREATED as a custom allowance master and
# then enabled — so the imported employee allowances flow into the
# Compliance Salary under the same heads.
_BUCKET_LABEL = {
    "hra": "HRA",
    "conveyance": "CONV.",
    "medical": "MEDICAL ALLOWANCES",
    "special": "OTH. ALLOW.",
    "others": "OTHER MISC.ALLOWANCE",
}


def _allow_bucket(head: str) -> str:
    """Mirror utils.compliance_salary head→column mapping."""
    s = str(head or "").strip().lower()
    if "hra" in s or "house" in s:
        return "hra"
    if s.startswith("conv") or "travel" in s:
        return "conveyance"
    if "medic" in s:
        return "medical"
    if "special" in s:
        return "special"
    return "others"


async def _sync_firm_allowances(
    company_id: str, heads: set, admin_uid: str = "",
) -> Dict[str, list]:
    """Enable legacy allowance heads on the Firm Master (create custom
    heads that don't exist in the catalog). Returns what was done."""
    from routes.firm_master import ALLOWANCE_LABELS
    if not heads:
        return {"enabled": [], "created": []}
    # Catalog = fixed labels + custom allowance masters for this firm.
    catalog: Dict[str, str] = {x.strip().lower(): x for x in ALLOWANCE_LABELS}
    async for mm in db.masters.find(
        {"type": "allowance",
         "company_id": {"$in": [company_id, "__global__", None]}},
        {"_id": 0, "name": 1},
    ):
        n = str(mm.get("name") or "").strip()
        if n:
            catalog.setdefault(n.lower(), n)
    fm = await db.firm_masters.find_one(
        {"company_id": company_id}, {"_id": 0, "allowances": 1})
    current = dict((fm or {}).get("allowances") or {})
    to_enable: set = set()
    created: List[str] = []
    for head in sorted({str(h or "").strip() for h in heads} - {""}):
        bucket = _allow_bucket(head)
        label = catalog.get(head.lower())
        if not label and bucket != "others":
            # HRA / Conveyance / Medical / Special heads map into the
            # standard Firm Master label (e.g. "Conveyance" → "CONV.") —
            # no duplicate custom head is created.
            label = _BUCKET_LABEL[bucket]
        if not label:
            # No matching label — create a custom allowance head.
            await db.masters.insert_one({
                "master_id": f"mst_{uuid.uuid4().hex[:12]}",
                "type": "allowance",
                "company_id": company_id,
                "name": head,
                "date": None,
                "created_at": _now(),
                "updated_at": _now(),
                "created_by": admin_uid or "legacy_import",
                "scope": "firm",
                "auto_registered": "legacy_import_allowances",
            })
            catalog[head.lower()] = head
            created.append(head)
            label = head
        to_enable.add(label)
        # Always ALSO enable the compliance bucket label so the run's
        # allowance mask keeps this head's column (HRA / CONV. / etc.).
        to_enable.add(_BUCKET_LABEL[bucket])
    newly = sorted(lb for lb in to_enable if current.get(lb) is not True)
    if newly:
        # NOTE: labels like "CONV." / "OTH. ALLOW." contain dots — a dotted
        # $set path ("allowances.CONV.") is invalid in MongoDB. Merge and
        # write the whole allowances object instead.
        merged = dict(current)
        for lb in newly:
            merged[lb] = True
        await db.firm_masters.update_one(
            {"company_id": company_id},
            {"$set": {"allowances": merged, "updated_at": _now()}},
            upsert=True,
        )
    return {"enabled": newly, "created": created}


async def _run_job(job_id: str, body: ImportBody, admin_uid: str = ""):
    dbn = await _dbname()
    heads = await _head_names(dbn)

    async def _prog(**kw):
        await db.legacy_import_jobs.update_one({"job_id": job_id}, {"$set": {**kw, "updated_at": _now()}})

    totals = {"employees_created": 0, "employees_updated": 0, "employees_skipped": 0,
              # Iter 340 (user request) — Active vs Resigned import counts.
              "employees_active": 0, "employees_resigned": 0,
              "online_rows": 0, "offline_rows": 0, "firms_created": 0}
    errors: List[str] = []
    try:
        for m in body.mappings:
            await _prog(status="running", current_firm=m.firm_no)
            # Iter 303 (user) — no matching firm in the portal? create it
            # from the legacy FirmMaster (name + PF/ESI settings).
            if m.create_new and not m.company_id:
                m.company_id = await _create_company_from_legacy(dbn, m.firm_no, admin_uid)
                totals["firms_created"] += 1
                await _prog(totals=totals)
            emp_uid: Dict[Any, str] = {}

            # ---------------- Employees ----------------
            if body.import_employees:
                _ml: Dict[str, set] = {"group": set(), "department": set(), "designation": set()}
                emps = await _legacy_employees(dbn, m.firm_no)
                # head-wise structure rows for this firm (salary group)
                struct_by_emp: Dict[int, List[dict]] = {}
                emp_ids_by_code: Dict[int, List[int]] = {}
                if "salary" in body.employee_fields:
                    # Iter 348 (user: "Still showing old salary structure")
                    # — EmployeeSalaryStructureDtl.FirmID_FK does NOT always
                    # equal our firm_no (per-year FirmMaster ids). Join via
                    # EmpID_FK → EmployeeMaster.FirmNo, which is the key we
                    # already trust everywhere else.
                    srows = await _q(
                        dbn,
                        "SELECT d.EmpID_FK, d.SalHeadType, d.SalHeadName, d.Amount "
                        "FROM EmployeeSalaryStructureDtl d "
                        "JOIN EmployeeMaster em ON em.EmpID = d.EmpID_FK "
                        "WHERE em.FirmNo = %s",
                        (m.firm_no,),
                    )
                    for s in srows:
                        struct_by_emp.setdefault(int(s.get("EmpID_FK") or 0), []).append(s)
                    # Iter 333 (user bug: allowances not fetching) — the
                    # structure may only exist under an OLDER AcYear's
                    # EmpID for the same EmpCode. Build code → EmpIDs
                    # (latest year first) so we can fall back.
                    id_rows = await _q(
                        dbn,
                        "SELECT EmpID, EmpCode FROM EmployeeMaster "
                        "WHERE FirmNo = %s ORDER BY AcYear DESC, UID DESC",
                        (m.firm_no,))
                    for r0 in id_rows:
                        c0 = r0.get("EmpCode") if (r0.get("EmpCode") or 0) > 0 else None
                        if c0 is not None:
                            emp_ids_by_code.setdefault(
                                int(c0), []).append(int(r0.get("EmpID") or 0))
                    # Diagnostic — structure exists but nothing looks like
                    # an allowance? Surface the real type names.
                    if srows and not any(
                            str(s.get("SalHeadType") or "").strip().upper().startswith("ALLOW")
                            for s in srows):
                        _types = sorted({str(s.get("SalHeadType") or "").strip()
                                         for s in srows})[:8]
                        errors.append(
                            f"firm {m.firm_no}: salary structure has no "
                            f"ALLOWANCE-type heads; types present: {_types}")

                def _struct_for(e0: dict) -> List[dict]:
                    rows_ = struct_by_emp.get(int(e0.get("EmpID") or 0), [])
                    if rows_:
                        return rows_
                    c0 = e0.get("EmpCode") if (e0.get("EmpCode") or 0) > 0 else None
                    if c0 is not None:
                        for eid in emp_ids_by_code.get(int(c0), []):
                            rows_ = struct_by_emp.get(eid, [])
                            if rows_:
                                return rows_
                    return []
                for e in emps:
                    try:
                        nm = str(e.get("EmpName") or "").strip()
                        if not nm:
                            totals["employees_skipped"] += 1
                            continue
                        fields = _emp_doc_fields(
                            e, body.employee_fields,
                            _struct_for(e),
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
                        # Iter 340 (user bug: E11000 duplicate email —
                        # KRIPA SHARAN SHARMA case) — the same email on two
                        # legacy employees breaks the unique users.email
                        # index. Drop the duplicate email rather than fail
                        # the whole employee.
                        if fields.get("email"):
                            _eclash = await db.users.find_one(
                                {"email": fields["email"]}, {"_id": 1})
                            if _eclash:
                                fields["email"] = None
                        code = e.get("EmpCode") if (e.get("EmpCode") or 0) > 0 else None
                        # Iter 332 (user bug: SUVIDHI RAYONS — 2548 emp
                        # imported as ~1000) — match by EMPLOYEE CODE first.
                        # Name-only matching merged every duplicate name
                        # into one record. Name fallback only applies when
                        # the legacy row has no code, or to enrich a portal
                        # employee that has no code yet.
                        existing = None
                        if code is not None:
                            existing = await db.users.find_one(
                                {"company_id": m.company_id, "role": "employee",
                                 "employee_code": str(code)},
                                {"_id": 0, "user_id": 1})
                        if existing is None:
                            q = {"company_id": m.company_id, "role": "employee",
                                 "name": {"$regex": f"^{_rx(nm)}$", "$options": "i"}}
                            if code is not None:
                                # legacy row HAS a code → only enrich a
                                # same-name portal employee without a code
                                # (never merge two coded employees).
                                q["$or"] = [
                                    {"employee_code": None},
                                    {"employee_code": ""},
                                    {"employee_code": {"$exists": False}},
                                ]
                            existing = await db.users.find_one(q, {"_id": 0, "user_id": 1})
                        if existing:
                            # Iter 305 (user) — replace only CONFIRMED names.
                            repl = (body.replace_names or {}).get(str(m.firm_no))
                            if repl is not None and nm.strip().lower() not in {
                                    str(x).strip().lower() for x in repl}:
                                totals["employees_kept"] = totals.get("employees_kept", 0) + 1
                            else:
                                fields.pop("phone", None)
                                fields.pop("email", None)
                                if code is not None:
                                    # backfill the code on a name-matched
                                    # portal employee so future imports
                                    # match by code directly.
                                    fields.setdefault("employee_code", str(code))
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
                            try:
                                await db.users.insert_one(doc)
                            except Exception as _dk:
                                # Iter 340 — any residual unique-index clash
                                # (email/phone): retry once without them.
                                if "E11000" in str(_dk):
                                    doc["email"] = None
                                    doc["phone"] = None
                                    doc.pop("_id", None)
                                    await db.users.insert_one(doc)
                                else:
                                    raise
                            totals["employees_created"] += 1
                            # Iter 340 — Active / Resigned import counts.
                            if doc.get("employment_status") == "resigned" \
                                    or bool(e.get("IsResign")):
                                totals["employees_resigned"] += 1
                            else:
                                totals["employees_active"] += 1
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
                # Iter 331 (user request) — auto-set the legacy allowance
                # heads on the Firm Master (enable matching labels, create
                # missing ones) so imported allowances land in Compliance
                # Salary under the same heads.
                if "salary" in body.employee_fields:
                    try:
                        _heads = {
                            str(s.get("SalHeadName") or "").strip()
                            for rows_ in struct_by_emp.values() for s in rows_
                            if str(s.get("SalHeadType") or "").strip().upper().startswith("ALLOW")
                            and _f(s.get("Amount"))
                        }
                        _sync = await _sync_firm_allowances(
                            m.company_id, _heads, admin_uid)
                        if _sync["enabled"] or _sync["created"]:
                            totals["allowance_labels_enabled"] = (
                                totals.get("allowance_labels_enabled", 0)
                                + len(_sync["enabled"]))
                            totals["allowance_heads_created"] = (
                                totals.get("allowance_heads_created", 0)
                                + len(_sync["created"]))
                            await db.legacy_import_jobs.update_one(
                                {"job_id": job_id},
                                {"$push": {"allowance_sync": {
                                    "firm_no": m.firm_no,
                                    "company_id": m.company_id,
                                    **_sync,
                                }}})
                    except Exception as ex:
                        if len(errors) < 40:
                            errors.append(f"allowance sync: {str(ex)[:120]}")
                await _prog(totals=totals)

            # ---------------- Salary history ----------------
            off_latest: Dict[Any, dict] = {}   # Iter 333 — off-roll workers
            for kind, table in (("online", "SalaryTrans"), ("offline", "SalaryTransoff")):
                if kind == "online" and not body.salary_online:
                    continue
                if kind == "offline" and not body.salary_offline:
                    continue
                await db.legacy_salary_history.delete_many(
                    {"company_id": m.company_id, "kind": kind, "firm_no": m.firm_no})
                skip = 0
                while True:
                    # Iter 344 (user bug — offline rows "not getting"):
                    # some legacy DB versions differ in schema; fall back
                    # to a filter-free query and skip deleted rows in
                    # Python instead of failing the whole kind.
                    try:
                        rows = await _q(
                            dbn,
                            f"SELECT * FROM {table} WHERE FirmNo = %s AND DeletedDate IS NULL "
                            f"ORDER BY UID OFFSET {skip} ROWS FETCH NEXT 2000 ROWS ONLY",
                            (m.firm_no,),
                        )
                    except Exception:
                        rows = await _q(
                            dbn,
                            f"SELECT * FROM {table} WHERE FirmNo = %s "
                            f"ORDER BY (SELECT NULL) OFFSET {skip} ROWS FETCH NEXT 2000 ROWS ONLY",
                            (m.firm_no,),
                        )
                    if not rows:
                        break
                    docs = []
                    for r in rows:
                        # Iter 344 — legacy column names vary in CASE between
                        # installations (e.g. FirstDayofMonth); match keys
                        # case-insensitively so rows are never skipped.
                        rl = {str(k).lower(): v for k, v in r.items()}
                        if rl.get("deleteddate"):
                            continue
                        # Iter 344 — SalaryTransoff may carry the month ONLY
                        # in MonthYear ('Feb 2019'); fall back to it so
                        # offline rows are never dropped for a missing
                        # FirstDayOfMonth.
                        mon = _month_key_any(
                            rl.get("firstdayofmonth"), rl.get("monthyear"))
                        if not mon:
                            totals[f"{kind}_skipped_no_month"] = (
                                totals.get(f"{kind}_skipped_no_month", 0) + 1)
                            continue
                        try:
                            _ec = int(float(rl.get("empcode")))
                        except (TypeError, ValueError):
                            _ec = 0
                        code = _ec if _ec > 0 else None
                        base = {
                            "company_id": m.company_id,
                            "firm_no": m.firm_no,
                            "kind": kind,
                            "month": mon,
                            "emp_code": code,
                            "emp_id": rl.get("empid"),
                            "user_id": emp_uid.get(code) if code else emp_uid.get(f"id_{rl.get('empid')}"),
                            "name": str(rl.get("empname") or "").strip(),
                            "employee_type": (str(rl.get("emptype") or "").strip() or None),
                            "month_days": rl.get("monthdays"),
                            "present_days": _f(rl.get("presentdays")) or 0,
                            "basic": _f(rl.get("tbasicsalary")) or _f(rl.get("basicsalary")) or 0,
                            "gross": _f(rl.get("grosssalary")) or 0,
                            "net": _f(rl.get("netsalary")) or 0,
                        }
                        if kind == "online":
                            earn = {}
                            ded = {}
                            for i in range(1, 26):
                                v = _f(rl.get(f"earn{i}"))
                                if v:
                                    earn[heads.get(f"Earn{i}", f"Earn{i}")] = v
                            for i in range(1, 21):
                                v = _f(rl.get(f"deduct{i}"))
                                if v:
                                    ded[heads.get(f"Deduct{i}", f"Deduct{i}")] = v
                            base.update({
                                "earn_heads": earn, "deduct_heads": ded,
                                # Iter 302f (user) — month's MASTER rates
                                # (full-month salary) alongside earned.
                                "master_basic": _f(rl.get("basicsalary")),
                                "master_pf_basic": _f(rl.get("pfbasicsalary")),
                                "pf_basic": _f(rl.get("t_pfbasicsalary")),
                                "ee_pf": _f(rl.get("ee_epf")),
                                "er_pf": (_f(rl.get("er_epf")) or 0) + (_f(rl.get("er_fpf")) or 0) or None,
                                "er_esi": _f(rl.get("er_esi")),
                                "less_adv": _f(rl.get("lessadv")),
                                "less_other": _f(rl.get("lessother")),
                                "less_loan": _f(rl.get("lessloan")),
                                "less_total": _f(rl.get("lesstotal")),
                                "ot_hours": _f(rl.get("otworkhours")),
                            })
                        else:
                            base.update({
                                "rate": _f(rl.get("salaryrate")),
                                "w_basic": _f(rl.get("wbasicsalary")),
                                "others": _f(rl.get("tother")),
                                "tds": _f(rl.get("tds")),
                                "work_hours": _f(rl.get("workhours")),
                                "less_epf": _f(rl.get("lessepf")),
                                "less_esi": _f(rl.get("lessesi")),
                                "less_adv": _f(rl.get("lessadv")),
                                "less_other": _f(rl.get("lessother")),
                                "less_loan": _f(rl.get("lessloan")),
                                "less_total": _f(rl.get("lesstotal")),
                            })
                            # Iter 333 (user request) — remember the LATEST
                            # off-roll row per worker so we can create the
                            # missing OFF-ROLL employees with their master
                            # salary rate after the history import.
                            _okey = int(code) if code else f"id_{rl.get('empid')}"
                            _prev = off_latest.get(_okey)
                            if _prev is None or mon > _prev["month"]:
                                off_latest[_okey] = {
                                    "month": mon,
                                    "code": code,
                                    "emp_id": rl.get("empid"),
                                    "name": str(rl.get("empname") or "").strip(),
                                    "employee_type": (str(rl.get("emptype") or "").strip() or None),
                                    "rate": _f(rl.get("salaryrate")) or 0,
                                }
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

            # Iter 333 (user request) — CREATE the OFF-ROLL employees found
            # in the offline salary history (SalaryTransoff) that are not
            # in the portal yet, with their master salary rate. Existing
            # employees only get the rate backfilled when they have none.
            if body.import_employees and body.salary_offline and off_latest:
                for okey, w in off_latest.items():
                    try:
                        nm = w["name"]
                        if not nm:
                            continue
                        code = w["code"]
                        uid = emp_uid.get(int(code)) if code else emp_uid.get(f"id_{w['emp_id']}")
                        existing = None
                        if uid:
                            existing = await db.users.find_one(
                                {"user_id": uid},
                                {"_id": 0, "user_id": 1, "salary_structure_actual": 1})
                        if existing is None and code is not None:
                            existing = await db.users.find_one(
                                {"company_id": m.company_id, "role": "employee",
                                 "employee_code": str(code)},
                                {"_id": 0, "user_id": 1, "salary_structure_actual": 1})
                        if existing is None:
                            existing = await db.users.find_one(
                                {"company_id": m.company_id, "role": "employee",
                                 "name": {"$regex": f"^{_rx(nm)}$", "$options": "i"}},
                                {"_id": 0, "user_id": 1, "salary_structure_actual": 1})
                        rate_struct = ([{"head": "Basic Salary", "amount": w["rate"],
                                         "rate_type": "daily"}] if w["rate"] else None)
                        if existing:
                            if rate_struct and not existing.get("salary_structure_actual"):
                                await db.users.update_one(
                                    {"user_id": existing["user_id"]},
                                    {"$set": {"salary_structure_actual": rate_struct}})
                                totals["offroll_rate_backfilled"] = (
                                    totals.get("offroll_rate_backfilled", 0) + 1)
                            uid = existing["user_id"]
                        else:
                            doc = {
                                "user_id": f"user_{uuid.uuid4().hex[:12]}",
                                "role": "employee",
                                "company_id": m.company_id,
                                "name": nm,
                                "employee_code": (str(code) if code else None),
                                "employee_type": w["employee_type"],
                                "employee_group": w["employee_type"],
                                "is_onroll": False,
                                "salary_mode": "daily",
                                "onboarded": True,
                                "approval_status": "approved",
                                "has_pin": False,
                                "picture": None,
                                "phone": None,
                                "email": None,
                                "created_at": _now(),
                                "legacy_imported": True,
                                "legacy_firm_no": m.firm_no,
                                "legacy_emp_id": w["emp_id"],
                                "legacy_offroll": True,
                            }
                            if rate_struct:
                                doc["salary_structure_actual"] = rate_struct
                            await db.users.insert_one(doc)
                            totals["offroll_created"] = (
                                totals.get("offroll_created", 0) + 1)
                            uid = doc["user_id"]
                        # link their offline history rows
                        _hq: Dict[str, Any] = {
                            "company_id": m.company_id, "kind": "offline",
                            "firm_no": m.firm_no, "user_id": None}
                        if code:
                            _hq["emp_code"] = code
                        else:
                            _hq["emp_id"] = w["emp_id"]
                        await db.legacy_salary_history.update_many(
                            _hq, {"$set": {"user_id": uid}})
                    except Exception as ex:
                        if len(errors) < 40:
                            errors.append(f"off-roll {w.get('name')}: {str(ex)[:120]}")
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


@router.post("/admin/legacy-import/employee-compare")
async def legacy_employee_compare(body: ImportBody, authorization: Optional[str] = Header(None)):
    """Iter 305 (user) — Comparison Record, grouped firm-wise: matched
    names (with field-level old→new changes) for Replace-or-Not confirm,
    plus the NEW names that will import regardless."""
    await _super(authorization)
    dbn = await _dbname()

    def _neq(old: Any, new: Any) -> bool:
        if old is None and new is None:
            return False
        try:
            return abs(float(old) - float(new)) > 0.01
        except (TypeError, ValueError):
            pass
        return str(old or "").strip().upper() != str(new or "").strip().upper()

    firms = []
    for m in body.mappings:
        emps = await _legacy_employees(dbn, m.firm_no)
        create_new = bool(m.create_new and not m.company_id)
        comp = None if create_new else await db.companies.find_one(
            {"company_id": m.company_id}, {"_id": 0, "name": 1})
        users: Dict[str, dict] = {}
        by_code: Dict[str, dict] = {}
        if not create_new:
            async for u in db.users.find(
                    {"company_id": m.company_id, "role": "employee"}, {"_id": 0}):
                users[str(u.get("name") or "").strip().lower()] = u
                if u.get("employee_code"):
                    by_code[str(u["employee_code"]).strip()] = u
        matched, new_names = [], []
        active = resigned = 0
        for e in emps:
            nm = str(e.get("EmpName") or "").strip()
            if not nm:
                continue
            if e.get("IsResign"):
                resigned += 1
            else:
                active += 1
            # Iter 332 — same matching as the import: code first, then a
            # name-match only against a portal employee without a code.
            code = e.get("EmpCode") if (e.get("EmpCode") or 0) > 0 else None
            u = by_code.get(str(code)) if code is not None else None
            if u is None:
                u = users.get(nm.lower())
                if u is not None and code is not None and u.get("employee_code"):
                    u = None
            if not u:
                new_names.append(nm)
                continue
            doc = _emp_doc_fields(e, body.employee_fields, [],
                                  overrides=body.field_overrides)
            doc.pop("compliance_salary_allowances", None)
            changes = [
                {"field": k, "old": u.get(k), "new": v}
                for k, v in doc.items()
                if v is not None and k not in ("phone", "email") and _neq(u.get(k), v)
            ]
            matched.append({"name": nm, "employee_code": u.get("employee_code"),
                            "changes": changes[:25], "change_count": len(changes)})
        matched.sort(key=lambda x: x["name"])
        new_names.sort()
        firms.append({
            "firm_no": m.firm_no,
            "company_id": m.company_id,
            "company_name": "➕ NEW FIRM (will be created)" if create_new
                            else (comp or {}).get("name"),
            "total": len(emps), "active": active, "resigned": resigned,
            "matched_count": len(matched), "new_count": len(new_names),
            "matched": matched[:400], "new_names": new_names[:400],
        })
    return {"firms": firms}


@router.post("/admin/legacy-import/run")
async def legacy_import_run(body: ImportBody, authorization: Optional[str] = Header(None)):
    admin = await _super(authorization)
    if not body.mappings:
        raise HTTPException(status_code=400, detail="Map at least one firm")
    for m in body.mappings:
        if not m.company_id and not m.create_new:
            raise HTTPException(
                status_code=400,
                detail=f"Firm {m.firm_no}: map it to a portal firm or choose "
                       "'Create NEW firm'.")
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
    asyncio.get_event_loop().create_task(_run_job(job_id, body, admin.get("user_id") or ""))
    return {"job_id": job_id}


@router.get("/admin/legacy-salary/firms")
async def legacy_salary_firms(authorization: Optional[str] = Header(None)):
    """Iter 304b (user) — only firms whose legacy data was imported
    successfully, with SALARY IMPORTED / LOCKED status badges."""
    await _super(authorization)
    cids = await db.legacy_salary_history.distinct("company_id")
    comps = await db.companies.find(
        {"company_id": {"$in": cids}},
        {"_id": 0, "company_id": 1, "name": 1}).sort("name", 1).to_list(5000)
    # Iter 304c (user) — mark published (salary imported) + locked firms.
    for c in comps:
        pub = await db.compliance_salary_runs.count_documents(
            {"company_id": c["company_id"], "legacy_imported": True})
        locked = await db.compliance_salary_runs.count_documents(
            {"company_id": c["company_id"], "legacy_imported": True,
             "finalized": True})
        c["published_months"] = pub
        c["locked_months"] = locked
        c["fully_locked"] = bool(pub and locked == pub)
    return {"companies": comps}


# Iter 303 (user, A-ONE MOTOR'S case) — UNDO a firm's import: removes the
# legacy-created employees, imported salary history and published legacy
# runs, and unlocks the firm so it can be re-imported (e.g. into a newly
# created firm). Pre-existing employees that were merely enriched are kept.
class UndoBody(BaseModel):
    firm_no: int
    company_id: str


@router.post("/admin/legacy-import/missing")
async def legacy_import_missing(body: ImportBody, authorization: Optional[str] = Header(None)):
    """Iter 340 (user request) — OLD DATABASE vs PORTAL difference list:
    every legacy employee that did NOT land in the portal, with the
    REASON it was not imported."""
    await _super(authorization)
    dbn = await _dbname()
    firms: List[dict] = []
    for m in body.mappings:
        if not m.company_id:
            continue
        emps = await _legacy_employees(dbn, m.firm_no)
        portal = await db.users.find(
            {"company_id": m.company_id, "role": "employee"},
            {"_id": 0, "name": 1, "employee_code": 1},
        ).to_list(25000)
        by_code = {str(u["employee_code"]): u for u in portal if u.get("employee_code")}
        by_name: Dict[str, list] = {}
        for u in portal:
            by_name.setdefault(str(u.get("name") or "").strip().lower(), []).append(u)
        job = await db.legacy_import_jobs.find_one(
            {"mappings.firm_no": m.firm_no}, {"_id": 0, "errors": 1},
            sort=[("started_at", -1)])
        errs = (job or {}).get("errors") or []
        missing: List[dict] = []
        for e in emps:
            nm = str(e.get("EmpName") or "").strip()
            code = e.get("EmpCode") if (e.get("EmpCode") or 0) > 0 else None
            resigned = bool(e.get("IsResign"))
            if not nm:
                missing.append({"emp_code": code, "name": "(blank name)",
                                "resigned": resigned,
                                "reason": "Blank employee name in the old database"})
                continue
            if code is not None and str(code) in by_code:
                continue  # imported (matched by Employee Code)
            if by_name.get(nm.lower()):
                continue  # imported / merged into a same-name portal employee
            reason = None
            _pfx = f"emp {nm}"
            for er in errs:
                if str(er).startswith(_pfx):
                    reason = f"Import error: {str(er)[len(_pfx) + 2:][:160]}"
                    break
            missing.append({
                "emp_code": code, "name": nm, "resigned": resigned,
                "reason": reason or ("Not found in the portal — record was "
                                     "skipped during import (no error "
                                     "captured); re-import the firm"),
            })
        firms.append({
            "firm_no": m.firm_no, "company_id": m.company_id,
            "legacy_count": len(emps), "portal_count": len(portal),
            "missing_count": len(missing), "missing": missing,
        })
    return {"firms": firms}


@router.post("/admin/legacy-import/undo")
async def legacy_import_undo(body: UndoBody, authorization: Optional[str] = Header(None)):
    await _super(authorization)
    u = await db.users.delete_many({
        "company_id": body.company_id, "role": "employee",
        "legacy_imported": True, "legacy_firm_no": body.firm_no})
    # Iter 332 (user request) — UNDO also releases the employee lock on any
    # remaining employees of this firm (delete/update allowed again).
    unlocked = await db.users.update_many(
        {"company_id": body.company_id, "role": "employee",
         "legacy_locked": True},
        {"$unset": {"legacy_locked": "", "legacy_locked_at": "",
                    "legacy_locked_by": ""}})
    h = await db.legacy_salary_history.delete_many(
        {"company_id": body.company_id, "firm_no": body.firm_no})
    runs = await db.compliance_salary_runs.delete_many(
        {"company_id": body.company_id, "legacy_imported": True})
    # Iter 343 — UNDO also removes legacy-published ACTUAL salary runs.
    act_runs = await db.salary_runs.delete_many(
        {"company_id": body.company_id, "run_type": "actual",
         "legacy_imported": True})
    lock = await db.legacy_imported_firms.delete_many({"firm_no": body.firm_no})
    return {"ok": True,
            "employees_deleted": u.deleted_count,
            "employees_unlocked": unlocked.modified_count,
            "salary_rows_deleted": h.deleted_count,
            "published_runs_deleted": runs.deleted_count + act_runs.deleted_count,
            "unlocked": lock.deleted_count > 0}


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
    # Iter 302f (user) — month's MASTER salary (full-month rate) so the
    # engine/screens can calculate accordingly: use the legacy master Basic
    # when the import stored it, otherwise pro-rate earned → full month.
    md = float(r.get("month_days") or 0)
    d = float(r.get("present_days") or 0)
    factor = (md / d) if (d > 0 and md > 0) else 1.0

    def _m(v: float) -> float:
        return round(v * factor, 2) if v else 0.0

    basic_master = float(r.get("master_basic") or 0) or _m(basic)
    hra_master = _m(hra)
    conveyance_master = _m(conv)
    medical_master = _m(med)
    special_master = _m(spl)
    others_master = _m(others)
    gross_master = round(
        basic_master + hra_master + conveyance_master
        + medical_master + special_master + others_master, 2) or _m(gross)
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
        "basic_master": basic_master, "hra_master": hra_master,
        "conveyance_master": conveyance_master, "medical_master": medical_master,
        "special_master": special_master, "others_master": others_master,
        "gross_master": gross_master,
        "monthly_gross": gross_master, "gross_paid": gross, "ot_pay": ot_pay,
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


class BulkLockBody(BaseModel):
    # Iter 308 (user) — lock MANY firms in one go from Legacy Salary Records.
    company_id: Optional[str] = None
    company_ids: Optional[List[str]] = None


def _legacy_row_to_actual(r: dict, u: dict, sr: int) -> dict:
    """Iter 343 (user request) — map a legacy OFFLINE salary history row to
    the ACTUAL Salary Process row shape (salary_runs, run_type="actual")."""
    less_epf = float(r.get("less_epf") or 0)
    less_esi = float(r.get("less_esi") or 0)
    adv = (float(r.get("less_adv") or 0) + float(r.get("less_loan") or 0)
           + float(r.get("less_other") or 0))
    tds = float(r.get("tds") or 0)
    gross = float(r.get("gross") or 0)
    net = float(r.get("net") or 0) or round(
        gross - (less_epf + less_esi + adv + tds), 2)
    return {
        "sr": sr,
        "user_id": r.get("user_id"),
        "employee_code": str(r.get("emp_code") or "") or None,
        "name": r.get("name"),
        "father_name": u.get("father_name"),
        "designation": u.get("designation"),
        "salary_mode": u.get("salary_mode") or "daily",
        "is_onroll": False,
        "basic": float(r.get("rate") or 0),
        "p_days": float(r.get("present_days") or 0),
        "p_hours": float(r.get("work_hours") or 0),
        "oth_allo": float(r.get("others") or 0),
        "basic_salary": float(r.get("basic") or 0),
        "w_basic_salary": float(r.get("w_basic") or 0),
        "total_gross": round(gross, 2),
        "epf": round(less_epf, 2),
        "esi": round(less_esi, 2),
        "adv": round(adv, 2),
        "tds": round(tds, 2),
        "net_pay": round(net, 2),
        "legacy_imported": True,
    }


_ACT_TOTAL_KEYS = ("basic_salary", "w_basic_salary", "total_gross",
                   "epf", "esi", "adv", "tds", "net_pay")


async def _publish_offline_actual_job(job_id: str, company_id: str, admin_uid: str,
                                      lock: bool = False,
                                      only_months: Optional[List[str]] = None):
    """Iter 343 (user request) — publish imported OFFLINE salary months as
    ACTUAL Salary Process runs so the old database's off-roll salary shows
    up in the new portal's Actual Salary options."""
    async def _prog(**kw):
        await db.legacy_import_jobs.update_one(
            {"job_id": job_id}, {"$set": {**kw, "updated_at": _now()}})

    published: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []
    try:
        months = sorted(await db.legacy_salary_history.distinct(
            "month", {"company_id": company_id, "kind": "offline"}))
        if only_months:
            keep = set(only_months)
            months = [m for m in months if m in keep]
        users: Dict[str, dict] = {}
        async for u in db.users.find(
                {"company_id": company_id, "role": "employee"},
                {"_id": 0, "user_id": 1, "father_name": 1, "designation": 1,
                 "salary_mode": 1}):
            users[u["user_id"]] = u
        for mon in months:
            try:
                # NEVER overwrite an existing ACTUAL run for that month —
                # publishing is strictly additive.
                if await db.salary_runs.find_one(
                        {"company_id": company_id, "month": mon,
                         "run_type": "actual"}, {"_id": 1}):
                    skipped.append(mon)
                    continue
                hrows = await db.legacy_salary_history.find(
                    {"company_id": company_id, "kind": "offline", "month": mon},
                    {"_id": 0}).sort("name", 1).to_list(20000)
                rows = [_legacy_row_to_actual(r, users.get(r.get("user_id")) or {}, i + 1)
                        for i, r in enumerate(hrows)]
                totals = {k: round(sum(float(r.get(k) or 0) for r in rows), 2)
                          for k in _ACT_TOTAL_KEYS}
                y, mn = int(mon[:4]), int(mon[5:7])
                run = {
                    "run_id": f"asal_{uuid.uuid4().hex[:12]}",
                    "run_type": "actual",
                    "month": mon, "year": y, "month_number": mn,
                    "month_days": int(max((r.get("month_days") or 0) for r in hrows) or 30),
                    "default_month_days": 30,
                    "attendance_source": "legacy_import",
                    "company_id": company_id,
                    "employee_type": None,
                    "is_onroll_filter": False,
                    "group_id": None,
                    "branch_name": None,
                    "rows": rows,
                    "totals": totals,
                    "employees_count": len(rows),
                    "legacy_imported": True,
                    "finalized": bool(lock),
                    **({"finalized_at": _now(), "finalized_by": admin_uid} if lock else {}),
                    "generated_by": admin_uid,
                    "generated_at": _now(),
                }
                await db.salary_runs.insert_one(run)
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


@router.post("/admin/legacy-salary/publish-actual")
async def legacy_publish_actual(
    body: PublishBody, authorization: Optional[str] = Header(None),
):
    """Iter 343 (user request) — publish imported OFFLINE salary months into
    the ACTUAL Salary Process (past runs)."""
    admin = await _super(authorization)
    months = await db.legacy_salary_history.distinct(
        "month", {"company_id": body.company_id, "kind": "offline"})
    if body.months:
        months = [m for m in months if m in set(body.months)]
    if not months:
        raise HTTPException(
            status_code=404,
            detail="No imported OFFLINE salary months for this firm — run the "
                   "Legacy Import Wizard first (or select at least one month).")
    job_id = f"lpub_{uuid.uuid4().hex[:10]}"
    await db.legacy_import_jobs.insert_one({
        "job_id": job_id, "type": "publish_actual", "status": "running",
        "company_id": body.company_id, "totals": {}, "errors": [],
        "started_by": admin.get("user_id"), "started_at": _now(),
    })
    asyncio.get_event_loop().create_task(
        _publish_offline_actual_job(job_id, body.company_id, admin.get("user_id"),
                                    lock=body.lock, only_months=body.months))
    return {"job_id": job_id, "months": len(months)}


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
    body: BulkLockBody, authorization: Optional[str] = Header(None),
):
    """Iter 302b (user) — after checking, LOCK all published legacy months
    (finalize every legacy_imported compliance run of the firm).
    Iter 308 (user) — accepts ``company_ids`` to lock MANY firms at once."""
    admin = await _super(authorization)
    cids = [c for c in (body.company_ids or []) if c]
    if body.company_id:
        cids.append(body.company_id)
    cids = list(dict.fromkeys(cids))
    if not cids:
        raise HTTPException(status_code=400, detail="Pick at least one firm to lock")
    total = 0
    per_firm: Dict[str, int] = {}
    emp_locked = 0
    for cid in cids:
        r = await db.compliance_salary_runs.update_many(
            {"company_id": cid, "legacy_imported": True,
             "finalized": {"$ne": True}},
            {"$set": {"finalized": True, "finalized_at": _now(),
                      "finalized_by": admin.get("user_id")}})
        per_firm[cid] = r.modified_count
        total += r.modified_count
        # Iter 332 (user request) — locking the legacy salary records ALSO
        # locks the firm's legacy-imported employees: master data can only
        # be updated with Resign/Exit data and NOTHING can be deleted until
        # the firm's legacy import is UNDONE.
        e = await db.users.update_many(
            {"company_id": cid, "role": "employee", "legacy_imported": True},
            {"$set": {"legacy_locked": True,
                      "legacy_locked_at": _now(),
                      "legacy_locked_by": admin.get("user_id")}})
        emp_locked += e.modified_count
    return {"ok": True, "locked": total, "firms": len(cids),
            "employees_locked": emp_locked, "per_firm": per_firm}


# ---------------------------------------------------------------------------
# Iter 347 (user: "So Many Companies Facing Issues Regarding Allowances /
# Salary Not Fetch From OLD DB — Please Set for All Firms") — one-click
# salary STRUCTURE re-sync for EVERY firm that was imported from the legacy
# database. Updates ONLY salary fields (basic, allowances, gross, monthly)
# on existing portal employees, matched code-first exactly like the import.
# ---------------------------------------------------------------------------

_SYNC_SALARY_KEYS = ["basic_salary", "compliance_basic", "pf_basic",
                     "compliance_gross", "salary_monthly",
                     "compliance_salary_allowances"]


async def _sync_structures_job(job_id: str, admin_uid: str):
    async def _prog(**kw):
        await db.legacy_import_jobs.update_one(
            {"job_id": job_id}, {"$set": {**kw, "updated_at": _now()}})

    totals = {"firms_synced": 0, "employees_updated": 0,
              "employees_unmatched": 0, "gross_changed": 0,
              "allowance_labels_enabled": 0, "allowance_heads_created": 0}
    errors: List[str] = []
    try:
        dbn = await _dbname()
        maps = await db.legacy_imported_firms.find({}, {"_id": 0}).to_list(2000)
        await _prog(status="running", firms_total=len(maps), totals=totals)
        for mp in maps:
            firm_no = mp.get("firm_no")
            company_id = mp.get("company_id")
            if firm_no is None or not company_id:
                continue
            if not await db.companies.find_one({"company_id": company_id}, {"_id": 1}):
                continue
            await _prog(current_firm=firm_no, totals=totals)
            try:
                emps = await _legacy_employees(dbn, firm_no)
                # Iter 348 — join via EmpID_FK → EmployeeMaster.FirmNo (the
                # trusted key); FirmID_FK alone missed structures for many
                # firms ("allowances not fetched from old DB").
                srows = await _q(
                    dbn,
                    "SELECT d.EmpID_FK, d.SalHeadType, d.SalHeadName, d.Amount "
                    "FROM EmployeeSalaryStructureDtl d "
                    "JOIN EmployeeMaster em ON em.EmpID = d.EmpID_FK "
                    "WHERE em.FirmNo = %s",
                    (firm_no,))
                totals["structure_rows"] = totals.get("structure_rows", 0) + len(srows)
                if not srows:
                    errors.append(f"firm {firm_no}: NO structure rows in old DB "
                                  "(EmployeeSalaryStructureDtl) — employees keep "
                                  "EmployeeMaster figures")
                struct_by_emp: Dict[int, List[dict]] = {}
                for s in srows:
                    struct_by_emp.setdefault(
                        int(s.get("EmpID_FK") or 0), []).append(s)
                emp_ids_by_code: Dict[int, List[int]] = {}
                for r0 in await _q(
                        dbn,
                        "SELECT EmpID, EmpCode FROM EmployeeMaster "
                        "WHERE FirmNo = %s ORDER BY AcYear DESC, UID DESC",
                        (firm_no,)):
                    try:
                        c0 = int(r0.get("EmpCode") or 0)
                    except (TypeError, ValueError):
                        c0 = 0
                    if c0 > 0:
                        emp_ids_by_code.setdefault(c0, []).append(
                            int(r0.get("EmpID") or 0))

                def _struct_for(e0: dict) -> List[dict]:
                    rows_ = struct_by_emp.get(int(e0.get("EmpID") or 0), [])
                    if rows_:
                        return rows_
                    try:
                        c0 = int(e0.get("EmpCode") or 0)
                    except (TypeError, ValueError):
                        c0 = 0
                    if c0 > 0:
                        for eid in emp_ids_by_code.get(c0, []):
                            rows_ = struct_by_emp.get(eid, [])
                            if rows_:
                                return rows_
                    return []

                # Iter 349 — manual head interlinks (old head → portal label).
                _links = await _head_links_for(company_id)

                # Enable every legacy allowance head on the Firm Master.
                _heads = {
                    _links.get(str(s.get("SalHeadName") or "").strip().lower(),
                               str(s.get("SalHeadName") or "").strip())
                    for rows_ in struct_by_emp.values() for s in rows_
                    if str(s.get("SalHeadType") or "").strip().upper().startswith("ALLOW")
                    and _f(s.get("Amount"))
                }
                _sync = await _sync_firm_allowances(company_id, _heads, admin_uid)
                totals["allowance_labels_enabled"] += len(_sync["enabled"])
                totals["allowance_heads_created"] += len(_sync["created"])

                for e in emps:
                    fields = _emp_doc_fields(e, ["salary"], _struct_for(e),
                                             overrides=None)
                    # Iter 349 — rename interlinked heads to portal labels.
                    if _links and fields.get("compliance_salary_allowances"):
                        for a0 in fields["compliance_salary_allowances"]:
                            lb0 = _links.get(str(a0.get("head") or "").strip().lower())
                            if lb0:
                                a0["head"] = lb0
                    updates = {k: v for k, v in fields.items()
                               if k in _SYNC_SALARY_KEYS}
                    if not updates:
                        continue
                    # Old DB is the source of truth here — clear legacy
                    # per-head fields that would otherwise DOUBLE-count on
                    # top of the fresh allowance list (Iter 348).
                    if "compliance_salary_allowances" in updates:
                        updates.update({"hra_amount": None, "conv_amount": None,
                                        "basic_amount": None,
                                        "salary_structure_compliance": None})
                    try:
                        code = int(e.get("EmpCode") or 0)
                    except (TypeError, ValueError):
                        code = 0
                    existing = None
                    if code > 0:
                        existing = await db.users.find_one(
                            {"company_id": company_id, "role": "employee",
                             "employee_code": str(code)},
                            {"_id": 0, "user_id": 1, "compliance_gross": 1})
                    if existing is None:
                        nm = str(e.get("EmpName") or "").strip()
                        cands = await db.users.find(
                            {"company_id": company_id, "role": "employee",
                             "name": {"$regex": f"^{_rx(nm)}$", "$options": "i"}},
                            {"_id": 0, "user_id": 1, "compliance_gross": 1},
                        ).to_list(2) if nm else []
                        existing = cands[0] if len(cands) == 1 else None
                    if existing is None:
                        totals["employees_unmatched"] += 1
                        continue
                    if round(float(existing.get("compliance_gross") or 0)) != \
                            round(float(updates.get("compliance_gross") or 0)):
                        totals["gross_changed"] += 1
                    updates["salary_structure_synced_at"] = _now()
                    await db.users.update_one(
                        {"user_id": existing["user_id"]}, {"$set": updates})
                    totals["employees_updated"] += 1
            except Exception as fe:  # noqa: BLE001 — keep syncing other firms
                errors.append(f"firm {firm_no}: {str(fe)[:200]}")
            totals["firms_synced"] += 1
            await _prog(totals=totals, errors=errors[-20:])
        await _prog(status="done", totals=totals, errors=errors[-50:])
    except Exception as e:  # noqa: BLE001
        errors.append(str(e)[:300])
        await _prog(status="failed", totals=totals, errors=errors[-50:])


@router.post("/admin/legacy-import/sync-salary-structures")
async def legacy_sync_salary_structures(
        authorization: Optional[str] = Header(None)):
    """Start the ALL-FIRMS salary structure re-sync from the legacy DB.
    Returns a job_id — poll GET /admin/legacy-import/jobs/{job_id}."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    job_id = f"lsync_{uuid.uuid4().hex[:10]}"
    await db.legacy_import_jobs.insert_one({
        "job_id": job_id, "kind": "salary_structure_sync",
        "status": "queued", "totals": {}, "errors": [],
        "started_by": admin.get("user_id"), "started_at": _now()})
    asyncio.get_event_loop().create_task(
        _sync_structures_job(job_id, admin.get("user_id") or ""))
    return {"job_id": job_id}


@router.get("/admin/legacy-import/heads-compare")
async def legacy_heads_compare(authorization: Optional[str] = Header(None)):
    """Iter 348 (user request) — show BOTH databases' salary heads side by
    side, per mapped firm: Old DB allowance + deduction heads (from
    EmployeeSalaryStructureDtl via the EmpID join) vs the portal Firm
    Master's enabled allowances + deductions."""
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    dbn = await _dbname()
    maps = await db.legacy_imported_firms.find({}, {"_id": 0}).to_list(2000)
    # ONE query for all firms: firm-wise distinct head names by type.
    rows = await _q(
        dbn,
        "SELECT em.FirmNo AS firm_no, d.SalHeadType, d.SalHeadName, "
        "COUNT(*) AS n FROM EmployeeSalaryStructureDtl d "
        "JOIN EmployeeMaster em ON em.EmpID = d.EmpID_FK "
        "GROUP BY em.FirmNo, d.SalHeadType, d.SalHeadName")
    old_by_firm: Dict[int, Dict[str, list]] = {}
    for r in rows:
        try:
            fn = int(r.get("firm_no") or 0)
        except (TypeError, ValueError):
            continue
        t = str(r.get("SalHeadType") or "").strip().upper()
        nm = str(r.get("SalHeadName") or "").strip()
        if not nm:
            continue
        bucket = ("allowances" if t.startswith("ALLOW")
                  else "deductions" if t.startswith("DEDUCT")
                  else "basic" if "BASIC" in t or "basic" in nm.lower()
                  else "other")
        d0 = old_by_firm.setdefault(fn, {"allowances": [], "deductions": [],
                                         "basic": [], "other": []})
        d0[bucket].append({"head": nm, "employees": int(r.get("n") or 0)})
    out = []
    from routes.firm_master import ALLOWANCE_LABELS
    all_links = await db.legacy_head_links.find({}, {"_id": 0}).to_list(1000)
    for mp in maps:
        fn = mp.get("firm_no")
        cid = mp.get("company_id")
        co = await db.companies.find_one({"company_id": cid}, {"_id": 0, "name": 1})
        fm = await db.firm_masters.find_one(
            {"company_id": cid}, {"_id": 0, "allowances": 1, "deductions": 1})
        old = old_by_firm.get(int(fn or 0)) or {"allowances": [], "deductions": [],
                                                "basic": [], "other": []}
        for k in ("allowances", "deductions", "basic", "other"):
            old[k] = sorted(old[k], key=lambda x: -x["employees"])
        custom = [str(m0.get("name") or "").strip() async for m0 in db.masters.find(
            {"type": "allowance", "company_id": {"$in": [cid, "__global__", None]}},
            {"_id": 0, "name": 1})]
        links = {}
        for l0 in sorted(all_links,
                         key=lambda x: 0 if x.get("company_id") == "*" else 1):
            if l0.get("company_id") in ("*", cid):
                links[str(l0.get("old_head") or "").strip().lower()] = {
                    "portal_label": l0.get("portal_label"),
                    "scope": l0.get("company_id")}
        out.append({
            "firm_no": fn,
            "company_id": cid,
            "company_name": (co or {}).get("name") or mp.get("company_name"),
            "old_db": old,
            "portal_allowances": sorted(
                [k for k, v in ((fm or {}).get("allowances") or {}).items() if v]),
            "portal_deductions": sorted(
                [k for k, v in ((fm or {}).get("deductions") or {}).items() if v]),
            "label_options": sorted({*ALLOWANCE_LABELS, *[c for c in custom if c]}),
            "links": links,
        })
    out.sort(key=lambda x: str(x["company_name"] or "").lower())
    return {"firms": out}


# ---------------------------------------------------------------------------
# Iter 349 (user: "I will manually interlink") — head links: map an Old DB
# allowance head to a portal allowance label. The ALL-FIRMS sync applies
# these links (renames heads + enables the linked label) on the next run.
# ---------------------------------------------------------------------------

async def _head_links_for(company_id: str) -> Dict[str, str]:
    """old_head(lower) → portal label. Firm-specific overrides global (*)."""
    links: Dict[str, str] = {}
    rows = await db.legacy_head_links.find(
        {"company_id": {"$in": ["*", company_id]}}, {"_id": 0}).to_list(500)
    for r in sorted(rows, key=lambda x: 0 if x.get("company_id") == "*" else 1):
        oh = str(r.get("old_head") or "").strip().lower()
        pl = str(r.get("portal_label") or "").strip()
        if oh and pl:
            links[oh] = pl
    return links


@router.get("/admin/legacy-import/head-links")
async def legacy_head_links_list(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    rows = await db.legacy_head_links.find({}, {"_id": 0}).to_list(1000)
    return {"links": rows}


@router.post("/admin/legacy-import/head-links")
async def legacy_head_links_save(payload: Dict[str, Any] = Body(...),
                                 authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin"])
    old_head = str(payload.get("old_head") or "").strip()
    portal_label = str(payload.get("portal_label") or "").strip()
    cid = "*" if payload.get("apply_all_firms") else (payload.get("company_id") or "*")
    if not old_head:
        raise HTTPException(status_code=400, detail="old_head is required")
    key = {"company_id": cid, "old_head_lower": old_head.lower()}
    if payload.get("remove") or not portal_label:
        await db.legacy_head_links.delete_one(key)
        return {"ok": True, "removed": True}
    await db.legacy_head_links.replace_one(key, {
        **key, "old_head": old_head, "portal_label": portal_label,
        "by": admin.get("user_id"), "at": _now()}, upsert=True)
    return {"ok": True}
