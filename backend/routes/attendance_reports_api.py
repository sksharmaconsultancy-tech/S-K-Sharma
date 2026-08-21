"""Iter 397 — ATTENDANCE REPORT EXPORTS module (extracted from server.py).

Refactor only: the shared _monthly_report_impl/_daily_report_impl builders
plus monthly hours / OT / in-out and daily attendance (xlsx + pdf)
endpoints MOVED verbatim from server.py."""
import re
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from server import (  # noqa: E402
    _compute_monthly_grid_data,
    db,
    get_user_from_token,
    sub_admin_can_touch_company,
)

router = APIRouter(prefix="/api")
api = router


async def _monthly_report_impl(
    company_id: str,
    month: str,
    admin: dict,
    variant: str,   # "hours" | "inout"
    group_id: Optional[str] = None,
    hide_zero: bool = False,
):
    """Shared plumbing for both monthly attendance reports.

    Loads employees + all raw punches for the requested month, groups by
    user_id + date and hands off to the correct XLSX builder.
    """
    from fastapi.responses import Response
    # Super Admin, Sub-Admin (with scope) or Company Admin of the firm.
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only export your own firm")

    company = await db.companies.find_one(
        {"company_id": company_id},
        {"_id": 0, "name": 1, "attendance_policy": 1})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    # Iter 200 (user request) — Report Settings live on the firm's attendance
    # policy. A disabled report type cannot be exported for that firm.
    _rs_key = "inout" if variant.startswith("inout") else "hours"
    _rs = ((company.get("attendance_policy") or {}).get("report_settings") or {})
    _rs_en = _rs.get("enabled") or {}
    if _rs_key in _rs_en and not _rs_en.get(_rs_key):
        _lbl = "In/Out" if _rs_key == "inout" else "Hours Only"
        raise HTTPException(
            status_code=403,
            detail=f"The {_lbl} report is disabled for this firm "
                   "(Attendance Policy → Report Settings).")
    try:
        y, m = int(month[:4]), int(month[5:7])
        if m < 1 or m > 12:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")

    # Iter 660 (user request) — "Hide Zero Attendance": drop employees
    # with no hours / present days / OT / punches from the export.
    async def _grid(**kw):
        g = await _compute_monthly_grid_data(**kw)  # noqa: original compute
        if hide_zero:
            kept = []
            for e in (g.get("employees") or []):
                t = e.get("totals") or {}
                if (t.get("hours") or 0) or (t.get("present_days") or 0) \
                        or (t.get("ot_hours") or 0) or (t.get("total_punches") or 0):
                    kept.append(e)
            g["employees"] = kept
        return g

    # All four variants (XLSX + PDF twins) are grid-based now, so the
    # employee/punch loading happens inside ``_compute_monthly_grid_data``
    # with the full Firm Master policy pipeline applied.
    if variant == "inout":
        # Iter 77x — Grid View XLSX (multi-row per employee).
        # Reuses the exact grid-compute pipeline the Grid View screen uses
        # (via ``_compute_monthly_grid_data``) so the Excel mirrors what
        # admins see on-screen: bounce-merge, dedup, OT cap, cross-day OT
        # pairing, weekly-off rules — all applied upstream.
        from utils.monthly_attendance import build_grid_view_xlsx
        grid = await _grid(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        xlsx_bytes = build_grid_view_xlsx(grid)
        variant_slug = "GridView"
    elif variant == "inout_pdf":
        # Policy-aligned (user directive): PDF twins now consume the SAME
        # grid pipeline as the XLSX/Grid View so all attendance reports
        # follow the Firm Master attendance policy.
        from utils.monthly_attendance_pdf import build_monthly_inout_pdf
        grid = await _grid(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        from routes.report_formats import get_report_format
        pdf_bytes = build_monthly_inout_pdf(
            grid, fmt=await get_report_format("attendance_inout"))
        company_slug = (company.get("name") or "company").replace(" ", "_")
        filename = f"MonthlyAttendance_InOut_{company_slug}_{month}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif variant == "ot":
        # Iter 203 (user request) — OT Duty HRS report: day-wise OT ONLY.
        from utils.monthly_attendance import build_ot_only_grid_xlsx
        grid = await _grid(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        xlsx_bytes = build_ot_only_grid_xlsx(grid)
        variant_slug = "OTDutyHRS"
    elif variant == "ot_pdf":
        from utils.monthly_attendance_pdf import build_monthly_ot_pdf
        grid = await _grid(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        from routes.report_formats import get_report_format
        pdf_bytes = build_monthly_ot_pdf(
            grid, fmt=await get_report_format("attendance_ot"))
        company_slug = (company.get("name") or "company").replace(" ", "_")
        filename = f"MonthlyAttendance_OTDutyHRS_{company_slug}_{month}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    elif variant == "hours_pdf":
        from utils.monthly_attendance_pdf import build_monthly_hours_pdf
        grid = await _grid(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        from routes.report_formats import get_report_format
        pdf_bytes = build_monthly_hours_pdf(
            grid, fmt=await get_report_format("attendance_hours"))
        company_slug = (company.get("name") or "company").replace(" ", "_")
        filename = f"MonthlyAttendance_Hours_{company_slug}_{month}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        # Iter 77z — Hours Only sheet routed through grid compute so each
        # day cell combines Duty + OT (both included in the totals).
        from utils.monthly_attendance import build_hours_only_grid_xlsx
        grid = await _grid(
            company_id=company_id,
            month=month,
            group_id=group_id,
            from_date=None,
            to_date=None,
        )
        xlsx_bytes = build_hours_only_grid_xlsx(grid)
        variant_slug = "Hours"
    company_slug = (company.get("name") or "company").replace(" ", "_")
    filename = f"MonthlyAttendance_{variant_slug}_{company_slug}_{month}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/admin/attendance/monthly-hours/{company_id}/{month}.xlsx")
async def monthly_attendance_hours(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    hide_zero: int = 0,
    authorization: Optional[str] = Header(None),
):
    """Monthly working-hours matrix (mirrors the user's reference sheet)."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "hours", group_id, hide_zero=bool(hide_zero))


@api.get("/admin/attendance/monthly-ot/{company_id}/{month}.xlsx")
async def monthly_attendance_ot(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    hide_zero: int = 0,
    authorization: Optional[str] = Header(None),
):
    """Iter 203 — OT Duty HRS report (day-wise OT only, policy-computed)."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "ot", group_id, hide_zero=bool(hide_zero))


@api.get("/admin/attendance/monthly-ot/{company_id}/{month}.pdf")
async def monthly_attendance_ot_pdf(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    hide_zero: int = 0,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "ot_pdf", group_id, hide_zero=bool(hide_zero))


@api.get("/admin/attendance/monthly-inout/{company_id}/{month}.xlsx")
async def monthly_attendance_inout(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    hide_zero: int = 0,
    authorization: Optional[str] = Header(None),
):
    """Monthly IN / OUT + Working Hours matrix — same layout, richer cells."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "inout", group_id, hide_zero=bool(hide_zero))


@api.get("/admin/attendance/monthly-inout/{company_id}/{month}.pdf")
async def monthly_attendance_inout_pdf(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    hide_zero: int = 0,
    authorization: Optional[str] = Header(None),
):
    """Iter 77 - Landscape A4 PDF twin of the IN / OUT XLSX. Same numbers,
    print-ready."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "inout_pdf", group_id, hide_zero=bool(hide_zero))


@api.get("/admin/attendance/monthly-hours/{company_id}/{month}.pdf")
async def monthly_attendance_hours_pdf(
    company_id: str,
    month: str,
    group_id: Optional[str] = None,
    hide_zero: int = 0,
    authorization: Optional[str] = Header(None),
):
    """Iter 77 - Landscape A4 PDF twin of the Working Hours XLSX."""
    admin = await get_user_from_token(authorization)
    return await _monthly_report_impl(company_id, month, admin, "hours_pdf", group_id, hide_zero=bool(hide_zero))


# ---------------------------------------------------------------------------
# Iter 111 — DAILY-BASIS attendance report (single date, one row/employee)
# ---------------------------------------------------------------------------
async def _daily_report_impl(company_id: str, date_s: str, admin: dict, fmt: str,
                             group_id: Optional[str] = None):
    from fastapi.responses import Response
    if admin.get("role") not in ("super_admin", "sub_admin", "company_admin"):
        raise HTTPException(status_code=403, detail="Not authorised")
    if admin.get("role") == "sub_admin":
        if not sub_admin_can_touch_company(admin, company_id):
            raise HTTPException(status_code=403, detail="Firm not in your scope")
    if admin.get("role") == "company_admin" and admin.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="You can only export your own firm")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s or ""):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    grid = await _compute_monthly_grid_data(
        company_id=company_id,
        month=date_s[:7],
        group_id=group_id,
        from_date=date_s,
        to_date=date_s,
    )
    company_slug = (((grid.get("company") or {}).get("name")) or "company").replace(" ", "_")
    if fmt == "pdf":
        from utils.daily_attendance import build_daily_pdf
        from routes.report_formats import get_report_format
        content = build_daily_pdf(grid, date_s,
                                  fmt=await get_report_format("daily_present"))
        media = "application/pdf"
    else:
        from utils.daily_attendance import build_daily_xlsx
        content = build_daily_xlsx(grid, date_s)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    filename = f"DailyAttendance_{company_slug}_{date_s}.{fmt}"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.get("/admin/attendance/daily/{company_id}/{date_s}.xlsx")
async def daily_attendance_xlsx(
    company_id: str,
    date_s: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Daily-basis attendance report (Excel) — one row per employee."""
    admin = await get_user_from_token(authorization)
    return await _daily_report_impl(company_id, date_s, admin, "xlsx", group_id)


@api.get("/admin/attendance/daily/{company_id}/{date_s}.pdf")
async def daily_attendance_pdf(
    company_id: str,
    date_s: str,
    group_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """Daily-basis attendance report (PDF) — one row per employee."""
    admin = await get_user_from_token(authorization)
    return await _daily_report_impl(company_id, date_s, admin, "pdf", group_id)
