"""Iter 551 — FEATURES LIST PDF (user request: separate downloadable PDF).

Renders /app/USER_MANUAL_FEATURES.md ("Software Features & Functionalities")
into a clean A4 PDF, downloadable from the User Manual screen.
"""
import io
import os
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from server import get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api/admin", tags=["features-pdf"])
MD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "USER_MANUAL_FEATURES.md")


def _clean(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    return s.replace("&", "&amp;").replace("**", "").replace("<b>", "<b>").strip()


@router.get("/features-list.pdf")
async def features_list_pdf(authorization: Optional[str] = Header(None)):
    u = await get_user_from_token(authorization)
    require_role(u, ["super_admin", "sub_admin", "company_admin"])
    path = os.path.abspath(MD_PATH)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Feature list document missing")
    md = open(path, encoding="utf-8").read().splitlines()

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors as C
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, PageBreak)
    from reportlab.lib.styles import ParagraphStyle

    T = ParagraphStyle("t", fontSize=16, fontName="Helvetica-Bold", alignment=1,
                       textColor=C.HexColor("#0F3D3E"))
    H2 = ParagraphStyle("h2", fontSize=12, fontName="Helvetica-Bold",
                        textColor=C.HexColor("#0F3D3E"), spaceBefore=10, spaceAfter=4)
    H3 = ParagraphStyle("h3", fontSize=10.5, fontName="Helvetica-Bold",
                        textColor=C.HexColor("#B45309"), spaceBefore=8, spaceAfter=3)
    P = ParagraphStyle("p", fontSize=8.5, fontName="Helvetica", leading=11.5)
    CELL = ParagraphStyle("c", fontSize=7.2, fontName="Helvetica", leading=9)
    CELLH = ParagraphStyle("ch", fontSize=7.2, fontName="Helvetica-Bold", leading=9)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10*mm,
                            rightMargin=10*mm, topMargin=10*mm, bottomMargin=12*mm)
    story = []
    table_rows = []

    def flush_table():
        nonlocal table_rows
        if not table_rows:
            return
        ncols = max(len(r) for r in table_rows)
        rows = [[Paragraph(_clean(c), CELLH if i == 0 else CELL)
                 for c in (r + [""] * (ncols - len(r)))]
                for i, r in enumerate(table_rows)]
        avail = landscape(A4)[0] - 20 * mm
        widths = None
        if ncols == 8:  # master feature table
            fr = [0.05, 0.11, 0.12, 0.13, 0.31, 0.12, 0.09, 0.07]
            widths = [avail * f for f in fr]
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, C.HexColor("#CBD5E1")),
            ("BACKGROUND", (0, 0), (-1, 0), C.HexColor("#0F3D3E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), C.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C.white, C.HexColor("#F5F8FA")]),
        ]))
        story.append(t)
        story.append(Spacer(1, 4))
        table_rows = []

    for line in md:
        s = line.rstrip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.match(r"^:?-{3,}:?$", c) for c in cells if c):
                continue
            table_rows.append(cells)
            continue
        flush_table()
        if not s.strip() or s.startswith("---"):
            continue
        if s.startswith("# "):
            story.append(Paragraph(_clean(s[2:]), T))
        elif s.startswith("### "):
            story.append(Paragraph(_clean(s[4:]), H3))
        elif s.startswith("## "):
            if story:
                story.append(Spacer(1, 6))
            story.append(Paragraph(_clean(s[3:]), H2))
        elif s.startswith("- ") or re.match(r"^\d+\.\s", s):
            story.append(Paragraph("•  " + _clean(re.sub(r"^(-|\d+\.)\s", "", s)), P))
        elif s.startswith("*") and s.endswith("*"):
            story.append(Paragraph("<i>" + _clean(s.strip("*")) + "</i>", P))
        else:
            story.append(Paragraph(_clean(s), P))
    flush_table()
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<i>Generated on {datetime.now().strftime('%d-%m-%Y %H:%M')} — "
        f"S.K. Sharma & Co. Payroll & HR Compliance Software</i>", P))
    doc.build(story)
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition":
                             'attachment; filename="Software_Features_List.pdf"'})
