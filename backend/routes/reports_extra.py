"""Iter 86 - Route module: extra reports (users-log activity feed).

First endpoint extracted from the monolithic `server.py` as a proof of
concept for the modularization effort.

The endpoint pattern used here is the template for all future extracts:

  1) `router = APIRouter(prefix="/api")` - preserves the `/api` prefix
     so URLs are unchanged.
  2) Shared state (`db`, `get_user_from_token`, `require_role`) is
     imported lazily from `server` so this module doesn't need to
     duplicate the FastAPI app / motor client setup.
  3) `server.py` includes this router at the very bottom of its file,
     AFTER all shared helpers are defined.  That ordering breaks the
     apparent circular import because at the moment `server.py` runs
     ``from routes.reports_extra import router``, all names this
     sub-module needs are already bound on the `server` module object.

Endpoints:
  * GET /api/admin/users-log - Unified activity feed across:
      - company_audit_log
      - attendance_audit_log
      - salary_runs (generated_at + finalized_at)
      - compliance_salary_runs (generated_at + finalized_at)
    Filters: from_date, to_date, company_id, user_id.
"""
from typing import Optional, List
from fastapi import APIRouter, Header, Query

# Shared helpers live on the `server` module.  Importing them here at
# module-load time is safe because `server.py` only pulls this
# sub-module in at the very bottom of its file - long after `db`,
# `get_user_from_token`, and `require_role` are bound.
from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api")


# Iter 85 - Users Log Report - unified activity feed.
#
# Aggregates events from four sources into a single date-filtered
# stream:
#   * company_audit_log   - admin actions (approvals, PIN changes, ...)
#   * attendance_audit_log - punch decisions (approve/reject/edit)
#   * salary_runs          - generated_at + finalized_at
#   * compliance_salary_runs - generated_at + finalized_at
#
# Filters:
#   from_date / to_date  (YYYY-MM-DD, inclusive)
#   company_id           (optional; scopes to a single firm)
#   user_id              (optional; scopes to a single actor)
@router.get("/admin/users-log")
async def users_log_report(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "sub_admin", "company_admin"])
    scope_cid = admin.get("company_id") if admin["role"] == "company_admin" else company_id

    date_range: dict = {}
    if from_date:
        date_range["$gte"] = f"{from_date}T00:00:00"
    if to_date:
        date_range["$lte"] = f"{to_date}T23:59:59"

    def _apply(q: dict, ts_field: str) -> dict:
        if date_range:
            q[ts_field] = date_range
        if scope_cid:
            q["company_id"] = scope_cid
        return q

    events: List[dict] = []

    # 0) activity_log — the FULL automatic action trail (Iter 247): every
    #    create/update/delete + report download by any logged-in user.
    async for e in db.activity_log.find(_apply({}, "at"), {"_id": 0}).sort("at", -1).limit(3000):
        st = e.get("status")
        extra = f" [FAILED {st}]" if isinstance(st, int) and st >= 400 else ""
        events.append({
            "at": e.get("at"),
            "actor_id": e.get("actor_id"),
            "action": e.get("action") or f"{e.get('method')} {e.get('path')}",
            "company_id": e.get("company_id"),
            "details": ((e.get("details") or "") + extra).strip(),
            "source": "activity_log",
        })

    # 1) company_audit_log - generic admin actions
    async for e in db.company_audit_log.find(_apply({}, "at"), {"_id": 0}).sort("at", -1).limit(1000):
        events.append({
            "at": e.get("at"),
            "actor_id": e.get("actor_id") or e.get("user_id"),
            "action": e.get("action") or e.get("kind") or "action",
            "company_id": e.get("company_id"),
            "details": e.get("details") or e.get("note") or "",
            "source": "company_audit_log",
        })

    # 2) attendance_audit_log - punch approve/reject/edit
    async for e in db.attendance_audit_log.find(_apply({}, "at"), {"_id": 0}).sort("at", -1).limit(1000):
        events.append({
            "at": e.get("at"),
            "actor_id": e.get("admin_id") or e.get("actor_id"),
            "action": f"punch.{e.get('action') or 'decision'}",
            "company_id": e.get("company_id"),
            "details": e.get("reason") or e.get("note") or "",
            "source": "attendance_audit_log",
        })

    # 3) salary_runs (Actual Salary)
    async for e in db.salary_runs.find(
        _apply({}, "generated_at"),
        {"_id": 0, "generated_by": 1, "generated_at": 1, "month": 1, "company_id": 1, "run_type": 1, "finalized_by": 1, "finalized_at": 1},
    ).sort("generated_at", -1).limit(500):
        events.append({
            "at": e.get("generated_at"),
            "actor_id": e.get("generated_by"),
            "action": "salary.generated",
            "company_id": e.get("company_id"),
            "details": f"month={e.get('month')} type={e.get('run_type', 'actual')}",
            "source": "salary_runs",
        })
        if e.get("finalized_at"):
            events.append({
                "at": e.get("finalized_at"),
                "actor_id": e.get("finalized_by"),
                "action": "salary.finalized",
                "company_id": e.get("company_id"),
                "details": f"month={e.get('month')}",
                "source": "salary_runs",
            })

    # 4) compliance_salary_runs
    async for e in db.compliance_salary_runs.find(
        _apply({}, "generated_at"),
        {"_id": 0, "generated_by": 1, "generated_at": 1, "month": 1, "company_id": 1},
    ).sort("generated_at", -1).limit(500):
        events.append({
            "at": e.get("generated_at"),
            "actor_id": e.get("generated_by"),
            "action": "compliance.generated",
            "company_id": e.get("company_id"),
            "details": f"month={e.get('month')}",
            "source": "compliance_salary_runs",
        })

    # Filter by user_id if requested (applied after aggregation)
    if user_id:
        events = [ev for ev in events if ev.get("actor_id") == user_id]

    # Enrich with actor + company names for a nicer display
    actor_ids = {ev.get("actor_id") for ev in events if ev.get("actor_id")}
    cids = {ev.get("company_id") for ev in events if ev.get("company_id")}
    actor_names: dict = {}
    if actor_ids:
        async for u in db.users.find(
            {"user_id": {"$in": list(actor_ids)}},
            {"_id": 0, "user_id": 1, "name": 1, "role": 1, "phone": 1},
        ):
            actor_names[u["user_id"]] = {
                "name": u.get("name") or "-",
                "role": u.get("role") or "",
                "phone": u.get("phone") or "",
            }
    company_names: dict = {}
    if cids:
        async for c in db.companies.find(
            {"company_id": {"$in": list(cids)}},
            {"_id": 0, "company_id": 1, "name": 1},
        ):
            company_names[c["company_id"]] = c.get("name") or "-"
    for ev in events:
        actor = actor_names.get(ev.get("actor_id") or "") or {}
        ev["actor_name"] = actor.get("name") or "-"
        ev["actor_role"] = actor.get("role") or ""
        ev["company_name"] = company_names.get(ev.get("company_id") or "") or "-"

    # Sort DESC by timestamp
    events.sort(key=lambda ev: (ev.get("at") or ""), reverse=True)
    events = events[:2000]
    return {"events": events, "count": len(events)}


# Iter 247 — Excel export of the SAME filtered log (full report with
# date and time, one row per action).
@router.get("/admin/users-log.xlsx")
async def users_log_report_xlsx(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    data = await users_log_report(from_date, to_date, company_id, user_id, authorization)
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from fastapi.responses import Response

    wb = Workbook()
    ws = wb.active
    ws.title = "Users Log"
    ws.append(["Date", "Time", "User", "Role", "Firm", "Action", "Details", "Source"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for ev in data["events"]:
        at = ev.get("at") or ""
        d = f"{at[8:10]}-{at[5:7]}-{at[0:4]}" if len(at) >= 10 else ""
        t = at[11:19] if len(at) >= 19 else ""
        ws.append([
            d, t,
            ev.get("actor_name") or "-",
            ev.get("actor_role") or "",
            ev.get("company_name") or "-",
            ev.get("action") or "",
            (ev.get("details") or "")[:500],
            ev.get("source") or "",
        ])
    for col, w in zip("ABCDEFGH", (12, 10, 22, 15, 26, 42, 60, 20)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"users-log-{from_date or 'all'}-to-{to_date or 'all'}.xlsx"
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
