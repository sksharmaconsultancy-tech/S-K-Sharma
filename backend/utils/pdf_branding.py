"""Iter 182 — shared PDF branding: punch line footer used across all
statutory / payroll PDF exports ("Your Satisfaction is Our First Ambition")."""
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer
from reportlab.lib import colors as rl_colors

PUNCH_LINE = '"Your Satisfaction is Our First Ambition"'

_style = ParagraphStyle(
    "sks_punchline",
    fontName="Helvetica-Oblique",
    fontSize=8.5,
    textColor=rl_colors.HexColor("#2563EB"),
    alignment=1,  # center
    spaceBefore=10,
)


def punchline_flowables():
    """Returns [Spacer, Paragraph] to append at the end of any PDF story."""
    return [Spacer(1, 8), Paragraph(PUNCH_LINE, _style)]
