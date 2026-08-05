"""Iter 499 backend tests
Covers:
1. Employee-groups group_id fix
2. Portal priority tasks endpoint
3. Factory & Boiler Annual Return endpoints (JSON + PDF + XLSX)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "Missing EXPO_PUBLIC_BACKEND_URL/EXPO_BACKEND_URL env"
BASE_URL = BASE_URL.rstrip("/")

CID = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin-password-login",
        json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("session_token") or r.json().get("access_token")
    assert tok, f"no token: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ------------ 1. Employee Groups group_id ---------------
class TestEmployeeGroups:
    def test_all_groups_have_group_id(self, h):
        r = requests.get(f"{BASE_URL}/api/admin/employee-groups?company_id={CID}", headers=h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        groups = data.get("groups") or data.get("items") or (data if isinstance(data, list) else [])
        assert len(groups) > 0, f"no groups: {data}"
        print(f"Got {len(groups)} groups")
        for g in groups:
            gid = g.get("group_id") or g.get("id")
            assert gid, f"missing group_id: {g}"
        # Expect at least LABOUR + STAFF names
        names = {(g.get("name") or "").upper() for g in groups}
        assert "LABOUR" in names or any("LABOUR" in n for n in names), f"no LABOUR: {names}"
        assert "STAFF" in names or any("STAFF" in n for n in names), f"no STAFF: {names}"


# ------------ 2. Portal Priority Tasks ---------------
class TestPriorityTasks:
    def test_priority_tasks_endpoint(self, h):
        r = requests.get(f"{BASE_URL}/api/admin/portal-tasks/priority", headers=h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        assert isinstance(items, list), f"expected list, got {type(items)}: {data}"
        assert len(items) <= 8, f"max 8, got {len(items)}"
        # Ensure no done/low
        for it in items:
            status = (it.get("status") or "").lower()
            prio = (it.get("priority") or "").lower()
            assert status != "done", f"done task returned: {it}"
            assert prio != "low", f"low priority returned: {it}"
        print(f"priority items: {len(items)}")

    def test_priority_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/portal-tasks/priority", timeout=15)
        assert r.status_code in (401, 403), f"expected auth error, got {r.status_code}"


# ------------ 3. Factory & Boiler Annual Return ---------------
class TestFactoryReturn:
    def test_json_combined(self, h):
        r = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026", headers=h, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("year", "source", "firm", "monthly", "summary", "employees"):
            assert k in data, f"missing key {k}: {list(data.keys())}"
        assert isinstance(data["monthly"], list) and len(data["monthly"]) >= 1, f"monthly must have at least 1 row: got {len(data['monthly'])}"
        assert "employees_total" in data["summary"], f"summary keys: {list(data['summary'].keys())}"
        print("combined keys:", list(data.keys()), "employees_total=", data["summary"].get("employees_total"))

    def test_json_current_and_legacy(self, h):
        r_cur = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026?source=current", headers=h, timeout=60)
        r_leg = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026?source=legacy", headers=h, timeout=60)
        r_comb = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026?source=combined", headers=h, timeout=60)
        assert r_cur.status_code == 200, r_cur.text
        assert r_leg.status_code == 200, r_leg.text
        assert r_comb.status_code == 200, r_comb.text
        def et(d):
            j = d.json()
            return (j.get("summary") or {}).get("employees_total") or j.get("employees_total") or 0
        cur = et(r_cur)
        comb = et(r_comb)
        print(f"employees_total current={cur} combined={comb}")
        assert comb >= cur, f"combined ({comb}) should be >= current ({cur})"

    def test_put_details_and_persist(self, h):
        payload = {
            "factory_license_no": "RJ/FACT/1234",
            "factory_name": "Kankani Enterprises",
            "occupier_name": "Prakash Kankani",
        }
        r = requests.put(
            f"{BASE_URL}/api/admin/factory-return/details/{CID}",
            json=payload, headers=h, timeout=30,
        )
        assert r.status_code == 200, r.text
        # GET back
        r2 = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026", headers=h, timeout=30)
        assert r2.status_code == 200
        j = r2.json()
        det = j.get("particulars") or j.get("details") or j
        # search recursively for license
        text = str(j)
        assert "RJ/FACT/1234" in text, f"license not persisted: {det}"

    def test_pdf_factory(self, h):
        r = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026.pdf", headers=h, timeout=90)
        assert r.status_code == 200, r.text[:400]
        ctype = r.headers.get("content-type", "")
        assert "pdf" in ctype.lower(), f"bad ctype: {ctype}"
        assert r.content[:4] == b"%PDF", "not a PDF magic"
        print(f"factory pdf {len(r.content)} bytes")

    def test_pdf_boiler(self, h):
        r = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026/boiler.pdf", headers=h, timeout=90)
        assert r.status_code == 200, r.text[:400]
        ctype = r.headers.get("content-type", "")
        assert "pdf" in ctype.lower(), f"bad ctype: {ctype}"
        assert r.content[:4] == b"%PDF", "not a PDF magic"
        print(f"boiler pdf {len(r.content)} bytes")

    def test_xlsx(self, h):
        r = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026.xlsx", headers=h, timeout=90)
        assert r.status_code == 200, r.text[:400]
        ctype = r.headers.get("content-type", "")
        assert "sheet" in ctype.lower() or "excel" in ctype.lower() or "octet-stream" in ctype.lower(), f"bad ctype: {ctype}"
        # xlsx files begin with PK zip magic
        assert r.content[:2] == b"PK", "not a ZIP/XLSX magic"
        print(f"xlsx {len(r.content)} bytes")

    def test_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026", timeout=15)
        assert r.status_code in (401, 403)
        r2 = requests.get(f"{BASE_URL}/api/admin/factory-return/{CID}/2026.pdf", timeout=15)
        assert r2.status_code in (401, 403)


# ------------ 4. Attendance grid group filter (regression) ---------------
class TestAttendanceGroupFilter:
    def test_grid_all_returns_all(self, h):
        r = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{CID}/2026-07",
            headers=h, timeout=60,
        )
        assert r.status_code == 200, r.text[:400]
        j = r.json()
        emps = j.get("employees") or j.get("rows") or j.get("items") or []
        print(f"grid ALL: {len(emps)} employees")
        assert len(emps) >= 100, f"expected ~127, got {len(emps)}"

    def test_grid_staff_only(self, h):
        # find STAFF group_id
        r = requests.get(f"{BASE_URL}/api/admin/employee-groups?company_id={CID}", headers=h, timeout=30)
        groups = r.json().get("groups") or r.json().get("items") or []
        staff = next((g for g in groups if (g.get("name") or "").upper() == "STAFF"), None)
        assert staff, f"no STAFF group: {[g.get('name') for g in groups]}"
        gid = staff.get("group_id") or staff.get("id")
        r2 = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{CID}/2026-07",
            params={"group_id": gid},
            headers=h, timeout=60,
        )
        assert r2.status_code == 200, r2.text[:400]
        j = r2.json()
        emps = j.get("employees") or j.get("rows") or j.get("items") or []
        print(f"grid STAFF ({gid}): {len(emps)} employees")
        assert 5 <= len(emps) <= 30, f"expected ~16 STAFF, got {len(emps)}"

    def test_grid_labour_only(self, h):
        r = requests.get(f"{BASE_URL}/api/admin/employee-groups?company_id={CID}", headers=h, timeout=30)
        groups = r.json().get("groups") or r.json().get("items") or []
        lab = next((g for g in groups if (g.get("name") or "").upper() == "LABOUR"), None)
        assert lab, f"no LABOUR group"
        gid = lab.get("group_id") or lab.get("id")
        r2 = requests.get(
            f"{BASE_URL}/api/admin/attendance/monthly-grid/{CID}/2026-07",
            params={"group_id": gid},
            headers=h, timeout=60,
        )
        assert r2.status_code == 200
        emps = r2.json().get("employees") or []
        print(f"grid LABOUR ({gid}): {len(emps)} employees")
        assert 90 <= len(emps) <= 120, f"expected ~108, got {len(emps)}"
