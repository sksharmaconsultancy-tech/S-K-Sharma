"""Iter 408 backend tests — Higher PF & VPF support.

Covers:
1. Employee PF fields save + pf_audit_log entry
2. Compliance settings (allow_higher_pf/allow_vpf/vpf_max_percent)
3. Create compliance run + row shape (pf_contribution_type, pf_higher_active,
   pf_ceiling_applied)
4. PF contribution report (JSON + xlsx + pdf) for views all/higher
5. Lock validation error surface + super-admin allow_errors override
6. HIGHER_PF_APPROVAL_PENDING validation code appears when approval=pending

Mandatory cleanup: reverts employee master fields, compliance settings,
and deletes created runs at the end.
"""
import os
import re
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_BACKEND_URL")
            or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
COMPANY_ID = "cmp_527fecdd7c"
MONTH = "2026-07"

SUPER_EMAIL = "sksharmaconsultancy@gmail.com"
SUPER_PASSWORD = "sharma123"


# ---------------------------- fixtures ----------------------------
@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": SUPER_EMAIL, "password": SUPER_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("session_token")
    assert tok, f"no session_token in login response: {r.text[:200]}"
    return tok


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def state():
    """Shared mutable state across ordered tests."""
    return {
        "test_uid": None,
        "old_settings": None,
        "run_ids": [],
        "old_emp_pf": {},
    }


# ---------------------------- module-scoped ordered tests ----------------------------
@pytest.mark.dependency(name="login")
def test_login(token):
    assert token


@pytest.mark.dependency(name="pick_emp", depends=["login"])
def test_pick_employee(auth, state):
    r = requests.get(
        f"{BASE_URL}/api/admin/employees",
        params={"company_id": COMPANY_ID, "limit": 5},
        headers=auth, timeout=30)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    emps = data.get("employees") or data.get("items") or data.get("rows") or data
    if isinstance(emps, dict):
        emps = emps.get("employees") or emps.get("items") or []
    assert emps and isinstance(emps, list), f"no employees returned: {str(data)[:200]}"
    uid = emps[0].get("user_id")
    assert uid, f"first emp missing user_id: {emps[0]}"
    state["test_uid"] = uid
    # snapshot original PF fields for cleanup
    p = requests.get(f"{BASE_URL}/api/admin/employees/{uid}/profile",
                     headers=auth, timeout=20)
    assert p.status_code == 200, p.text[:200]
    js = p.json()
    for k in ("pf_contribution_type", "higher_pf_wage", "pf_approval_status",
              "pf_declaration_available", "pf_remarks", "vpf_percent",
              "vpf_amount", "vpf_enabled", "higher_pf_from", "higher_pf_to",
              "pf_approval_required"):
        state["old_emp_pf"][k] = js.get(k)


# ---- 1. PF fields save (Higher PF, Approved) ----
@pytest.mark.dependency(name="save_pf_fields", depends=["pick_emp"])
def test_save_pf_fields_higher_approved(auth, state):
    uid = state["test_uid"]
    body = {
        "pf_contribution_type": "higher",
        "higher_pf_wage": 30000,
        "pf_approval_status": "approved",
        "pf_declaration_available": True,
        "pf_remarks": "QA_TEST higher pf",
    }
    # PATCH is the actual route method; PUT (as spec says) is tried as fallback
    r = requests.patch(f"{BASE_URL}/api/admin/employees/{uid}/profile",
                       json=body, headers=auth, timeout=30)
    if r.status_code == 405:
        r = requests.put(f"{BASE_URL}/api/admin/employees/{uid}/profile",
                         json=body, headers=auth, timeout=30)
    assert r.status_code == 200, f"save PF fields failed: {r.status_code} {r.text[:300]}"

    # GET back and verify persistence
    g = requests.get(f"{BASE_URL}/api/admin/employees/{uid}/profile",
                     headers=auth, timeout=20)
    assert g.status_code == 200
    prof = g.json()
    assert (prof.get("pf_contribution_type") or "").lower() == "higher"
    assert float(prof.get("higher_pf_wage") or 0) == 30000
    assert (prof.get("pf_approval_status") or "").lower() == "approved"
    assert prof.get("pf_declaration_available") is True
    assert "QA_TEST" in (prof.get("pf_remarks") or "")


# ---- 2. Compliance settings ----
@pytest.mark.dependency(name="settings", depends=["login"])
def test_compliance_settings_higher_pf_vpf(auth, state):
    r = requests.get(f"{BASE_URL}/api/admin/compliance-settings",
                     headers=auth, timeout=20)
    assert r.status_code == 200, r.text[:200]
    cur = r.json().get("settings") or {}
    state["old_settings"] = {
        "allow_higher_pf": cur.get("allow_higher_pf"),
        "allow_vpf": cur.get("allow_vpf"),
        "vpf_max_percent": cur.get("vpf_max_percent"),
    }
    body = {"allow_higher_pf": True, "allow_vpf": True, "vpf_max_percent": 20}
    p = requests.put(f"{BASE_URL}/api/admin/compliance-settings",
                     json=body, headers=auth, timeout=20)
    assert p.status_code == 200, f"put settings: {p.status_code} {p.text[:200]}"
    # read back
    g = requests.get(f"{BASE_URL}/api/admin/compliance-settings",
                     headers=auth, timeout=20)
    s = g.json().get("settings") or {}
    assert s.get("allow_higher_pf") is True
    assert s.get("allow_vpf") is True
    assert float(s.get("vpf_max_percent") or 0) == 20


# ---- 3. Create compliance run + row shape ----
@pytest.mark.dependency(name="create_run",
                       depends=["save_pf_fields", "settings"])
def test_create_compliance_run(auth, state):
    # First, unlock any pre-existing finalized run for this month so a
    # fresh create/reprocess is possible.
    lst = requests.get(
        f"{BASE_URL}/api/admin/compliance-salary-runs",
        params={"company_id": COMPANY_ID, "month": MONTH},
        headers=auth, timeout=20)
    if lst.status_code == 200:
        existing = (lst.json().get("runs") or lst.json().get("items")
                    or lst.json() or [])
        if isinstance(existing, dict):
            existing = existing.get("runs") or []
        for run in existing:
            if run.get("finalized"):
                requests.post(
                    f"{BASE_URL}/api/admin/compliance-salary-runs/"
                    f"{run['run_id']}/unlock-request",
                    json={"reason": "QA_TEST prepare"}, headers=auth, timeout=30)

    body = {"month": MONTH, "company_id": COMPANY_ID,
            "use_imported_sheet": True}
    r = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs",
                      json=body, headers=auth, timeout=120)
    # If still blocked because an unlocked run already exists (unique-per-
    # month rule), reuse the latest one via reprocess.
    if r.status_code == 409:
        lst2 = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs",
            params={"company_id": COMPANY_ID, "month": MONTH},
            headers=auth, timeout=20)
        runs = (lst2.json().get("runs") or lst2.json().get("items") or [])
        if isinstance(runs, dict):
            runs = runs.get("runs") or []
        assert runs, f"create returned 409 but no runs listed: {r.text[:200]}"
        run_id = runs[0].get("run_id")
        rp = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/reprocess",
            json={"use_imported_sheet": True}, headers=auth, timeout=120)
        assert rp.status_code == 200, f"reprocess: {rp.status_code} {rp.text[:300]}"
        state["reused_run_id"] = run_id  # don't delete pre-existing
    else:
        assert r.status_code == 200, f"create run: {r.status_code} {r.text[:300]}"
        js = r.json()
        run_id = js.get("run_id") or (js.get("run") or {}).get("run_id")
        assert run_id, f"no run_id: {str(js)[:300]}"
        state["run_ids"].append(run_id)

    state["current_run_id"] = run_id

    # Fetch run and locate our modified employee
    g = requests.get(f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}",
                     headers=auth, timeout=30)
    assert g.status_code == 200
    run = g.json()
    rows = run.get("rows") or (run.get("run") or {}).get("rows") or []
    assert rows, "run has no rows"
    # keys presence check on FIRST row
    for k in ("pf_contribution_type", "pf_higher_active", "pf_ceiling_applied"):
        assert k in rows[0], f"row missing key: {k}"
    ours = next((r for r in rows if r.get("user_id") == state["test_uid"]), None)
    assert ours is not None, "test employee not present in run rows"
    assert str(ours.get("pf_contribution_type") or "").lower() == "higher", \
        f"expected higher, got {ours.get('pf_contribution_type')}"


# ---- 4. PF contribution report ----
@pytest.mark.dependency(name="report_json", depends=["create_run"])
def test_pf_report_json_all_and_higher(auth):
    r = requests.get(
        f"{BASE_URL}/api/admin/reports/pf-contribution",
        params={"company_id": COMPANY_ID, "month": MONTH, "view": "all"},
        headers=auth, timeout=30)
    assert r.status_code == 200, r.text[:200]
    js = r.json()
    assert "rows" in js and "summary" in js and "policy" in js, \
        f"missing keys: {list(js.keys())}"

    # view=higher — every row must be HIGHER (uppercased in output)
    r2 = requests.get(
        f"{BASE_URL}/api/admin/reports/pf-contribution",
        params={"company_id": COMPANY_ID, "month": MONTH, "view": "higher"},
        headers=auth, timeout=30)
    assert r2.status_code == 200
    for row in (r2.json().get("rows") or []):
        assert str(row.get("pf_contribution_type") or "").upper() == "HIGHER", \
            f"non-higher row leaked: {row.get('pf_contribution_type')}"


@pytest.mark.dependency(name="report_bin", depends=["create_run"])
def test_pf_report_xlsx_and_pdf(auth):
    x = requests.get(
        f"{BASE_URL}/api/admin/reports/pf-contribution.xlsx",
        params={"company_id": COMPANY_ID, "month": MONTH, "view": "all"},
        headers=auth, timeout=30)
    assert x.status_code == 200, x.text[:200]
    assert x.content[:2] == b"PK", "xlsx not a zip/xlsx binary"

    p = requests.get(
        f"{BASE_URL}/api/admin/reports/pf-contribution.pdf",
        params={"company_id": COMPANY_ID, "month": MONTH, "view": "all"},
        headers=auth, timeout=30)
    assert p.status_code == 200, p.text[:200]
    assert p.content[:4] == b"%PDF", "pdf magic missing"


# ---- 5. Finalize: allow_errors override ----
@pytest.mark.dependency(name="finalize_override", depends=["create_run"])
def test_finalize_validation_and_override(auth, state):
    run_id = state["current_run_id"]
    # Try to finalize without override — may 200 (no issues), 422 (errors) or
    # 409 (warnings only). Only the 422 branch exercises Iter-407 override.
    r = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/finalize",
        json={}, headers=auth, timeout=60)
    if r.status_code == 422:
        det = (r.json() or {}).get("detail") or {}
        assert det.get("can_override") is True, f"can_override missing: {det}"
        val = det.get("validation") or {}
        assert "rows" in val, f"no rows in validation: {val}"
        # Override
        r2 = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/finalize",
            json={"allow_errors": True}, headers=auth, timeout=60)
        assert r2.status_code == 200, f"override finalize: {r2.status_code} {r2.text[:300]}"
        js2 = r2.json()
        lv = js2.get("lock_validation") or {}
        assert lv.get("errors_overridden") is True, f"errors_overridden not set: {lv}"
    elif r.status_code == 409:
        # warnings only — override with allow_warnings
        r2 = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/finalize",
            json={"allow_warnings": True}, headers=auth, timeout=60)
        assert r2.status_code == 200
    else:
        assert r.status_code == 200, f"unexpected finalize: {r.status_code} {r.text[:300]}"

    # Unlock so we can delete in cleanup (super admin -> immediate unlock)
    u = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/unlock-request",
        json={"reason": "QA_TEST cleanup"}, headers=auth, timeout=30)
    assert u.status_code == 200, u.text[:200]


# ---- 6. HIGHER_PF_APPROVAL_PENDING validation code ----
@pytest.mark.dependency(name="pending_code", depends=["finalize_override"])
@pytest.mark.skip(reason="Iter 425 (user directive) — Higher PF approval "
                         "gating removed: employee type=higher + effective "
                         "window is enough; no APPROVAL_PENDING validation.")
def test_higher_pf_approval_pending_validation(auth, state):
    uid = state["test_uid"]
    # Set approval back to pending
    body = {"pf_approval_status": "pending", "pf_approval_required": True}
    r = requests.patch(f"{BASE_URL}/api/admin/employees/{uid}/profile",
                       json=body, headers=auth, timeout=30)
    assert r.status_code == 200, r.text[:200]

    # Recompute the run (in place) via reprocess
    run_id = state["current_run_id"]
    rp = requests.post(
        f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/reprocess",
        json={"use_imported_sheet": True}, headers=auth, timeout=120)
    print(f"[iter408] reprocess {run_id}: {rp.status_code} {rp.text[:200]}")
    # If reprocess unavailable, unlock+delete+recreate
    if rp.status_code not in (200, 201):
        # Try unlock (in case finalized) then delete then create
        requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/unlock-request",
            json={"reason": "QA_TEST retry"}, headers=auth, timeout=20)
        requests.delete(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}",
            headers=auth, timeout=20)
        cr = requests.post(f"{BASE_URL}/api/admin/compliance-salary-runs",
                           json={"month": MONTH, "company_id": COMPANY_ID,
                                 "use_imported_sheet": True},
                           headers=auth, timeout=120)
        assert cr.status_code == 200, f"fallback create: {cr.status_code} {cr.text[:300]}"
        cj = cr.json()
        run_id = cj.get("run_id") or (cj.get("run") or {}).get("run_id")
        assert run_id, f"no run_id in fallback: {cj}"
        state["run_ids"].append(run_id)
        state["current_run_id"] = run_id

    # Validate — either dedicated endpoint or embedded in finalize 422
    v = requests.get(
        f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/validate",
        headers=auth, timeout=30)
    codes = set()
    if v.status_code == 200:
        for row in (v.json().get("rows") or []):
            if row.get("user_id") == uid:
                codes.update(i.get("code") for i in row.get("issues") or [])
    else:
        # try finalize which will surface validation
        f = requests.post(
            f"{BASE_URL}/api/admin/compliance-salary-runs/{run_id}/finalize",
            json={}, headers=auth, timeout=60)
        js_err = {}
        try:
            js_err = f.json()
        except Exception:
            pass
        det = js_err.get("detail") if isinstance(js_err, dict) else None
        if isinstance(det, dict):
            for row in ((det.get("validation") or {}).get("rows") or []):
                if row.get("user_id") == uid:
                    codes.update(i.get("code") for i in row.get("issues") or [])
        else:
            pytest.fail(
                f"validate failed ({v.status_code} {v.text[:150]}) and "
                f"finalize did not return structured detail: "
                f"{f.status_code} {f.text[:200]}")

    assert "HIGHER_PF_APPROVAL_PENDING" in codes, \
        f"HIGHER_PF_APPROVAL_PENDING not found; got codes={codes}"


# ---- CLEANUP: revert employee + settings + delete runs ----
def test_zzz_cleanup(auth, state):
    uid = state.get("test_uid")
    if uid:
        revert = {
            "pf_contribution_type": "statutory",
            "higher_pf_wage": 0,
            "pf_approval_status": "",
            "pf_remarks": "",
            "pf_declaration_available": False,
        }
        requests.patch(f"{BASE_URL}/api/admin/employees/{uid}/profile",
                       json=revert, headers=auth, timeout=30)
    old = state.get("old_settings") or {}
    if old:
        payload = {
            "allow_higher_pf": bool(old.get("allow_higher_pf")) if old.get("allow_higher_pf") is not None else False,
            "vpf_max_percent": float(old.get("vpf_max_percent") or 0),
        }
        if old.get("allow_vpf") is not None:
            payload["allow_vpf"] = bool(old.get("allow_vpf"))
        requests.put(f"{BASE_URL}/api/admin/compliance-settings",
                     json=payload, headers=auth, timeout=20)
    for rid in state.get("run_ids") or []:
        requests.delete(f"{BASE_URL}/api/admin/compliance-salary-runs/{rid}",
                        headers=auth, timeout=30)
    # nothing to assert — best-effort cleanup
    assert True
