"""Iter 433 — smoke test the 11-point Payroll Correction report changes."""
import asyncio
import os
import sys

import httpx

BASE = os.environ.get("BASE", "http://localhost:8001/api")
CID = "cmp_527fecdd7c"


async def main():
    async with httpx.AsyncClient(timeout=90) as cl:
        r = await cl.post(f"{BASE}/auth/admin-password-login", json={
            "email": "sksharmaconsultancy@gmail.com", "password": "sharma123"})
        assert r.status_code == 200, r.text
        tok = r.json().get("session_token")
        H = {"Authorization": f"Bearer {tok}"}

        # find a month with a compliance run
        r = await cl.get(f"{BASE}/admin/compliance-salary-runs",
                         params={"company_id": CID}, headers=H)
        runs = r.json().get("runs") or []
        month = runs[0]["month"] if runs else "2026-05"
        print("Using month:", month, "| runs found:", len(runs))
        fy = int(month[:4]) if int(month[5:7]) >= 4 else int(month[:4]) - 1

        ok = fail = 0

        async def hit(label, path, params=None, pdf=False):
            nonlocal ok, fail
            r = await cl.get(f"{BASE}{path}", params=params or {}, headers=H)
            good = r.status_code == 200 and (
                r.content[:4] == b"%PDF" if pdf else True)
            print(("PASS" if good else "FAIL"), label, r.status_code,
                  "" if good else r.text[:200])
            ok += good
            fail += not good
            return r

        # 2. Cost analysis S.No
        r = await hit("ctc-analysis JSON", "/admin/payroll-reports/ctc-analysis",
                      {"company_id": CID, "month": month})
        cols = [c["key"] for c in r.json().get("columns", [])]
        print("  ctc-analysis cols:", cols[:4], "| sno present:", "sno" in cols)

        # 4. F&F with employee filter
        r = await cl.get(f"{BASE}/admin/employees",
                         params={"company_id": CID}, headers=H)
        emps = r.json().get("employees") or []
        eids = ",".join(e["user_id"] for e in emps[:2])
        r = await hit("F&F employee filter",
                      "/admin/payroll-reports/full-and-final",
                      {"company_id": CID, "fy_start_year": fy,
                       "employee_ids": eids})
        print("  F&F rows (2 picked):", len(r.json().get("rows", [])))
        await hit("F&F PDF", "/admin/payroll-reports/full-and-final.pdf",
                  {"company_id": CID, "fy_start_year": fy,
                   "employee_ids": eids}, pdf=True)

        # 6. OT cost analysis employee filter
        await hit("OT cost analysis", "/admin/payroll-reports/ot-cost-analysis",
                  {"company_id": CID, "fy_start_year": fy,
                   "employee_ids": eids})

        # 7. Daily OT — periodic date range + S.No
        r = await hit("ot-daily periodic", "/admin/payroll-reports/ot-daily",
                      {"company_id": CID, "month": month,
                       "from_date": f"{month}-01", "to_date": f"{month}-15"})
        cols = [c["key"] for c in r.json().get("columns", [])]
        print("  ot-daily cols:", cols, "| sno:", "sno" in cols)
        await hit("ot-daily PDF", "/admin/payroll-reports/ot-daily.pdf",
                  {"company_id": CID, "month": month,
                   "from_date": f"{month}-01", "to_date": f"{month}-15"},
                  pdf=True)

        # 8. Dept-wise OT with names
        r = await hit("ot-department", "/admin/payroll-reports/ot-department",
                      {"company_id": CID, "month": month,
                       "from_date": f"{month}-01", "to_date": f"{month}-15"})
        cols = [c["key"] for c in r.json().get("columns", [])]
        print("  ot-department cols:", cols,
              "| names col:", "ot_employee_names" in cols)

        # 3. Fine register — periodic + empty note
        r = await hit("fine-register month",
                      "/admin/govt-registers/fine-register",
                      {"company_id": CID, "month": month})
        j = r.json()
        print("  fine rows:", len(j.get("rows", [])),
              "| empty_note:", j.get("empty_note", "")[:70])
        await hit("fine-register periodic PDF",
                  "/admin/govt-registers/fine-register.pdf",
                  {"company_id": CID, "month": month, "month_to": month},
                  pdf=True)

        # 5. Gratuity with employee filter
        r = await hit("gratuity-register emp filter",
                      "/admin/govt-registers/gratuity-register",
                      {"company_id": CID, "month": month,
                       "employee_ids": eids})
        print("  gratuity rows (2 picked):", len(r.json().get("rows", [])))
        await hit("gratuity PDF", "/admin/govt-registers/gratuity-register.pdf",
                  {"company_id": CID, "month": month}, pdf=True)

        # 1. Arrear register export (need an arrear run)
        r = await cl.get(f"{BASE}/admin/arrear-salary-runs",
                         params={"company_id": CID}, headers=H)
        aruns = r.json().get("runs") or []
        if not aruns:
            r = await cl.post(f"{BASE}/admin/arrear-salary-runs", headers=H,
                              json={"company_id": CID, "from_month": month,
                                    "to_month": month})
            if r.status_code == 200:
                aruns = [r.json()["run"]]
            else:
                print("  (no arrear run available:", r.text[:120], ")")
        if aruns:
            rid = aruns[0]["run_id"]
            await hit("arrear export.pdf",
                      f"/admin/arrear-salary-runs/{rid}/export.pdf", pdf=True)
            await hit("arrear export.xlsx",
                      f"/admin/arrear-salary-runs/{rid}/export.xlsx")

        # 9. Payroll register (bonus head)
        r = await hit("payroll-register JSON",
                      "/admin/reports/payroll-register",
                      {"company_id": CID, "fy_start_year": fy, "limit": 2})
        heads = [h["key"] for h in r.json().get("heads", [])]
        print("  payroll-register heads:", heads)
        await hit("payroll-register PDF",
                  "/admin/reports/payroll-register.pdf",
                  {"company_id": CID, "fy_start_year": fy}, pdf=True)

        # 10. PF contribution PDF
        await hit("pf-contribution PDF", "/admin/reports/pf-contribution.pdf",
                  {"company_id": CID, "month": month}, pdf=True)

        # 11. Salary register compliance PDF
        r = await cl.get(f"{BASE}/admin/compliance-salary-runs",
                         params={"company_id": CID}, headers=H)
        runs = r.json().get("runs") or []
        if runs:
            rid = runs[0]["run_id"]
            await hit("salary register compliance PDF",
                      f"/admin/compliance-salary-runs/{rid}/register.pdf",
                      pdf=True)

        # wage register global font (uses register_pdf)
        await hit("wage-register PDF", "/admin/govt-registers/wage-register.pdf",
                  {"company_id": CID, "month": month}, pdf=True)

        print(f"\nRESULT: {ok} passed, {fail} failed")
        sys.exit(1 if fail else 0)


asyncio.run(main())
