"""Iter 497 — Universal report PDF export endpoint.

The Universal Report Table (frontend) posts its CURRENT on-screen layout
(visible columns, user-resized widths, display values) and receives a
landscape PDF that matches the screen exactly — headers repeated on every
page, no truncated columns, no overlapping text.
"""
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

sys.path.append("/app/backend")
from server import get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/report-export", tags=["report-export"])

_MAX_ROWS = 20000
_MAX_COLS = 80


class PdfBody(BaseModel):
    title: str = "Report"
    subtitle: str = ""
    columns: List[Dict[str, Any]] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    footer: Optional[List[str]] = None


@router.post("/pdf")
async def report_export_pdf(body: PdfBody,
                            authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin", "company_admin"])
    if not body.columns:
        raise HTTPException(status_code=400, detail="No columns to export")
    if len(body.columns) > _MAX_COLS:
        raise HTTPException(status_code=400, detail=f"Too many columns (max {_MAX_COLS})")
    from utils.report_pdf import build_report_pdf
    pdf = build_report_pdf(
        title=body.title[:200],
        subtitle=body.subtitle[:300],
        columns=body.columns,
        rows=body.rows[:_MAX_ROWS],
        footer=body.footer,
    )
    fname = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in body.title)[:80] or "report"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}.pdf"'})
