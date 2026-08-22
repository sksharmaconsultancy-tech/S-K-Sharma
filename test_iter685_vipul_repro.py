"""Iter 685 repro — VIPUL ENTERPRISES: STIPHAN daily rate 300 shows
M.Basic/M.Gross 16120 (= 520×31) in the Compliance grid.

Hypotheses (grid shows master 16120 with month_days=31):
 H1: stale policy.salary=520 (employee_policy) beats compliance settings
 H2: stale compliance_gross=16120 (monthly-era value)
 H3: stale salary_monthly=16120
 H4: stale basic_amount=16120 override skewing structure
"""
import sys
sys.path.insert(0, "/app/backend")
from utils.compliance_salary import compute_compliance_row

STATS0 = {"present_days": 0, "effective_present": 0, "duty_hours": 0,
          "ot_hours": 0, "half_days": 0}


def show(tag, user, policy):
    row = compute_compliance_row(user, policy, 31, dict(STATS0))
    print(f"{tag}: mode={row['salary_mode']} rate={row['rate']} "
          f"M.Basic={row['basic_master']} M.Gross={row['gross_master']} "
          f"basic={row['basic']} gross={row.get('gross_earning', row.get('monthly_gross'))}")


BASE = {
    "user_id": "u1", "name": "STIPHAN", "employee_code": "18",
    "company_id": "cmp_vipul", "employee_type": "STAFF",
    "compliance_salary_mode": "daily",
    "compliance_basic": 300,
}

# H1 — stale employee_policy carries salary 520 (daily era)
show("H1 policy.salary=520      ", dict(BASE), {"salary": 520, "salary_mode": "daily"})
# H2 — stale compliance_gross 16120 (monthly era)
show("H2 compliance_gross=16120 ", {**BASE, "compliance_gross": 16120}, {})
# H2b — stale compliance_gross 520 (daily era gross)
show("H2b compliance_gross=520  ", {**BASE, "compliance_gross": 520}, {})
# H3 — stale salary_monthly=16120
show("H3 salary_monthly=16120   ", {**BASE, "salary_monthly": 16120}, {})
# H4 — stale basic_amount=16120
show("H4 basic_amount=16120     ", {**BASE, "basic_amount": 16120, "compliance_gross": 16120}, {})
# Clean master — what SHOULD happen
show("CLEAN (expected)          ", dict(BASE), {})
