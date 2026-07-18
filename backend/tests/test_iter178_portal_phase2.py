"""Backend tests for Portal Dashboard Phase 2 (Iter 178).

Covers: Tasks CRUD, Tracked Documents CRUD (with bucketing),
Client Health scoring, Compliance Calendar merge + toggle,
Alerts / Notification center, role-scoping for company_admin,
and validation errors.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "https://emplo-connect-1.preview.emergentagent.com").rstrip("/")
KANKANI_CID = "cmp_527fecdd7c"


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{BASE_URL}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=15)
    assert r.status_code == 200, f"super login failed: {r.status_code} {r.text}"
    tok = r.json().get("session_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def company_token():
    """Kankani company_admin. PIN was rotated by user, so we fall back to injecting
    a test session in user_sessions if pin-login fails (per test_credentials.md line 49)."""
    r = requests.post(f"{BASE_URL}/api/auth/admin-pin-login",
                      json={"identifier": "admin@kankani.local", "pin": "1234"},
                      timeout=15)
    if r.status_code == 200:
        tok = r.json().get("session_token") or r.json().get("token")
        if tok:
            return tok
    # Fallback: inject a session directly via mongo (allowed in preview env)
    import asyncio, secrets, os as _os
    from datetime import datetime, timedelta, timezone
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    IST = timezone(timedelta(hours=5, minutes=30))

    async def _inject():
        cli = AsyncIOMotorClient(_os.environ["MONGO_URL"])
        db = cli[_os.environ["DB_NAME"]]
        u = await db.users.find_one({"email": "admin@kankani.local"},
                                    {"_id": 0, "user_id": 1})
        if not u:
            return None
        tok = "TEST_" + secrets.token_hex(16)
        await db.user_sessions.insert_one({
            "session_token": tok, "user_id": u["user_id"],
            "created_at": datetime.now(IST).isoformat(),
            "expires_at": (datetime.now(IST) + timedelta(hours=6)).isoformat(),
            "active": True,
        })
        return tok
    tok = asyncio.get_event_loop().run_until_complete(_inject()) \
        if False else asyncio.new_event_loop().run_until_complete(_inject())
    if not tok:
        pytest.skip("Could not obtain company_admin session")
    return tok


@pytest.fixture(scope="module")
def company_headers(company_token):
    return {"Authorization": f"Bearer {company_token}", "Content-Type": "application/json"}


# ============== TASKS ==============

class TestPortalTasks:
    created_id = None

    def test_list_tasks_super(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/portal-tasks", headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tasks" in data and "counts" in data
        for k in ("open", "in_progress", "done", "overdue"):
            assert k in data["counts"]

    def test_create_task_success(self, super_headers):
        payload = {"title": "TEST_iter178 backend task",
                   "description": "auto-created by pytest",
                   "due_date": "2026-06-30",
                   "priority": "high",
                   "company_id": KANKANI_CID}
        r = requests.post(f"{BASE_URL}/api/admin/portal-tasks",
                          json=payload, headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()["task"]
        assert t["title"] == payload["title"]
        assert t["priority"] == "high"
        assert t["status"] == "open"
        assert t["company_id"] == KANKANI_CID
        assert t["task_id"].startswith("task_")
        TestPortalTasks.created_id = t["task_id"]

    def test_create_task_missing_title(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/portal-tasks",
                          json={"title": "", "priority": "medium"},
                          headers=super_headers, timeout=15)
        assert r.status_code == 400, r.text

    def test_create_task_invalid_priority(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/portal-tasks",
                          json={"title": "TEST_bad_prio", "priority": "urgent"},
                          headers=super_headers, timeout=15)
        assert r.status_code == 400, r.text

    def test_status_transition_and_completed_at(self, super_headers):
        tid = TestPortalTasks.created_id
        assert tid
        # open -> in_progress
        r = requests.patch(f"{BASE_URL}/api/admin/portal-tasks/{tid}",
                           json={"status": "in_progress"}, headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["task"]["status"] == "in_progress"
        # in_progress -> done, must set completed_at
        r = requests.patch(f"{BASE_URL}/api/admin/portal-tasks/{tid}",
                           json={"status": "done"}, headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()["task"]
        assert t["status"] == "done"
        assert t.get("completed_at")

    def test_invalid_status(self, super_headers):
        tid = TestPortalTasks.created_id
        r = requests.patch(f"{BASE_URL}/api/admin/portal-tasks/{tid}",
                           json={"status": "bogus"}, headers=super_headers, timeout=15)
        assert r.status_code == 400

    def test_delete_task(self, super_headers):
        tid = TestPortalTasks.created_id
        r = requests.delete(f"{BASE_URL}/api/admin/portal-tasks/{tid}",
                            headers=super_headers, timeout=15)
        assert r.status_code == 200
        # verify gone by trying to patch it -> 404
        r2 = requests.patch(f"{BASE_URL}/api/admin/portal-tasks/{tid}",
                            json={"status": "open"}, headers=super_headers, timeout=15)
        assert r2.status_code == 404


# ============== TRACKED DOCUMENTS ==============

class TestTrackedDocuments:
    created_id = None

    def test_list(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/tracked-documents",
                         headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("expired", "critical", "warning", "upcoming", "ok"):
            assert k in d["buckets"]
        assert "today" in d

    def test_create_success(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/tracked-documents",
                          json={"title": "TEST_iter178 factory license",
                                "doc_type": "license",
                                "expiry_date": "2026-12-31",
                                "company_id": KANKANI_CID,
                                "remind_days": 30},
                          headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        doc = r.json()["document"]
        assert doc["title"].startswith("TEST_")
        assert doc["expiry_date"] == "2026-12-31"
        assert doc["tdoc_id"].startswith("tdoc_")
        TestTrackedDocuments.created_id = doc["tdoc_id"]

    def test_create_bad_expiry(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/tracked-documents",
                          json={"title": "TEST_bad_expiry",
                                "doc_type": "license",
                                "expiry_date": "31-12-2026"},
                          headers=super_headers, timeout=15)
        assert r.status_code == 400

    def test_create_missing_title(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/tracked-documents",
                          json={"title": "", "doc_type": "license",
                                "expiry_date": "2026-12-31"},
                          headers=super_headers, timeout=15)
        assert r.status_code == 400

    def test_create_bad_doc_type(self, super_headers):
        r = requests.post(f"{BASE_URL}/api/admin/tracked-documents",
                          json={"title": "TEST_bad_type",
                                "doc_type": "gibberish",
                                "expiry_date": "2026-12-31"},
                          headers=super_headers, timeout=15)
        assert r.status_code == 400

    def test_bucket_and_days_left(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/tracked-documents",
                         headers=super_headers, timeout=15)
        docs = r.json()["documents"]
        ours = [d for d in docs if d["tdoc_id"] == TestTrackedDocuments.created_id]
        assert ours, "created doc must appear in list"
        d = ours[0]
        assert d["bucket"] in ("expired", "critical", "warning", "upcoming", "ok")
        assert isinstance(d["days_left"], int)

    def test_patch(self, super_headers):
        tid = TestTrackedDocuments.created_id
        r = requests.patch(f"{BASE_URL}/api/admin/tracked-documents/{tid}",
                           json={"notes": "iter178 patched"},
                           headers=super_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["document"]["notes"] == "iter178 patched"

    def test_delete(self, super_headers):
        tid = TestTrackedDocuments.created_id
        r = requests.delete(f"{BASE_URL}/api/admin/tracked-documents/{tid}",
                            headers=super_headers, timeout=15)
        assert r.status_code == 200


# ============== CLIENT HEALTH ==============

class TestClientHealth:
    def test_client_health(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/portal-dashboard/client-health",
                         headers=super_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "clients" in d and "month" in d
        if d["clients"]:
            c = d["clients"][0]
            assert 0 <= c["score"] <= 100
            assert c["grade"] in ("A", "B", "C", "D")
            assert isinstance(c["factors"], list) and len(c["factors"]) == 6
            labels = [f["label"] for f in c["factors"]]
            # Sanity — payroll and attendance factors present
            assert any("Payroll" in x for x in labels)
            assert any("Attendance" in x for x in labels)


# ============== CALENDAR ==============

class TestCalendar:
    def test_calendar_month(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/portal-dashboard/calendar?month=2026-06",
                         headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["month"] == "2026-06"
        assert "events" in d and "today" in d
        # 5 statutory items must be present
        stat = [e for e in d["events"] if e["type"] == "statutory"]
        assert len(stat) == 5
        keys = {e["key"] for e in stat}
        assert {"tds", "pf", "esic", "pt", "pf_return"}.issubset(keys)

    def test_toggle_on_then_off(self, super_headers):
        # toggle first time -> done True
        r1 = requests.post(f"{BASE_URL}/api/admin/portal-dashboard/calendar/toggle",
                           json={"month": "2026-05", "item_key": "tds"},
                           headers=super_headers, timeout=15)
        assert r1.status_code == 200
        first = r1.json()["done"]
        # toggle again -> flipped
        r2 = requests.post(f"{BASE_URL}/api/admin/portal-dashboard/calendar/toggle",
                           json={"month": "2026-05", "item_key": "tds"},
                           headers=super_headers, timeout=15)
        assert r2.status_code == 200
        second = r2.json()["done"]
        assert first != second, "toggle must flip state"
        # If we ended up with done=True, toggle once more to leave clean state
        if second:
            requests.post(f"{BASE_URL}/api/admin/portal-dashboard/calendar/toggle",
                          json={"month": "2026-05", "item_key": "tds"},
                          headers=super_headers, timeout=15)


# ============== ALERTS ==============

class TestAlerts:
    def test_alerts(self, super_headers):
        r = requests.get(f"{BASE_URL}/api/admin/portal-dashboard/alerts",
                         headers=super_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "alerts" in d and "recent_notifications" in d
        assert "generated_at" in d
        # each alert has required fields
        for a in d["alerts"]:
            assert "severity" in a and a["severity"] in ("critical", "warning", "info")
            assert "title" in a


# ============== ROLE SCOPING ==============

class TestRoleScoping:
    def test_company_admin_scoped_tasks(self, company_headers):
        # create a super-admin task for a different firm should not be visible.
        # Just check that all tasks returned belong to Kankani only.
        r = requests.get(f"{BASE_URL}/api/admin/portal-tasks",
                         headers=company_headers, timeout=15)
        assert r.status_code == 200
        for t in r.json()["tasks"]:
            # company_id could be None if none was set, but scope logic forces it
            assert t.get("company_id") == KANKANI_CID, \
                f"Task leaked from another firm: {t.get('company_id')}"

    def test_company_admin_scoped_docs(self, company_headers):
        r = requests.get(f"{BASE_URL}/api/admin/tracked-documents",
                         headers=company_headers, timeout=15)
        assert r.status_code == 200
        for d in r.json()["documents"]:
            assert d.get("company_id") == KANKANI_CID

    def test_company_admin_creates_task_locked_to_firm(self, company_headers):
        # attempt to create a task for a different company_id — should be forced to Kankani
        r = requests.post(f"{BASE_URL}/api/admin/portal-tasks",
                          json={"title": "TEST_scoping ", "company_id": "cmp_someother",
                                "priority": "low"},
                          headers=company_headers, timeout=15)
        assert r.status_code == 200
        t = r.json()["task"]
        assert t["company_id"] == KANKANI_CID
        # cleanup
        requests.delete(f"{BASE_URL}/api/admin/portal-tasks/{t['task_id']}",
                        headers=company_headers, timeout=15)


# ============== AUTH GUARDS ==============

class TestAuthGuards:
    def test_no_auth_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/portal-tasks", timeout=10)
        assert r.status_code in (401, 403), r.text

    def test_bad_token_401(self):
        r = requests.get(f"{BASE_URL}/api/admin/portal-tasks",
                         headers={"Authorization": "Bearer NOT_A_TOKEN"}, timeout=10)
        assert r.status_code in (401, 403)
