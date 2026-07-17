"""Iter 163 — Global PDF Report Formats (Utilities → PDF Report Formats).

SUPER-ADMIN-ONLY utility to set the saved format of regular PDF reports
one time; every future download applies it automatically.

Supported reports:
  * pf_ecr            — columns / order / headings / widths + orientation,
                        font size and title.
  * esic_contribution — same as above.
  * pf_challan        — fixed statutory grid; orientation / font size /
                        title are editable.
  * esic_challan      — fixed statutory layout; font size / title editable.

(The Compliance Salary Register keeps its dedicated editor at
/admin/compliance-register-layout.)

Formats live in db.app_settings under key "report_format:{report_id}".
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException

from server import db, get_user_from_token, now_iso, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin/report-formats", tags=["report-formats"])


# (key, default heading, default width, numeric?)
ECR_COLUMNS: List[Any] = [
    ("sl", "Sl.", 10, False),
    ("uan", "UAN", 28, False),
    ("name", "Member Name", 62, False),
    ("gross", "Gross Wages", 22, True),
    ("epf_wages", "EPF Wages", 22, True),
    ("eps_wages", "EPS Wages", 22, True),
    ("edli_wages", "EDLI Wages", 22, True),
    ("epf_ee", "EE Share", 22, True),
    ("eps_er", "EPS Contri.", 22, True),
    ("diff_er", "ER Share (Diff)", 22, True),
    ("refund", "Refunds", 22, True),
    ("ncp", "NCP Days", 16, True),
]

ESIC_COLUMNS: List[Any] = [
    ("sl", "SNo.", 11, False),
    ("disable", "Is Disable", 16, False),
    ("ip_no", "IP Number", 26, False),
    ("name", "IP Name", 62, False),
    ("days", "No. Of Days", 18, True),
    ("wages", "Total Wages", 24, True),
    ("ee", "IP Contribution", 24, True),
    ("reason", "Reason", 22, False),
]

REPORTS: Dict[str, Dict[str, Any]] = {
    "pf_ecr": {
        "label": "PF ECR — Return Statement (PDF)",
        "group": "PF Reports",
        "columns": ECR_COLUMNS,
        "defaults": {"orientation": "landscape", "font_size": 7.5,
                     "title": "EMPLOYEE'S PROVIDENT FUND ORGANISATION"},
    },
    "pf_challan": {
        "label": "PF Challan (PDF)",
        "group": "PF Reports",
        "columns": None,  # fixed statutory grid
        "defaults": {"orientation": "portrait", "font_size": 8,
                     "title": "EMPLOYEES' PROVIDENT FUND ORGANISATION"},
    },
    "esic_contribution": {
        "label": "ESIC Contribution Sheet (PDF)",
        "group": "ESIC Reports",
        "columns": ESIC_COLUMNS,
        "defaults": {"orientation": "portrait", "font_size": 7.5,
                     "title": "Employees' State Insurance Corporation"},
    },
    "esic_challan": {
        "label": "ESIC Challan (PDF)",
        "group": "ESIC Reports",
        "columns": None,  # fixed statutory layout
        "defaults": {"orientation": "portrait", "font_size": 9,
                     "title": "EMPLOYEE STATE INSURANCE CORPORATION"},
    },
}

_ORIENTATIONS = ("portrait", "landscape")


def _key(report_id: str) -> Dict[str, str]:
    return {"key": f"report_format:{report_id}"}


async def get_report_format(report_id: str) -> Dict[str, Any]:
    """Saved format for a report ({} when nothing saved). Used by the
    PDF generators — never raises."""
    try:
        doc = await db.app_settings.find_one(_key(report_id), {"_id": 0}) or {}
        return doc.get("format") or {}
    except Exception:
        return {}


def resolve_columns(report_id: str, fmt: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ordered [{key, heading, width, numeric}] honouring the saved
    format (fallback = full default catalog)."""
    catalog = REPORTS[report_id]["columns"] or []
    defaults = {k: (h, w, n) for k, h, w, n in catalog}
    spec = [c for c in (fmt.get("columns") or [])
            if isinstance(c, dict) and c.get("key") in defaults]
    if not spec:
        spec = [{"key": k} for k, _h, _w, _n in catalog]
    out = []
    for c in spec:
        h, w, n = defaults[c["key"]]
        try:
            width = float(c.get("width") or 0)
        except Exception:
            width = 0
        out.append({"key": c["key"],
                    "heading": str(c.get("heading") or "").strip() or h,
                    "width": width if width > 0 else float(w),
                    "numeric": n})
    return out


def _report_or_404(report_id: str) -> Dict[str, Any]:
    r = REPORTS.get(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown report")
    return r


@router.get("")
async def list_report_formats(authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    items = []
    for rid, r in REPORTS.items():
        doc = await db.app_settings.find_one(_key(rid), {"_id": 0}) or {}
        items.append({
            "report_id": rid, "label": r["label"], "group": r["group"],
            "has_columns": bool(r["columns"]),
            "saved": bool(doc.get("format")),
            "updated_at": doc.get("updated_at"),
            "updated_by_name": doc.get("updated_by_name"),
        })
    return {"reports": items}


@router.get("/{report_id}")
async def get_one(report_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    r = _report_or_404(report_id)
    doc = await db.app_settings.find_one(_key(report_id), {"_id": 0}) or {}
    return {
        "report_id": report_id,
        "label": r["label"],
        "defaults": r["defaults"],
        "catalog": ([{"key": k, "heading": h, "width": w, "numeric": n}
                     for k, h, w, n in r["columns"]] if r["columns"] else None),
        "format": doc.get("format") or None,
        "updated_at": doc.get("updated_at"),
        "updated_by_name": doc.get("updated_by_name"),
    }


@router.put("/{report_id}")
async def save_one(report_id: str, payload: Dict[str, Any] = Body(...),
                   authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])  # user directive: super admin ONLY
    r = _report_or_404(report_id)

    fmt: Dict[str, Any] = {}
    # ---- columns (only for tabular reports)
    if r["columns"]:
        valid = {k for k, _h, _w, _n in r["columns"]}
        cols = []
        for c in payload.get("columns") or []:
            if not isinstance(c, dict) or c.get("key") not in valid:
                continue
            item: Dict[str, Any] = {"key": c["key"]}
            if str(c.get("heading") or "").strip():
                item["heading"] = str(c["heading"]).strip()[:40]
            try:
                w = float(c.get("width") or 0)
                if w > 0:
                    item["width"] = max(4.0, min(100.0, w))
            except Exception:
                pass
            cols.append(item)
        if not cols:
            raise HTTPException(status_code=400,
                                detail="Select at least one column")
        fmt["columns"] = cols

    # ---- general options
    orient = str(payload.get("orientation") or "").strip().lower()
    if orient:
        if orient not in _ORIENTATIONS:
            raise HTTPException(status_code=400,
                                detail="orientation must be portrait/landscape")
        fmt["orientation"] = orient
    try:
        fs = float(payload.get("font_size") or 0)
        if fs > 0:
            fmt["font_size"] = max(5.0, min(16.0, fs))
    except Exception:
        pass
    title = str(payload.get("title") or "").strip()
    if title:
        fmt["title"] = title[:120]

    if not fmt:
        raise HTTPException(status_code=400, detail="Nothing to save")

    await db.app_settings.update_one(
        _key(report_id),
        {"$set": {"format": fmt, "updated_at": now_iso(),
                  "updated_by_name": admin.get("name") or admin.get("email") or ""},
         "$setOnInsert": _key(report_id)}, upsert=True)
    return {"ok": True, "format": fmt}


@router.delete("/{report_id}")
async def reset_one(report_id: str, authorization: Optional[str] = Header(None)):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin"])
    _report_or_404(report_id)
    await db.app_settings.delete_one(_key(report_id))
    return {"ok": True}
