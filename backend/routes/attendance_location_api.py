"""Iter 397 — ATTENDANCE LOCATION / FLAGS module (extracted from server.py).

Refactor only: flagged punches, location audit (+xlsx), clear-flag and
punch selfie endpoints MOVED verbatim from server.py."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    now_iso,
    require_role,
)

router = APIRouter(prefix="/api")
api = router


@api.get("/admin/attendance/flagged")
async def list_flagged_punches(
    company_id: Optional[str] = None,
    limit: int = 100,
    authorization: Optional[str] = Header(None),
):
    """Return recent punches flagged by face-match. company_admin sees
    their company only; super_admin can filter with ?company_id=."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    q: dict = {"identity_flagged": True}
    if user["role"] == "company_admin":
        q["company_id"] = user.get("company_id")
    elif user["role"] == "super_admin" and company_id and company_id != "all":
        q["company_id"] = company_id
    limit = max(1, min(500, int(limit or 100)))
    recs = await db.attendance.find(
        q, {"_id": 0, "selfie_base64": 0, "device_info": 0}
    ).sort("at", -1).to_list(limit)
    # Attach user + company name for display
    uids = list({r.get("user_id") for r in recs if r.get("user_id")})
    users = await db.users.find(
        {"user_id": {"$in": uids}},
        {"_id": 0, "user_id": 1, "name": 1, "employee_code": 1, "company_id": 1},
    ).to_list(1000) if uids else []
    u_by_id = {u["user_id"]: u for u in users}
    cids = list({u.get("company_id") for u in users if u.get("company_id")})
    companies = await db.companies.find(
        {"company_id": {"$in": cids}}, {"_id": 0, "company_id": 1, "name": 1},
    ).to_list(500) if cids else []
    c_by_id = {c["company_id"]: c["name"] for c in companies}
    for r in recs:
        u = u_by_id.get(r.get("user_id"), {})
        r["user_name"] = u.get("name")
        r["employee_code"] = u.get("employee_code")
        r["company_name"] = c_by_id.get(u.get("company_id"))
    return {"flagged": recs, "count": len(recs)}


# ---------------------------------------------------------------------------
# Iter 64 — Location Audit
# ---------------------------------------------------------------------------
def _compute_location_status(rec: dict) -> str:
    """Back-fill helper: derive location_status for older records that were
    saved before the field existed."""
    if rec.get("location_status"):
        return rec["location_status"]
    if rec.get("gps_verified") is False:
        return "no-gps"
    if rec.get("outside_geofence") is True:
        return "outside"
    return "inside"


@api.get("/admin/attendance/location-audit")
async def list_location_audit(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(
        None, description="Cross-firm filter. Ignored for company_admin.",
    ),
    user_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD (inclusive)"),
    location_status: Optional[str] = Query(
        None,
        description="inside | outside | no-gps. Omit for all.",
    ),
    limit: int = Query(200, ge=1, le=1000),
    authorization: Optional[str] = Header(None),
):
    """Location Audit: filterable list of punches with per-row status.

    Never returns selfie_base64 in the list view to keep payloads light —
    the client fetches the selfie separately from ``/admin/attendance/{id}/selfie``
    if it wants to display the thumbnail.
    """
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])

    q: dict = {}
    if admin["role"] == "company_admin":
        q["company_id"] = admin.get("company_id")
    elif company_ids:
        clean = [c for c in company_ids if c]
        if clean:
            q["company_id"] = {"$in": clean}
    elif company_id:
        q["company_id"] = company_id

    if user_id:
        q["user_id"] = user_id
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["date"] = rng
    if location_status in ("inside", "outside", "no-gps"):
        # Newer records have the field set; older ones require the derived
        # equivalent so we still surface them in the audit view.
        if location_status == "inside":
            q["$or"] = [
                {"location_status": "inside"},
                {
                    "location_status": {"$exists": False},
                    "gps_verified": {"$ne": False},
                    "outside_geofence": {"$ne": True},
                },
            ]
        elif location_status == "outside":
            q["$or"] = [
                {"location_status": "outside"},
                {
                    "location_status": {"$exists": False},
                    "outside_geofence": True,
                },
            ]
        elif location_status == "no-gps":
            q["$or"] = [
                {"location_status": "no-gps"},
                {
                    "location_status": {"$exists": False},
                    "gps_verified": False,
                },
            ]

    recs = (
        await db.attendance.find(
            q, {"_id": 0, "selfie_base64": 0, "device_info": 0},
        )
        .sort("at", -1)
        .to_list(limit)
    )

    for r in recs:
        r["location_status"] = _compute_location_status(r)

    # Enrich with user + company names.
    uids = list({r.get("user_id") for r in recs if r.get("user_id")})
    users = (
        await db.users.find(
            {"user_id": {"$in": uids}},
            {
                "_id": 0, "user_id": 1, "name": 1,
                "employee_code": 1, "company_id": 1,
            },
        ).to_list(len(uids))
        if uids
        else []
    )
    u_by_id = {u["user_id"]: u for u in users}
    cids = list({u.get("company_id") for u in users if u.get("company_id")})
    companies = (
        await db.companies.find(
            {"company_id": {"$in": cids}},
            {"_id": 0, "company_id": 1, "name": 1},
        ).to_list(len(cids))
        if cids
        else []
    )
    c_by_id = {c["company_id"]: c["name"] for c in companies}
    for r in recs:
        u = u_by_id.get(r.get("user_id"), {})
        r["user_name"] = u.get("name")
        r["employee_code"] = u.get("employee_code")
        r["company_name"] = c_by_id.get(u.get("company_id"))

    # Aggregate summary counts for the header.
    summary = {"inside": 0, "outside": 0, "no-gps": 0}
    for r in recs:
        s = r.get("location_status") or "no-gps"
        if s in summary:
            summary[s] += 1

    return {"records": recs, "count": len(recs), "summary": summary}


@api.get("/admin/attendance/location-audit.xlsx")
async def download_location_audit_xlsx(
    company_id: Optional[str] = Query(None),
    company_ids: Optional[List[str]] = Query(None),
    user_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    location_status: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Native Excel export of the Location Audit view."""
    from utils.report_xlsx import build_rows_xlsx
    from fastapi.responses import Response
    data = await list_location_audit(
        company_id=company_id,
        company_ids=company_ids,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        location_status=location_status,
        limit=1000,
        authorization=authorization,
    )
    # Project the columns for the sheet.
    rows: List[Dict[str, Any]] = []
    for r in data["records"]:
        rows.append({
            "date": r.get("date"),
            "time": (r.get("at") or "").split("T")[-1].split(".")[0] if r.get("at") else "",
            "company_name": r.get("company_name") or "",
            "employee_code": r.get("employee_code") or "",
            "employee_name": r.get("user_name") or "",
            "kind": ("IN" if r.get("kind") == "in" else "OUT"),
            "location_status": r.get("location_status"),
            "distance_m": r.get("distance_m"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
            "biometric_method": r.get("biometric_method"),
            "source": r.get("source"),
            "status": r.get("status"),
            "outside_note": r.get("outside_note") or "",
        })
    xlsx = build_rows_xlsx(
        columns=[
            "date", "time", "company_name", "employee_code", "employee_name",
            "kind", "location_status", "distance_m", "latitude", "longitude",
            "biometric_method", "source", "status", "outside_note",
        ],
        rows=rows,
        sheet_name="Location Audit",
        title="Attendance — Location Audit",
        subtitle=(
            f"Inside {data['summary']['inside']} · "
            f"Outside {data['summary']['outside']} · "
            f"No-GPS {data['summary']['no-gps']} · "
            f"Total {data['count']}"
        ),
    )
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="LocationAudit.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@api.patch("/admin/attendance/{record_id}/clear-flag")
async def clear_flag(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Admin clears the identity_flagged bit after manual review."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    rec = await db.attendance.find_one({"record_id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if user["role"] == "company_admin" and rec.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your company")
    await db.attendance.update_one(
        {"record_id": record_id},
        {"$set": {
            "identity_flagged": False,
            "identity_reviewed_by": user["user_id"],
            "identity_reviewed_at": now_iso(),
        }},
    )
    return {"ok": True}


@api.get("/admin/attendance/{record_id}/selfie")
async def get_punch_selfie(
    record_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return the base64 selfie captured on a specific punch. Admin-only."""
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin", "sub_admin"])
    rec = await db.attendance.find_one(
        {"record_id": record_id},
        {"_id": 0, "selfie_base64": 1, "company_id": 1},
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Punch not found")
    if user["role"] == "company_admin" and rec.get("company_id") != user.get("company_id"):
        raise HTTPException(status_code=403, detail="Not your company")
    _b64 = rec.get("selfie_base64")
    # Iter 306 — legacy rows stored with a data-URL prefix render blank.
    if _b64 and _b64.startswith("data:"):
        _b64 = _b64.split("base64,", 1)[-1]
    return {"selfie_base64": _b64}


