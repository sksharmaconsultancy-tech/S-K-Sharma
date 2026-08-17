"""Iter 597 — Contractor PF Calculation Rule engine tests (user spec)."""
import sys
sys.path.insert(0, "/app/backend")
from utils.compliance_salary import compute_compliance_row  # noqa: E402

BASE_USER = {
    "salary_monthly": 22000, "pf_applicable": True, "esic_applicable": True,
}


def row(pf_basic, present, cfg, extra=None, month_days=30):
    u = dict(BASE_USER, pf_basic=pf_basic)
    if extra:
        u.update(extra)
    stats = {"present_days": present, "half_days": 0,
             "effective_present": present, "duty_hours": 0, "ot_hours": 0}
    return compute_compliance_row(u, {"salary_mode": "monthly"}, month_days, stats,
                                  statutory_cfg=cfg)


CONTRACTOR = {"contractor_pf_mode": "contractor_wage_based"}
ok = True


def chk(name, r, wages, pf):
    global ok
    good = abs(r["pf_wages"] - wages) < 1 and abs(r["pf_employee"] - pf) < 1
    ok &= good
    print(f"{'PASS' if good else 'FAIL'}  {name}: wages={r['pf_wages']} (exp {wages}) "
          f"pf={r['pf_employee']} (exp {pf})")
    if not good:
        print("      reason:", r["pf_reason"])


# ── Spec Example 1 / Rule 2: Basic+DA 18,000, FULL month → wage 15,000, PF 1,800
chk("Rule 2 full month 18k", row(18000, 30, CONTRACTOR), 15000, 1800)

# ── Spec Example 2 / Rule 3: 18,000, 12 of 30 days → earned 7,200 → PF 864
r3 = row(18000, 12, CONTRACTOR)
chk("Rule 3 partial 12/30", r3, 7200, 864)
# Employer also on 7,200: EPS 8.33% = 600, EPF 3.67% = 264
ok &= abs(r3["pf_employer_eps"] - 600) < 1 and abs(r3["pf_employer_epf"] - 264) < 1
print(f"      employer split EPS={r3['pf_employer_eps']} EPF={r3['pf_employer_epf']}")

# ── Rule 1: PF Basic 12,000 below ceiling, full month → PF on earned 12,000
#    (no 50% floor even though gross 22,000 → floor would give 11,000; earned wins as-is)
chk("Rule 1 below ceiling", row(12000, 30, CONTRACTOR), 12000, 1440)

# ── Rule 4 — Adopt PF (higher), partial month, COMPANY POLICY (default adopted_wage):
hi = {"pf_contribution_type": "higher", "higher_pf_wage": 20000}
r4a = row(18000, 12, CONTRACTOR, extra=hi)
chk("Rule 4 adopted (default)", r4a, 20000, 2400)

# ── Rule 4 — earned_wage option → 20,000 × 12/30 = 8,000 → PF 960
r4b = row(18000, 12, {**CONTRACTOR, "contractor_partial_month_rule": "earned_wage"}, extra=hi)
chk("Rule 4 earned option", r4b, 8000, 960)

# ── REGRESSION — standard mode unchanged: 18,000 PF Basic full month =
#    adopted-higher rule (Iter 456) → PF on full earned 18,000 → 2,160
chk("Standard mode regression 18k", row(18000, 30, {}), 18000, 2160)
# Standard partial 12/30 → earned 7,200 vs floor 50% of gross-paid 8,800 → 8,800 → 864? no:
rstd = row(18000, 12, {})
print(f"INFO  standard partial: wages={rstd['pf_wages']} pf={rstd['pf_employee']} ({rstd['pf_reason'][:90]})")
# Standard 12,000 full month with 22,000 gross → floor 11,000 < 12,000 → wage 12,000 → 1,440
chk("Standard below-ceiling regression", row(12000, 30, {}), 12000, 1440)

# ── contractor note present in pf_reason
ok &= "CONTRACTOR WAGE-BASED PF" in r3["pf_reason"] and "Rule 3" in r3["pf_reason"]
print("      reason sample:", r3["pf_reason"])
ok &= r3["calc_snapshot"]["contractor_pf_mode"] == "contractor_wage_based"

print("RESULT:", "PASS ✅" if ok else "FAIL ❌")
sys.exit(0 if ok else 1)
