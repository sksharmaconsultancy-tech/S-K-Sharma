"""Iter 497 — UNIVERSAL REPORT PDF BUILDER (user spec, PDF phase).

One shared landscape PDF engine used by the Universal Report Table:
  * LANDSCAPE, auto page size (A4 → legal → A3 → A2 by total width)
  * Column widths PROPORTIONAL to the on-screen layout → PDF matches screen
  * Header repeated on every page (banded group row supported)
  * Text cells wrap with Paragraph — no truncated / overlapping text
  * Numbers right-aligned, dates centered (alignment passed per column)
  * Automatic font scaling when many columns; proper page margins
"""
import io
from typing import Any, Dict, List, Optional

from reportlab.lib import colors as rl
from reportlab.lib.pagesizes import A2, A3, A4, landscape, legal
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_PAGES = [landscape(A4), landscape(legal), landscape(A3), landscape(A2)]
_MARGIN = 8 * mm


def build_report_pdf(
    title: str,
    subtitle: str,
    columns: List[Dict[str, Any]],   # [{label, align, width, band?}]
    rows: List[List[Any]],
    footer: Optional[List[str]] = None,
) -> bytes:
    ncols = max(1, len(columns))
    screen_w = sum(float(c.get("width") or 100) for c in columns)

    # Pick the smallest page the table fits on at a readable font; else the
    # largest page with proportional shrink.
    page = _PAGES[-1]
    for p in _PAGES:
        if screen_w * 0.75 <= (p[0] - 2 * _MARGIN):
            page = p
            break
    avail = page[0] - 2 * _MARGIN
    scale = avail / screen_w
    col_w = [max(28.0, float(c.get("width") or 100) * scale) for c in columns]
    # Renormalise after clamping so the table exactly fills the page width.
    tot = sum(col_w)
    col_w = [w * avail / tot for w in col_w]

    font = 8.0 if ncols <= 14 else 7.0 if ncols <= 22 else 6.0

    has_bands = any(c.get("band") for c in columns)
    head_rows = 2 if has_bands else 1

    styles: List[Any] = [
        ("FONTSIZE", (0, 0), (-1, -1), font),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, rl.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        # column header row
        ("BACKGROUND", (0, head_rows - 1), (-1, head_rows - 1), rl.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, head_rows - 1), rl.white),
        ("FONTNAME", (0, 0), (-1, head_rows - 1), "Helvetica-Bold"),
    ]

    data: List[List[Any]] = []
    if has_bands:
        band_row: List[Any] = []
        i = 0
        while i < ncols:
            b = columns[i].get("band")
            if b:
                j = i
                while (j + 1 < ncols and columns[j + 1].get("band")
                       and columns[j + 1]["band"].get("label") == b.get("label")
                       and columns[j + 1]["band"].get("color") == b.get("color")):
                    j += 1
                band_row.append(b.get("label") or "")
                band_row.extend([""] * (j - i))
                styles.append(("SPAN", (i, 0), (j, 0)))
                styles.append(("BACKGROUND", (i, 0), (j, 0),
                               rl.HexColor(b.get("color") or "#1E3A8A")))
                styles.append(("ALIGN", (i, 0), (j, 0), "CENTER"))
                i = j + 1
            else:
                band_row.append("")
                styles.append(("BACKGROUND", (i, 0), (i, 0), rl.HexColor("#1E3A8A")))
                i += 1
        data.append(band_row)

    data.append([str(c.get("label") or "") for c in columns])

    # per-column alignment + zebra striping
    wrap_style = ParagraphStyle("cell", fontSize=font, leading=font + 1.6)
    for ci, c in enumerate(columns):
        a = {"right": "RIGHT", "center": "CENTER"}.get(c.get("align") or "left", "LEFT")
        styles.append(("ALIGN", (ci, 0), (ci, -1), a))

    body_start = head_rows
    char_fit = {ci: max(3, int(col_w[ci] / (font * 0.52))) for ci in range(ncols)}
    for ri, r in enumerate(rows):
        out_row: List[Any] = []
        for ci in range(ncols):
            v = "" if ci >= len(r) or r[ci] is None else str(r[ci])
            if len(v) > char_fit[ci] and (columns[ci].get("align") or "left") == "left":
                out_row.append(Paragraph(
                    v.replace("&", "&amp;").replace("<", "&lt;"), wrap_style))
            else:
                out_row.append(v)
        data.append(out_row)
        if ri % 2 == 1:
            rr = body_start + ri
            styles.append(("BACKGROUND", (0, rr), (-1, rr), rl.HexColor("#F8FAFC")))

    if footer:
        fr = len(data)
        data.append([str(x or "") for x in footer[:ncols]] + [""] * max(0, ncols - len(footer)))
        styles.append(("BACKGROUND", (0, fr), (-1, fr), rl.HexColor("#FEF9C3")))
        styles.append(("FONTNAME", (0, fr), (-1, fr), "Helvetica-Bold"))
        styles.append(("LINEABOVE", (0, fr), (-1, fr), 1, rl.HexColor("#1E3A8A")))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=page,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=_MARGIN, bottomMargin=_MARGIN,
        title=title,
    )
    h1 = ParagraphStyle("h1", fontSize=12, leading=15, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("h2", fontSize=8.5, leading=11, textColor=rl.HexColor("#475569"))
    flow: List[Any] = [Paragraph(title, h1)]
    if subtitle:
        flow.append(Paragraph(subtitle, h2))
    flow.append(Spacer(1, 2.5 * mm))
    tbl = Table(data, colWidths=col_w, repeatRows=head_rows)
    tbl.setStyle(TableStyle(styles))
    flow.append(tbl)
    doc.build(flow)
    return buf.getvalue()
