"""
Iter 38 — Ticket attachment (PDF/JPEG/PNG) tests.

Covers POST /api/tickets (attachment validation + persistence),
GET /api/tickets (metadata-only), GET /api/tickets/{id}/attachments/{index}
(authZ matrix), PATCH /api/tickets (regression) and legacy ticket support.

Seeded IT38_* rows are cleaned up at the end. The real super_admin PIN
fields are never touched.
"""
import base64
import io
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") \
    or os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL/EXPO_BACKEND_URL must be set"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_TAG = "IT38_"


def _tiny_pdf_b64() -> str:
    return base64.b64encode(
        b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>%%EOF"
    ).decode("ascii")


def _tiny_jpeg_b64() -> str:
    # 1x1 white JPEG generated once and hard-coded to avoid pulling PIL.
    hex_data = (
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
        "07090908080a0d0b0a0a0a0d130f0f0c111a1c1c1a181a1917201f1f1f1f1f1f1f1f"
        "1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f"
        "1f1f1f1f1f1f1fffc0000b080001000101011100ffc4001f00000105010101010101"
        "00000000000000000102030405060708090a0bffc400b510000201030302040305"
        "05040400000174020103041105122131410613516107227114328191a1082342b1"
        "c11552d1f02433627282090a161718191a25262728292a3435363738393a434445"
        "464748494a535455565758595a636465666768696a737475767778797a83848586"
        "8788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3"
        "c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7"
        "f8f9faffda0008010100003f00fbffd9"
    )
    return base64.b64encode(bytes.fromhex(hex_data)).decode("ascii")


def _random_id() -> str:
    return uuid.uuid4().hex[:10]


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def seeded(mongo_db):
    """Seed two companies (A, B) with an admin + employee each, plus a
    super_admin (dedicated for this test — NOT the real sksharma one).
    Also seeds a legacy ticket (no `attachments` key) for employeeA1.

    Returns a dict with entities + bearer tokens.
    """
    db = mongo_db
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=1)

    # Companies
    comp_a = {
        "company_id": f"co_{_TAG}A_{_random_id()}",
        "company_code": f"{_TAG}A{_random_id()[:4].upper()}",
        "name": f"{_TAG}Company A",
        "created_at": now.isoformat(),
    }
    comp_b = {
        "company_id": f"co_{_TAG}B_{_random_id()}",
        "company_code": f"{_TAG}B{_random_id()[:4].upper()}",
        "name": f"{_TAG}Company B",
        "created_at": now.isoformat(),
    }
    db.companies.insert_many([comp_a, comp_b])

    def _mk_user(role, company_id, tag):
        uid = f"user_{_TAG}{tag}_{_random_id()}"
        email = f"{_TAG.lower()}{tag.lower()}_{_random_id()[:6]}@test.local"
        db.users.insert_one({
            "user_id": uid,
            "email": email,
            "phone": None,
            "name": f"{_TAG}{tag}",
            "picture": None,
            "role": role,
            "company_id": company_id,
            "onboarded": True,
            "created_at": now.isoformat(),
        })
        token = f"otp_{_TAG}{tag}_{uuid.uuid4().hex}"
        db.user_sessions.insert_one({
            "session_token": token,
            "user_id": uid,
            "expires_at": exp,
            "created_at": now,
            "auth_method": "seed",
        })
        return {"user_id": uid, "email": email, "role": role,
                "company_id": company_id, "token": token}

    empA1 = _mk_user("employee", comp_a["company_id"], "EMPA1")
    empA2 = _mk_user("employee", comp_a["company_id"], "EMPA2")
    empB1 = _mk_user("employee", comp_b["company_id"], "EMPB1")
    admA = _mk_user("company_admin", comp_a["company_id"], "ADMA")
    admB = _mk_user("company_admin", comp_b["company_id"], "ADMB")
    superU = _mk_user("super_admin", None, "SUPER")

    # Legacy ticket for empA1 (no `attachments` key at all).
    legacy_ticket_id = f"tkt_{_TAG}legacy_{_random_id()}"
    db.tickets.insert_one({
        "ticket_id": legacy_ticket_id,
        "user_id": empA1["user_id"],
        "company_id": empA1["company_id"],
        "user_name": empA1["email"],
        "user_email": empA1["email"],
        "category": "hr",
        "subject": f"{_TAG}Legacy",
        "description": "no attachments field",
        "status": "open",
        "admin_reply": None,
        "created_at": now.isoformat(),
    })

    data = {
        "empA1": empA1, "empA2": empA2, "empB1": empB1,
        "admA": admA, "admB": admB, "super": superU,
        "compA": comp_a, "compB": comp_b,
        "legacy_ticket_id": legacy_ticket_id,
    }
    yield data

    # ---- Teardown ----
    user_ids = [u["user_id"] for u in (empA1, empA2, empB1, admA, admB, superU)]
    tokens = [u["token"] for u in (empA1, empA2, empB1, admA, admB, superU)]
    db.tickets.delete_many({"user_id": {"$in": user_ids}})
    db.tickets.delete_many({"ticket_id": legacy_ticket_id})
    db.tickets.delete_many({"subject": {"$regex": f"^{_TAG}"}})
    db.user_sessions.delete_many({"session_token": {"$in": tokens}})
    db.users.delete_many({"user_id": {"$in": user_ids}})
    db.companies.delete_many({"company_id": {"$in": [comp_a["company_id"], comp_b["company_id"]]}})


def _hdr(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# 1. Create ticket — happy path with mixed attachments
# ---------------------------------------------------------------------------
class TestCreateTicketAttachments:
    def test_create_with_pdf_jpeg_png(self, seeded):
        pdf_b64 = _tiny_pdf_b64()
        jpg_b64 = _tiny_jpeg_b64()
        png_b64 = base64.b64encode(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f"
                "15c4890000000d49444154789c62000100000005000173a1e6b0000000004"
                "9454e44ae426082"
            )
        ).decode("ascii")

        payload = {
            "category": "it",
            "subject": f"{_TAG}Happy",
            "description": "with 3 attachments",
            "attachments": [
                {"name": "doc.pdf", "mime": "application/pdf", "data_base64": pdf_b64},
                {"name": "pic.jpg", "mime": "image/jpeg", "data_base64": jpg_b64},
                {"name": "img.png", "mime": "image/png", "data_base64": png_b64},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subject"] == f"{_TAG}Happy"
        assert body["status"] == "open"
        assert len(body["attachments"]) == 3
        for i, att in enumerate(body["attachments"]):
            assert att["index"] == i
            assert att["mime"] in {"application/pdf", "image/jpeg", "image/png"}
            assert att["size"] > 0
            assert "data_base64" not in att, "list/create response must not leak base64"
        seeded["primary_ticket_id"] = body["ticket_id"]

    def test_data_url_prefix_stripped(self, seeded):
        pdf_b64 = _tiny_pdf_b64()
        payload = {
            "category": "hr",
            "subject": f"{_TAG}DataURL",
            "description": "data-URL prefix should be stripped",
            "attachments": [
                {"name": "doc.pdf", "mime": "application/pdf",
                 "data_base64": f"data:application/pdf;base64,{pdf_b64}"},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["attachments"][0]["size"] > 0
        # verify persisted body decodes cleanly
        ticket_id = body["ticket_id"]
        g = requests.get(
            f"{BASE_URL}/api/tickets/{ticket_id}/attachments/0",
            headers=_hdr(seeded["empA1"]["token"]), timeout=30,
        )
        assert g.status_code == 200, g.text
        assert base64.b64decode(g.json()["data_base64"]).startswith(b"%PDF")

    def test_no_attachments_is_allowed(self, seeded):
        payload = {
            "category": "other",
            "subject": f"{_TAG}NoAtt",
            "description": "no files at all",
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA2"]["token"]), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["attachments"] == []


# ---------------------------------------------------------------------------
# 2. Validation failures
# ---------------------------------------------------------------------------
class TestCreateTicketValidation:
    def test_reject_more_than_5_files(self, seeded):
        pdf_b64 = _tiny_pdf_b64()
        payload = {
            "category": "hr",
            "subject": f"{_TAG}6files",
            "description": "6 attachments",
            "attachments": [
                {"name": f"f{i}.pdf", "mime": "application/pdf", "data_base64": pdf_b64}
                for i in range(6)
            ],
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 400, r.text
        assert "at most 5" in r.json()["detail"].lower()

    def test_reject_oversize_file(self, seeded):
        # 5 MB + 1 byte, all zeros
        big = base64.b64encode(b"\x00" * (5 * 1024 * 1024 + 1)).decode("ascii")
        payload = {
            "category": "hr",
            "subject": f"{_TAG}Big",
            "description": "too big",
            "attachments": [
                {"name": "big.pdf", "mime": "application/pdf", "data_base64": big},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA1"]["token"]), timeout=60)
        assert r.status_code == 400, r.text
        detail = r.json()["detail"].lower()
        assert "maximum" in detail or "mb" in detail

    def test_reject_bad_base64(self, seeded):
        payload = {
            "category": "hr",
            "subject": f"{_TAG}BadB64",
            "description": "invalid base64",
            "attachments": [
                {"name": "corrupt.pdf", "mime": "application/pdf",
                 "data_base64": "not valid base64!!!@@@"},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 400, r.text
        assert "not valid base64" in r.json()["detail"].lower()

    def test_reject_disallowed_mime(self, seeded):
        payload = {
            "category": "hr",
            "subject": f"{_TAG}BadMime",
            "description": "text/plain not allowed",
            "attachments": [
                {"name": "notes.txt", "mime": "text/plain",
                 "data_base64": base64.b64encode(b"hello").decode()},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# 3. Persistence — the base64 blob really is stored on the ticket doc.
# ---------------------------------------------------------------------------
class TestPersistence:
    def test_all_bodies_persist_in_db(self, seeded, mongo_db):
        pdf_b64 = _tiny_pdf_b64()
        payload = {
            "category": "payroll",
            "subject": f"{_TAG}Persist",
            "description": "persistence test",
            "attachments": [
                {"name": "a.pdf", "mime": "application/pdf", "data_base64": pdf_b64},
                {"name": "b.pdf", "mime": "application/pdf", "data_base64": pdf_b64},
            ],
        }
        r = requests.post(f"{BASE_URL}/api/tickets", json=payload,
                          headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 200
        tid = r.json()["ticket_id"]
        doc = mongo_db.tickets.find_one({"ticket_id": tid})
        assert doc is not None
        assert len(doc["attachments"]) == 2
        for a in doc["attachments"]:
            assert a["data_base64"], "raw base64 must be persisted on the doc"
            assert base64.b64decode(a["data_base64"]).startswith(b"%PDF")


# ---------------------------------------------------------------------------
# 4. GET /api/tickets — metadata only, both scopes
# ---------------------------------------------------------------------------
class TestListTickets:
    def test_list_mine_no_base64(self, seeded):
        r = requests.get(f"{BASE_URL}/api/tickets?scope=mine",
                         headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 200, r.text
        tickets = r.json()["tickets"]
        assert len(tickets) >= 1
        for t in tickets:
            for a in t.get("attachments", []):
                assert "data_base64" not in a, "list must never include base64"
                assert set(a.keys()) >= {"index", "name", "mime", "size"} \
                    or set(a.keys()) == {"index", "name", "mime", "size"}

    def test_list_all_admin_no_base64(self, seeded):
        r = requests.get(f"{BASE_URL}/api/tickets?scope=all",
                         headers=_hdr(seeded["admA"]["token"]), timeout=30)
        assert r.status_code == 200, r.text
        tickets = r.json()["tickets"]
        # admA should only see compA tickets
        for t in tickets:
            assert t["company_id"] == seeded["compA"]["company_id"]
            for a in t.get("attachments", []):
                assert "data_base64" not in a

    def test_list_all_super_admin(self, seeded):
        r = requests.get(f"{BASE_URL}/api/tickets?scope=all",
                         headers=_hdr(seeded["super"]["token"]), timeout=30)
        assert r.status_code == 200
        tickets = r.json()["tickets"]
        # super_admin sees every company
        company_ids = {t.get("company_id") for t in tickets}
        assert seeded["compA"]["company_id"] in company_ids

    def test_legacy_ticket_returns_empty_attachments(self, seeded):
        r = requests.get(f"{BASE_URL}/api/tickets?scope=mine",
                         headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert r.status_code == 200
        legacy = next(t for t in r.json()["tickets"]
                      if t["ticket_id"] == seeded["legacy_ticket_id"])
        assert legacy["attachments"] == [], \
            "legacy ticket without attachments field must surface as []"


# ---------------------------------------------------------------------------
# 5. GET attachment — authZ matrix + 404 handling
# ---------------------------------------------------------------------------
class TestAttachmentAuthZ:
    @pytest.fixture(scope="class")
    def ticket_with_att(self, seeded):
        pdf_b64 = _tiny_pdf_b64()
        r = requests.post(
            f"{BASE_URL}/api/tickets",
            json={
                "category": "it",
                "subject": f"{_TAG}AuthZ",
                "description": "authz matrix",
                "attachments": [
                    {"name": "doc.pdf", "mime": "application/pdf",
                     "data_base64": pdf_b64},
                ],
            },
            headers=_hdr(seeded["empA1"]["token"]),
            timeout=30,
        )
        assert r.status_code == 200
        return r.json()["ticket_id"]

    def test_owner_employee_can_view(self, seeded, ticket_with_att):
        r = requests.get(
            f"{BASE_URL}/api/tickets/{ticket_with_att}/attachments/0",
            headers=_hdr(seeded["empA1"]["token"]), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mime"] == "application/pdf"
        assert base64.b64decode(body["data_base64"]).startswith(b"%PDF")

    def test_other_employee_same_company_forbidden(self, seeded, ticket_with_att):
        r = requests.get(
            f"{BASE_URL}/api/tickets/{ticket_with_att}/attachments/0",
            headers=_hdr(seeded["empA2"]["token"]), timeout=30,
        )
        assert r.status_code == 403, r.text

    def test_company_admin_in_same_company_can_view(self, seeded, ticket_with_att):
        r = requests.get(
            f"{BASE_URL}/api/tickets/{ticket_with_att}/attachments/0",
            headers=_hdr(seeded["admA"]["token"]), timeout=30,
        )
        assert r.status_code == 200, r.text

    def test_company_admin_other_company_forbidden(self, seeded, ticket_with_att):
        r = requests.get(
            f"{BASE_URL}/api/tickets/{ticket_with_att}/attachments/0",
            headers=_hdr(seeded["admB"]["token"]), timeout=30,
        )
        assert r.status_code == 403, r.text

    def test_super_admin_can_view(self, seeded, ticket_with_att):
        r = requests.get(
            f"{BASE_URL}/api/tickets/{ticket_with_att}/attachments/0",
            headers=_hdr(seeded["super"]["token"]), timeout=30,
        )
        assert r.status_code == 200, r.text

    def test_unknown_ticket_id_404(self, seeded):
        r = requests.get(
            f"{BASE_URL}/api/tickets/tkt_nonexistent_zzz/attachments/0",
            headers=_hdr(seeded["super"]["token"]), timeout=30,
        )
        assert r.status_code == 404

    def test_out_of_range_index_404(self, seeded, ticket_with_att):
        r = requests.get(
            f"{BASE_URL}/api/tickets/{ticket_with_att}/attachments/99",
            headers=_hdr(seeded["empA1"]["token"]), timeout=30,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. PATCH regression — status update still works.
# ---------------------------------------------------------------------------
class TestPatchRegression:
    def test_status_update(self, seeded):
        # Create a fresh ticket for empA1
        r = requests.post(
            f"{BASE_URL}/api/tickets",
            json={"category": "hr", "subject": f"{_TAG}Patch",
                  "description": "patch regression"},
            headers=_hdr(seeded["empA1"]["token"]),
            timeout=30,
        )
        assert r.status_code == 200
        tid = r.json()["ticket_id"]

        # admA (same company) can patch
        p = requests.patch(
            f"{BASE_URL}/api/tickets/{tid}",
            json={"status": "in_progress", "admin_reply": "looking into it"},
            headers=_hdr(seeded["admA"]["token"]),
            timeout=30,
        )
        assert p.status_code == 200, p.text
        assert p.json()["status"] == "in_progress"
        assert p.json()["admin_reply"] == "looking into it"

        # GET verifies persistence
        g = requests.get(f"{BASE_URL}/api/tickets?scope=mine",
                         headers=_hdr(seeded["empA1"]["token"]), timeout=30)
        assert g.status_code == 200
        me = next(t for t in g.json()["tickets"] if t["ticket_id"] == tid)
        assert me["status"] == "in_progress"
