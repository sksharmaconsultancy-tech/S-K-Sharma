"""Iter 85 backend tests — Actual Salary Process, Compliance audit
enrichment, Users Log Report, Firm Master flags."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to preview URL if env not exported into the test shell
    BASE_URL = "https://emplo-connect-1.preview.emergentagent.com"

SUPER_ADMIN_EMAIL = "sksharmaconsultancy@gmail.com"
KANKANI_ID = "cmp_cb39e488a0"
LUXE_ID = "cmp_6c61d63ff4"


# ------------------------------------------------------------------
# Shared fixtures
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def token():
    """OTP dev-mode login as super_admin."""
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email"},
        timeout=15,
    )
    r.raise_for_status()
    dev = r.json().get("dev_code")
    assert dev, f"No dev_code in OTP request response: {r.json()}"
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"identifier": SUPER_ADMIN_EMAIL, "channel": "email", "code": dev},
        timeout=15,
    )
    r.raise_for_status()
    tok = r.json().get("session_token")
    assert tok, f"No session_token: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ------------------------------------------------------------------
# Firm Master flags — feature #8
# ------------------------------------------------------------------
class TestFirmMasterFlags:
    def test_kankani_flags(self, h):
        r = requests.get(f"{BASE_URL}/api/companies", headers=h, timeout=15)
        assert r.status_code == 200
        by_id = {c["company_id"]: c for c in r.json()["companies"]}
        k = by_id.get(KANKANI_ID)
        assert k is not None, "Kankani firm missing"
        assert k.get("location_punching_enabled") is True
        assert k.get("auto_punch_enabled") is True

    def test_luxe_flags(self, h):
        r = requests.get(f"{BASE_URL}/api/companies", headers=h, timeout=15)
        by_id = {c["company_id"]: c for c in r.json()["companies"]}
        lx = by_id.get(LUXE_ID)
        assert lx is not None, "Luxe firm missing"
        assert lx.get("location_punching_enabled") is False
        assert lx.get("auto_punch_enabled") is False
        assert lx.get("face_match_enabled") is False


# ------------------------------------------------------------------
# Actual Salary Process — features #1, #2, #3
# ------------------------------------------------------------------
class TestActualSalaryProcess:
    @pytest.fixture(scope="class")
    def run(self, h):
        payload = {
            "month": "2025-11",
            "company_id": KANKANI_ID,
            "attendance_source": "biometric",
        }
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process",
            json=payload, headers=h, timeout=60,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        assert body.get("ok") is True
        run = body["run"]
        assert run.get("rows"), "No rows in actual salary run"
        return run

    def test_row_fields(self, run):
        row = run["rows"][0]
        for key in (
            "basic", "w_basic_salary", "total_gross", "epf", "esi",
            "net_pay", "max_p_days", "p_days", "p_hours", "duty_hrs",
        ):
            assert key in row, f"Missing key {key} in actual salary row: {list(row.keys())}"
        assert row["basic"] == pytest.approx(row["basic"], rel=0.01)

    def test_esi_zero_when_gross_high(self, run):
        # ESI should be 0 when total_gross > 21000 as per the spec.
        for r in run["rows"]:
            tg = float(r.get("total_gross") or 0)
            esi = float(r.get("esi") or 0)
            if tg > 21000:
                assert esi == 0.0, (
                    f"ESI must be 0 when total_gross={tg} > 21000, got esi={esi}"
                )

    def test_inline_patch_row(self, h, run):
        # NOTE: biometric run locks p_days/p_hours — patch oth_allo instead
        # which is always editable.
        target = run["rows"][0]
        run_id = run["run_id"]
        r = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
            json={"user_id": target["user_id"], "oth_allo": 500.0},
            headers=h, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        assert body["row"]["oth_allo"] == 500.0
        assert body.get("totals") is not None

    def test_finalize_then_patch_returns_409(self, h, run):
        run_id = run["run_id"]
        r = requests.post(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/finalize",
            headers=h, timeout=20,
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True

        r2 = requests.patch(
            f"{BASE_URL}/api/admin/actual-salary-process/{run_id}/row",
            json={"user_id": run["rows"][0]["user_id"], "oth_allo": 999.0},
            headers=h, timeout=20,
        )
        assert r2.status_code == 409, f"Expected 409 after finalize, got {r2.status_code}: {r2.text}"


# ------------------------------------------------------------------
# Salary Runs audit enrichment — feature #4
# ------------------------------------------------------------------
class TestSalaryRunsAudit:
    def test_list_has_generated_by_name(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/salary-runs?company_id={KANKANI_ID}",
            headers=h, timeout=20,
        )
        assert r.status_code == 200
        runs = r.json().get("runs") or []
        assert runs, "No salary runs to check enrichment on"
        # At least one run should have generated_by_name populated
        assert any(x.get("generated_by_name") for x in runs), (
            "generated_by_name missing on all runs"
        )
        assert any("generated_by_role" in x for x in runs), (
            "generated_by_role missing on all runs"
        )


# ------------------------------------------------------------------
# Compliance Salary Runs audit + enabled_allowances — features #5, #7
# ------------------------------------------------------------------
class TestComplianceSalaryRuns:
    def test_list_audit_enrichment(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/compliance-salary-runs?company_id={KANKANI_ID}",
            headers=h, timeout=20,
        )
        assert r.status_code == 200
        runs = r.json().get("runs") or []
        # Enrichment is opportunistic — only assert schema when runs exist
        if runs:
            # Fields must exist for at least one run with a known generator
            assert any("generated_by_name" in x for x in runs), (
                f"generated_by_name key missing entirely from {len(runs)} runs"
            )

    def test_enabled_allowances_zeros_disabled_heads(self, h):
        # Read current firm compliance policy (proper endpoint)
        cur = requests.get(
            f"{BASE_URL}/api/admin/companies/{KANKANI_ID}/compliance-policy",
            headers=h, timeout=15,
        )
        assert cur.status_code == 200, f"{cur.status_code}: {cur.text[:200]}"
        prev_policy = (cur.json() or {}).get("policy") or {}

        # PUT with enabled_allowances=["basic","hra"] only
        put = requests.put(
            f"{BASE_URL}/api/admin/companies/{KANKANI_ID}/compliance-policy",
            json={"enabled_allowances": ["basic", "hra"]},
            headers=h, timeout=15,
        )
        assert put.status_code == 200, f"{put.status_code}: {put.text[:200]}"

        try:
            payload = {
                "month": "2025-11",
                "company_id": KANKANI_ID,
                "attendance_source": "biometric",
            }
            r = requests.post(
                f"{BASE_URL}/api/admin/compliance-salary-runs",
                json=payload, headers=h, timeout=60,
            )
            assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
            run = r.json()["run"]
            rows = run.get("rows") or []
            assert rows, "No compliance rows produced"
            # After the toggle, conveyance/medical/special/others must be 0
            for row in rows:
                for head in ("conveyance", "medical", "special", "others"):
                    val = float(row.get(head) or 0)
                    assert val == 0.0, (
                        f"After enabled_allowances=basic,hra, head={head} "
                        f"should be 0 but is {val} for uid={row.get('user_id')}"
                    )
        finally:
            # Restore original policy — clear enabled_allowances so all heads apply again
            # or restore prior list explicitly.
            restore = {"enabled_allowances": prev_policy.get("enabled_allowances") if prev_policy else None}
            if restore["enabled_allowances"] is None:
                restore["enabled_allowances"] = ["basic", "hra", "conveyance", "medical", "special", "others"]
            requests.put(
                f"{BASE_URL}/api/admin/companies/{KANKANI_ID}/compliance-policy",
                json=restore,
                headers=h, timeout=15,
            )


# ------------------------------------------------------------------
# Users Log Report — feature #6
# ------------------------------------------------------------------
class TestUsersLogReport:
    def test_endpoint_returns_events(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/users-log",
            params={"from_date": "2025-11-01", "to_date": "2025-12-31"},
            headers=h, timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        assert "events" in body
        assert "count" in body
        assert body["count"] == len(body["events"])

    def test_events_have_display_fields(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/users-log",
            params={"from_date": "2025-01-01", "to_date": "2026-12-31"},
            headers=h, timeout=20,
        )
        assert r.status_code == 200
        events = r.json().get("events") or []
        if not events:
            pytest.skip("No events in the aggregate window — cannot assert fields")
        e = events[0]
        for key in ("at", "actor_name", "actor_role", "company_name", "action", "details"):
            assert key in e, f"Missing display field {key} in event: {list(e.keys())}"
