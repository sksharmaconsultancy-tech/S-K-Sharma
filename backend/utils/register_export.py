"""Iter 357 — shared register-style PDF/Excel export builder.

Used by Labour Statistics, Annual Returns and Factory & Boilers modules.
A3-landscape professional register: title, company logo, column headers
repeated on every page, totals row, page numbers.
"""
from io import BytesIO
from typing import Any, Dict, List, Optional


def register_xlsx(title: str, subtitle: str, columns: List[Dict[str, str]],
                  rows: List[dict], totals: Optional[dict] = None) -> BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Register"
    n = len(columns)
    thin = Side(style="thin", color="9AA0A6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    ws.cell(1, 1, title).font = Font(bold=True, size=13)
    ws.cell(1, 1).alignment = Alignment(horizontal="center")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n)
    ws.cell(2, 1, subtitle).alignment = Alignment(horizontal="center")
    for j, c in enumerate(columns, 1):
        cell = ws.cell(4, j, c["label"])
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
        cell.border = border
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = max(
            11, min(28, len(c["label"]) + 4))
    r = 5
    for row in rows:
        for j, c in enumerate(columns, 1):
            v = row.get(c["key"])
            cell = ws.cell(r, j, v)
            cell.border = border
            if isinstance(v, (int, float)):
                cell.number_format = "#,##0.##"
                cell.alignment = Alignment(horizontal="right")
        r += 1
    if totals:
        for j, c in enumerate(columns, 1):
            v = totals.get(c["key"], "TOTAL" if j == 1 else None)
            cell = ws.cell(r, j, v)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="FFF2CC")
            cell.border = border
            if isinstance(v, (int, float)):
                cell.number_format = "#,##0.##"
                cell.alignment = Alignment(horizontal="right")
    ws.freeze_panes = "A5"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 8
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def register_pdf(title: str, subtitle: str, columns: List[Dict[str, str]],
                 rows: List[dict], totals: Optional[dict] = None,
                 logo_b64: Optional[str] = None) -> BytesIO:
    import base64
    from reportlab.lib import colors as rl
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A3), leftMargin=8 * mm,
                            rightMargin=8 * mm, topMargin=8 * mm,
                            bottomMargin=10 * mm, title=title)
    W = landscape(A3)[0] - 16 * mm
    story: List[Any] = []
    if logo_b64:
        try:
            raw = base64.b64decode(logo_b64.split(",")[-1])
            story.append(Image(BytesIO(raw), width=20 * mm, height=20 * mm))
        except Exception:  # noqa: BLE001
            pass
    story.append(Paragraph(title, ParagraphStyle(
        "h", fontSize=13, fontName="Helvetica-Bold", alignment=1)))
    story.append(Paragraph(subtitle, ParagraphStyle(
        "s", fontSize=8.5, alignment=1)))
    story.append(Spacer(1, 4 * mm))
    data = [[c["label"] for c in columns]]
    for row in rows:
        data.append([
            (f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float)
             else ("" if v is None else str(v)))
            for v in (row.get(c["key"]) for c in columns)])
    styles = [
        ("FONTSIZE", (0, 0), (-1, -1), 6.8),
        ("GRID", (0, 0), (-1, -1), 0.4, rl.HexColor("#9AA0A6")),
        ("BACKGROUND", (0, 0), (-1, 0), rl.HexColor("#DDEBF7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if totals:
        data.append([
            (f"{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float)
             else ("" if v is None else str(v)))
            for v in (totals.get(c["key"], "TOTAL" if i == 0 else None)
                      for i, c in enumerate(columns))])
        styles += [
            ("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1),
             rl.HexColor("#FFF2CC")),
            ("FONTNAME", (0, len(data) - 1), (-1, len(data) - 1),
             "Helvetica-Bold")]
    tbl = Table(data, colWidths=[W / len(columns)] * len(columns),
                repeatRows=1)
    tbl.setStyle(TableStyle(styles))
    story.append(tbl)

    def _page(cv, d):
        cv.setFont("Helvetica", 7)
        from reportlab.lib.pagesizes import A3 as _A3, landscape as _ls
        cv.drawRightString(_ls(_A3)[0] - 8 * mm, 5 * mm,
                           f"Page {cv.getPageNumber()}")
    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    buf.seek(0)
    return buf
