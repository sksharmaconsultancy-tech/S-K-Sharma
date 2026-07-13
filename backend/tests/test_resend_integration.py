"""In-process tests for the Resend email integration added to
POST /api/company-requests.

We do NOT hit the real Resend API. Instead we monkeypatch the `httpx.AsyncClient`
symbol imported into `server` to a fake that returns controllable responses,
and drive the FastAPI app via ASGI transport.

Covered scenarios:
    (a) Success  -> email_delivered=True, email_id populated, persisted doc
                    has email_provider='resend', email_error=None
    (b) 4xx from Resend -> endpoint still 200, email_delivered=False,
                            email_error prefixed with "http_"
    (c) Network exception (httpx.RequestError) -> endpoint still 200,
                            email_delivered=False, email_error prefixed "network:"
    (d) Missing RESEND_API_KEY -> endpoint still 200, email_delivered=False,
                            email_error == "missing_api_key_or_recipients"
    (e) HTML body IS included in payload sent to Resend
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

# Make backend importable as `server`
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server  # noqa: E402  (import after sys.path tweak)


# ---------------------------------------------------------------------------
# Fake httpx client that captures the outbound Resend request
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = text if text is not None else (
            "" if status_code < 300 else '{"error":"bad"}'
        )

    def json(self):
        return self._body


def make_fake_client(behavior):
    """behavior is a callable(url, headers, json) -> FakeResponse | raises."""
    captured = {"calls": []}

    class FakeAsyncClient:
        def __init__(self, *a, **kw):
            self.timeout = kw.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured["calls"].append(
                {"url": url, "headers": headers, "json": json}
            )
            return behavior(url, headers, json)

    return FakeAsyncClient, captured


# ---------------------------------------------------------------------------
# Fixtures: seed user + session, provide ASGI client
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def seeded_session():
    """Create an ephemeral employee user + session and yield the token.
    Cleanup after each test.
    """
    user_id = f"user_test_{uuid.uuid4().hex[:8]}"
    email = f"resend_test_{uuid.uuid4().hex[:6]}@test.local"
    token = f"testtok_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    await server.db.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": "Resend Tester",
        "role": "employee",
        "onboarded": False,
        "created_at": now.isoformat(),
    })
    await server.db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": now + timedelta(days=1),
        "created_at": now,
    })
    yield {"token": token, "user_id": user_id, "email": email}
    await server.db.user_sessions.delete_many({"session_token": token})
    await server.db.users.delete_many({"user_id": user_id})
    await server.db.company_requests.delete_many({"submitted_by_user_id": user_id})


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


REQUEST_PAYLOAD = {
    "contact_name": "TEST Contact",
    "contact_mobile": "+911234567890",
    "contact_email": "contact@test.example",
    "company_name": "TEST_ResendCo",
    "address": "1 Test Way",
    "employee_count": 25,
    "services_needed": "Payroll, Compliance",
    "notes": "auto-test",
}


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_success_path_returns_email_id_and_persists(monkeypatch, client, seeded_session):
    monkeypatch.setenv("RESEND_API_KEY", "re_fake_valid_key")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    monkeypatch.setenv("RESEND_TO_EMAIL", "sksharmaconsultancy@gmail.com")

    fake_id = f"resend_{uuid.uuid4().hex}"
    FakeCls, captured = make_fake_client(
        lambda u, h, j: FakeResponse(200, {"id": fake_id})
    )
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeCls)

    resp = await client.post(
        "/api/company-requests",
        json=REQUEST_PAYLOAD,
        headers={"Authorization": f"Bearer {seeded_session['token']}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["email_delivered"] is True
    assert data["email_id"] == fake_id
    assert isinstance(data["admin_emails"], list)
    assert "sksharmaconsultancy@gmail.com" in data["admin_emails"]

    # Outbound call to Resend was made with correct shape
    assert len(captured["calls"]) == 1
    call = captured["calls"][0]
    assert call["url"] == "https://api.resend.com/emails"
    assert call["headers"]["Authorization"] == "Bearer re_fake_valid_key"
    assert call["headers"]["Content-Type"] == "application/json"
    body = call["json"]
    assert body["subject"].startswith("New company request: TEST_ResendCo")
    assert body["to"] == ["sksharmaconsultancy@gmail.com"]
    assert body["from"].startswith("S.K. Sharma & Co. <onboarding@resend.dev>")
    assert "text" in body and "TEST_ResendCo" in body["text"]
    # (e) HTML body IS attached and comes from the formatter
    assert "html" in body
    assert "<!doctype html>" in body["html"].lower()
    assert "New company registration request" in body["html"]
    assert "TEST_ResendCo" in body["html"]

    # Persisted DB doc has the email audit fields
    doc = await server.db.company_requests.find_one(
        {"request_id": data["request_id"]}, {"_id": 0}
    )
    assert doc is not None
    assert doc["email_delivered"] is True
    assert doc["email_provider"] == "resend"
    assert doc["email_id"] == fake_id
    assert doc["email_error"] is None


# ---------------------------------------------------------------------------
# 4xx from Resend
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resend_4xx_still_returns_200(monkeypatch, client, seeded_session):
    monkeypatch.setenv("RESEND_API_KEY", "re_bad_key")
    monkeypatch.setenv("RESEND_TO_EMAIL", "sksharmaconsultancy@gmail.com")

    FakeCls, _ = make_fake_client(
        lambda u, h, j: FakeResponse(
            401,
            {"error": "invalid api key"},
            text='{"error":"invalid api key"}',
        )
    )
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeCls)

    resp = await client.post(
        "/api/company-requests",
        json=REQUEST_PAYLOAD,
        headers={"Authorization": f"Bearer {seeded_session['token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email_delivered"] is False
    assert data["email_id"] is None
    # Persisted doc
    doc = await server.db.company_requests.find_one(
        {"request_id": data["request_id"]}, {"_id": 0}
    )
    assert doc["email_delivered"] is False
    assert doc["email_provider"] == "resend"
    assert doc["email_error"] is not None
    assert doc["email_error"].startswith("http_401")


# ---------------------------------------------------------------------------
# Network exception (RequestError)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_network_exception_still_returns_200(monkeypatch, client, seeded_session):
    monkeypatch.setenv("RESEND_API_KEY", "re_any")
    monkeypatch.setenv("RESEND_TO_EMAIL", "sksharmaconsultancy@gmail.com")

    def raise_network(u, h, j):
        raise httpx.ConnectError("simulated dns failure")

    FakeCls, _ = make_fake_client(raise_network)
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeCls)

    resp = await client.post(
        "/api/company-requests",
        json=REQUEST_PAYLOAD,
        headers={"Authorization": f"Bearer {seeded_session['token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email_delivered"] is False
    doc = await server.db.company_requests.find_one(
        {"request_id": data["request_id"]}, {"_id": 0}
    )
    assert doc["email_delivered"] is False
    assert doc["email_error"] is not None
    assert doc["email_error"].startswith("network:")


# ---------------------------------------------------------------------------
# Missing RESEND_API_KEY
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_api_key_short_circuits(monkeypatch, client, seeded_session):
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("RESEND_TO_EMAIL", "sksharmaconsultancy@gmail.com")

    # Make sure no outbound call is attempted
    def should_not_be_called(u, h, j):
        raise AssertionError("Resend should not be called when API key is missing")

    FakeCls, captured = make_fake_client(should_not_be_called)
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeCls)

    resp = await client.post(
        "/api/company-requests",
        json=REQUEST_PAYLOAD,
        headers={"Authorization": f"Bearer {seeded_session['token']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email_delivered"] is False
    assert data["email_id"] is None
    assert captured["calls"] == []

    doc = await server.db.company_requests.find_one(
        {"request_id": data["request_id"]}, {"_id": 0}
    )
    assert doc["email_delivered"] is False
    assert doc["email_provider"] == "resend"
    assert doc["email_error"] == "missing_api_key_or_recipients"


# ---------------------------------------------------------------------------
# Unit test: _format_company_request_email_html
# ---------------------------------------------------------------------------
def test_html_formatter_produces_html_with_key_fields():
    req = {
        "contact_name": "Alice <script>",
        "contact_mobile": "+91-00000",
        "contact_email": "a@b.com",
        "submitted_by_email": "u@example.com",
        "company_name": "Acme & Co.",
        "address": "1 Test Way",
        "employee_count": 12,
        "services_needed": "Payroll",
        "notes": "n/a",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    html = server._format_company_request_email_html(req)
    assert "<!doctype html>" in html.lower()
    assert "New company registration request" in html
    # HTML escape must neutralise < > &
    assert "Alice &lt;script&gt;" in html
    assert "Acme &amp; Co." in html
    assert "u@example.com" in html
    # Table rows are present
    assert "Contact person" in html
    assert "Company name" in html


# ---------------------------------------------------------------------------
# Regression sanity: super_admin cannot POST /api/company-requests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_super_admin_forbidden(monkeypatch, client):
    # Create a super_admin session
    user_id = f"user_admin_{uuid.uuid4().hex[:8]}"
    token = f"admintok_{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    await server.db.users.insert_one({
        "user_id": user_id,
        "email": f"admin_{uuid.uuid4().hex[:6]}@test.local",
        "name": "Admin",
        "role": "super_admin",
        "onboarded": True,
        "created_at": now.isoformat(),
    })
    await server.db.user_sessions.insert_one({
        "session_token": token,
        "user_id": user_id,
        "expires_at": now + timedelta(days=1),
        "created_at": now,
    })
    try:
        # Make sure Resend is not actually called
        FakeCls, _ = make_fake_client(lambda u, h, j: FakeResponse(200, {"id": "x"}))
        monkeypatch.setattr(server.httpx, "AsyncClient", FakeCls)

        resp = await client.post(
            "/api/company-requests",
            json=REQUEST_PAYLOAD,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "Super admins" in resp.json().get("detail", "")
    finally:
        await server.db.user_sessions.delete_many({"session_token": token})
        await server.db.users.delete_many({"user_id": user_id})
