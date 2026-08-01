"""Iter 425 — Higher PF auto-approved (no ceiling) + VPF on top checks."""
import sys
sys.path.insert(0, "/app/backend")
from utils.compliance_salary import compute_compliance_row  # noqa: E402

BASE_USER = {
    "user_id": "u1", "name": "TEST", "salary_mode": "monthly",
    "compliance_basic": 25000, "pf_basic": 25000, "compliance_gross": 25000,
    "pf_applicable": True, "esic_applicable": False,
}
STATS = {"present_days": 30, "half_days": 0, "effective_present": 30,
         "duty_hours": 240, "ot_hours": 0}
CFG = {"allow_higher_pf": True, "_salary_month": "2026-06",
       "wage_definition_rule_enabled": False}

# 1. HIGHER PF — no approval fields set at all → must still activate.
u = dict(BASE_USER, pf_contribution_type="higher")
row = compute_compliance_row(u, {}, 30, STATS, statutory_cfg=CFG)
print("HIGHER: active =", row["pf_higher_active"], "| reason =", repr(row["pf_higher_reason"]),
      "| pf_wages =", row["pf_wages"], "| pf_employee =", row["pf_employee"])
assert row["pf_higher_active"] is True, "Higher PF should auto-approve"
assert row["pf_wages"] > 15000, f"Ceiling still applied! wages={row['pf_wages']}"
assert row["pf_employee"] == round(row["pf_wages"] * 0.12), "12% on full wages expected"

# 1b. Even with approval explicitly 'pending' + required → still active.
u2 = dict(u, pf_approval_required=True, pf_approval_status="pending")
row2 = compute_compliance_row(u2, {}, 30, STATS, statutory_cfg=CFG)
print("HIGHER (pending): active =", row2["pf_higher_active"], "| pf_wages =", row2["pf_wages"])
assert row2["pf_higher_active"] is True, "approval must be ignored"

# 1c. Company toggle OFF → falls back to ceiling with reason.
row3 = compute_compliance_row(u, {}, 30, STATS,
                              statutory_cfg=dict(CFG, allow_higher_pf=False))
print("HIGHER (toggle off): active =", row3["pf_higher_active"],
      "| reason =", row3["pf_higher_reason"], "| pf_wages =", row3["pf_wages"])
assert row3["pf_higher_active"] is False and row3["pf_wages"] == 15000

# 2. VPF — statutory ceiling + 10% VPF on top (employee side only).
uv = dict(BASE_USER, pf_contribution_type="vpf", vpf_percent=10)
rowv = compute_compliance_row(uv, {}, 30, STATS, statutory_cfg=CFG)
exp_stat = round(15000 * 0.12)
exp_vpf = round(15000 * 0.10)
print("VPF: pf_wages =", rowv["pf_wages"], "| pf_employee =", rowv["pf_employee"],
      "| vpf_amount =", rowv.get("vpf_amount"), "| employer_total =", rowv["pf_employer_total"])
assert rowv["pf_wages"] == 15000
assert rowv["pf_employee"] == exp_stat + exp_vpf, \
    f"expected {exp_stat}+{exp_vpf}, got {rowv['pf_employee']}"
assert rowv["pf_employer_total"] == round(15000 * 0.0367) + round(15000 * 0.0833), \
    "employer side must stay statutory"

# 2b. VPF with company allow_vpf = False → no VPF.
rowv2 = compute_compliance_row(uv, {}, 30, STATS,
                               statutory_cfg=dict(CFG, allow_vpf=False))
print("VPF (disallowed): pf_employee =", rowv2["pf_employee"])
assert rowv2["pf_employee"] == exp_stat, "VPF must be skipped when disallowed"

print("ALL HIGHER-PF / VPF CHECKS PASSED")
