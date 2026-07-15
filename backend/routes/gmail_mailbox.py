"""Iter 100 — Embedded Gmail mailbox for the Super Admin.

OAuth2 (offline access + refresh token) against Google, Gmail REST v1.
Credentials: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GMAIL_REDIRECT_URI
in backend/.env. The refresh token is stored per-user in ``gmail_accounts``.

Endpoints (super_admin only, except the OAuth callback which is
identified by the ``state`` parameter):
  * GET  /gmail/auth-url          → { auth_url }
  * GET  /gmail/oauth/callback    → browser redirect target (code exchange)
  * GET  /gmail/status            → { connected, email }
  * POST /gmail/disconnect
  * GET  /gmail/messages?q=&page_token=&label=INBOX
  * GET  /gmail/messages/{msg_id}
  * POST /gmail/send              → { to, subject, body, thread_id?, in_reply_to? }
"""
import base64
import os
import time
import uuid
from email.mime.text import MIMEText
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
)

router = APIRouter(prefix="/api", tags=["gmail"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"

_access_cache: dict = {}  # user_id -> {"token": str, "exp": epoch}


# ---------------------------------------------------------------------------
# SMTP/IMAP fallback — user directive: the Mailbox connects automatically
# using the credentials already saved in Email SMTP & Notifications, no
# Google OAuth required. Reading uses IMAP (same app-password works for
# Gmail), sending uses the shared SMTP sender.
# ---------------------------------------------------------------------------

async def _smtp_settings() -> Optional[dict]:
    doc = await db.smtp_settings.find_one({"_singleton": True}, {"_id": 0})
    if doc and doc.get("enabled") and doc.get("username") and doc.get("password"):
        return doc
    return None


def _imap_host(settings: dict) -> tuple:
    host = (settings.get("imap_host") or "").strip()
    if not host:
        sh = (settings.get("host") or "").strip().lower()
        if "gmail" in sh:
            host = "imap.gmail.com"
        elif sh.startswith("smtp."):
            host = "imap." + sh[5:]
        else:
            host = sh
    return host, int(settings.get("imap_port") or 993)


def _decode_hdr(raw) -> str:
    from email.header import decode_header
    try:
        parts = decode_header(raw or "")
        out = ""
        for txt, enc in parts:
            out += txt.decode(enc or "utf-8", "replace") if isinstance(txt, bytes) else str(txt)
        return out
    except Exception:
        return str(raw or "")


def _imap_connect(settings: dict):
    import imaplib
    host, port = _imap_host(settings)
    box = imaplib.IMAP4_SSL(host, port)
    box.login(settings["username"], settings["password"])
    return box


def _imap_select(box, label: str) -> None:
    lab = (label or "INBOX").upper()
    if lab == "SENT":
        for cand in ('"[Gmail]/Sent Mail"', "Sent", "INBOX.Sent"):
            try:
                if box.select(cand)[0] == "OK":
                    return
            except Exception:
                continue
    if lab == "SPAM":
        for cand in ('"[Gmail]/Spam"', "Spam", "Junk", "INBOX.Spam"):
            try:
                if box.select(cand)[0] == "OK":
                    return
            except Exception:
                continue
    box.select("INBOX")


def _imap_list_sync(settings: dict, label: str, q: Optional[str], limit: int = 25) -> list:
    import email as _email
    box = _imap_connect(settings)
    try:
        _imap_select(box, label)
        # Iter 126e — Gmail category tabs (Primary / Promotions / Social /
        # Updates). Gmail IMAP exposes them through X-GM-RAW searches.
        lab = (label or "INBOX").upper()
        category = None
        if lab.startswith("CATEGORY_"):
            category = lab.split("_", 1)[1].lower()
            if category == "personal":
                category = "primary"
        raw_terms = []
        if category:
            raw_terms.append(f"category:{category}")
        if q:
            raw_terms.append(q.replace('"', ""))
        if raw_terms:
            try:
                typ, data = box.uid("SEARCH", "X-GM-RAW", f'"{" ".join(raw_terms)}"')
            except Exception:
                # Non-Gmail IMAP server — fall back to plain text search.
                criteria = f'(TEXT "{(q or "").replace(chr(34), "")}")' if q else "ALL"
                typ, data = box.uid("SEARCH", None, criteria)
        else:
            typ, data = box.uid("SEARCH", None, "ALL")
        uids = (data[0] or b"").split()
        uids = uids[-limit:][::-1]  # newest first
        out = []
        for uid in uids:
            typ, md = box.uid(
                "FETCH", uid,
                "(FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE)])",
            )
            if typ != "OK" or not md or not isinstance(md[0], tuple):
                continue
            meta = md[0][0] or b""
            msg = _email.message_from_bytes(md[0][1] or b"")
            out.append({
                "id": uid.decode(),
                "thread_id": None,
                "snippet": "",
                "subject": _decode_hdr(msg.get("Subject")),
                "from": _decode_hdr(msg.get("From")),
                "to": _decode_hdr(msg.get("To")),
                "date": msg.get("Date") or "",
                "unread": b"\\Seen" not in meta,
            })
        return out
    finally:
        try:
            box.logout()
        except Exception:
            pass


def _imap_detail_sync(settings: dict, uid: str) -> Optional[dict]:
    import email as _email
    box = _imap_connect(settings)
    try:
        _imap_select(box, "INBOX")
        typ, md = box.uid("FETCH", uid.encode(), "(BODY.PEEK[])")
        if typ != "OK" or not md or not isinstance(md[0], tuple):
            return None
        msg = _email.message_from_bytes(md[0][1] or b"")
        html = plain = None
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_filename():
                continue  # skip attachments
            ctype = part.get_content_type()
            try:
                payload = part.get_payload(decode=True)
                decoded = payload.decode(part.get_content_charset() or "utf-8", "replace") if payload else None
            except Exception:
                decoded = None
            if not decoded:
                continue
            if ctype == "text/html" and html is None:
                html = decoded
            elif ctype == "text/plain" and plain is None:
                plain = decoded
        return {
            "id": uid,
            "thread_id": None,
            "subject": _decode_hdr(msg.get("Subject")),
            "from": _decode_hdr(msg.get("From")),
            "to": _decode_hdr(msg.get("To")),
            "date": msg.get("Date") or "",
            "message_id_header": msg.get("Message-ID") or "",
            "body_html": html,
            "body_text": plain,
            "snippet": (plain or "")[:160],
        }
    finally:
        try:
            box.logout()
        except Exception:
            pass


def _cfg():
    cid = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip().strip('"')
    secret = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip().strip('"')
    redirect = (os.environ.get("GMAIL_REDIRECT_URI") or "").strip().strip('"')
    if not cid or not secret or not redirect:
        raise HTTPException(status_code=500, detail="Gmail integration is not configured")
    return cid, secret, redirect


@router.get("/gmail/auth-url")
async def gmail_auth_url(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    cid, _, redirect = _cfg()
    state = f"gm_{uuid.uuid4().hex}"
    await db.gmail_oauth_states.insert_one(
        {"state": state, "user_id": user["user_id"], "created_at": now_iso()},
    )
    from urllib.parse import urlencode
    params = urlencode({
        "client_id": cid,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",           # force refresh_token issuance
        "state": state,
    })
    return {"auth_url": f"{GOOGLE_AUTH_URL}?{params}"}


@router.get("/gmail/oauth/callback")
async def gmail_oauth_callback(code: Optional[str] = None, state: Optional[str] = None,
                               error: Optional[str] = None):
    def _page(msg: str, ok: bool) -> HTMLResponse:
        color = "#166534" if ok else "#B91C1C"
        return HTMLResponse(
            f"""<html><body style="font-family:Arial;text-align:center;padding-top:80px">
            <h2 style="color:{color}">{msg}</h2>
            <p>You can close this tab and return to the portal — open the
            <b>Mailbox</b> page again.</p>
            <script>setTimeout(function(){{ window.location = '/mailbox?connected={1 if ok else 0}'; }}, 1800);</script>
            </body></html>"""
        )

    if error or not code or not state:
        return _page(f"Gmail connection failed: {error or 'missing code'}", False)
    st = await db.gmail_oauth_states.find_one({"state": state})
    if not st:
        return _page("Gmail connection failed: invalid state", False)
    await db.gmail_oauth_states.delete_many({"state": state})

    cid, secret, redirect = _cfg()
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": cid,
            "client_secret": secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        })
    if r.status_code != 200:
        return _page(f"Token exchange failed: {r.text[:200]}", False)
    tok = r.json()
    refresh_token = tok.get("refresh_token")
    access_token = tok.get("access_token")
    if not refresh_token:
        return _page("Google did not return a refresh token — remove the app's access at myaccount.google.com/permissions and try again.", False)

    # Fetch the connected email address.
    email = None
    try:
        async with httpx.AsyncClient(timeout=30) as cx:
            pr = await cx.get(f"{GMAIL_API}/profile",
                              headers={"Authorization": f"Bearer {access_token}"})
            if pr.status_code == 200:
                email = pr.json().get("emailAddress")
    except httpx.HTTPError:
        pass

    await db.gmail_accounts.update_one(
        {"user_id": st["user_id"]},
        {"$set": {
            "user_id": st["user_id"],
            "email": email,
            "refresh_token": refresh_token,
            "connected_at": now_iso(),
        }},
        upsert=True,
    )
    _access_cache.pop(st["user_id"], None)
    return _page(f"Gmail connected: {email or 'success'}", True)


async def _access_token(user_id: str) -> str:
    cached = _access_cache.get(user_id)
    if cached and cached["exp"] > time.time() + 60:
        return cached["token"]
    acct = await db.gmail_accounts.find_one({"user_id": user_id})
    if not acct or not acct.get("refresh_token"):
        raise HTTPException(status_code=409, detail="Gmail is not connected")
    cid, secret, _ = _cfg()
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.post(GOOGLE_TOKEN_URL, data={
            "refresh_token": acct["refresh_token"],
            "client_id": cid,
            "client_secret": secret,
            "grant_type": "refresh_token",
        })
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Gmail token refresh failed — reconnect your mailbox.",
        )
    tok = r.json()
    _access_cache[user_id] = {
        "token": tok["access_token"],
        "exp": time.time() + int(tok.get("expires_in") or 3500),
    }
    return tok["access_token"]


@router.get("/gmail/status")
async def gmail_status(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    # Iter 127 — Sub Admins may READ the shared mailbox (primary-inbox
    # notifications on their home screen link here).
    require_role(user, ["super_admin", "sub_admin"])
    acct = await db.gmail_accounts.find_one({"user_id": user["user_id"]}, {"_id": 0, "refresh_token": 0})
    if acct:
        return {"connected": True, "email": acct.get("email"),
                "connected_at": acct.get("connected_at"), "via": "oauth"}
    # Fallback — SMTP & Notifications credentials double as the mailbox.
    smtp = await _smtp_settings()
    if smtp:
        return {"connected": True, "email": smtp.get("username"),
                "connected_at": None, "via": "smtp"}
    return {"connected": False, "email": None, "connected_at": None}


# ---------------------------------------------------------------------------
# Iter 127 — Primary-inbox alert feed for admin home screens.
# Super Admins AND Sub Admins poll this endpoint (60s) so a bell badge +
# dashboard banner can "ping" whenever a new email lands in the Gmail
# PRIMARY category. The result is cached server-side for 45s so many
# concurrent admins don't hammer Gmail / IMAP.
# ---------------------------------------------------------------------------
_primary_unread_cache: dict = {"exp": 0.0, "data": None}


@router.get("/gmail/primary-unread")
async def gmail_primary_unread(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    if _primary_unread_cache["data"] is not None and time.time() < _primary_unread_cache["exp"]:
        return _primary_unread_cache["data"]

    result: dict = {"connected": False, "count": 0, "messages": []}
    try:
        acct = await db.gmail_accounts.find_one(
            {"user_id": user["user_id"]}, {"_id": 0, "user_id": 1})
        if acct:
            token = await _access_token(user["user_id"])
            params = [("maxResults", 5), ("labelIds", "INBOX"),
                      ("labelIds", "CATEGORY_PERSONAL"), ("q", "is:unread")]
            async with httpx.AsyncClient(timeout=30) as cx:
                r = await cx.get(f"{GMAIL_API}/messages", params=params,
                                 headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 200:
                    data = r.json()
                    ids = [m["id"] for m in data.get("messages", [])]
                    out = []
                    for mid in ids:
                        mr = await cx.get(
                            f"{GMAIL_API}/messages/{mid}",
                            params={"format": "metadata",
                                    "metadataHeaders": ["Subject", "From", "Date"]},
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        if mr.status_code != 200:
                            continue
                        m = mr.json()
                        hs = (m.get("payload") or {}).get("headers") or []
                        out.append({"id": m["id"], "subject": _hdr(hs, "Subject"),
                                    "from": _hdr(hs, "From"), "date": _hdr(hs, "Date")})
                    result = {"connected": True,
                              "count": int(data.get("resultSizeEstimate") or len(out)),
                              "messages": out}
        else:
            smtp = await _smtp_settings()
            if smtp:
                import asyncio as _asyncio
                msgs = await _asyncio.to_thread(
                    _imap_list_sync, smtp, "CATEGORY_PRIMARY", "is:unread", 10)
                unread = [m for m in msgs if m.get("unread")]
                result = {"connected": True, "count": len(unread),
                          "messages": [{"id": m["id"], "subject": m["subject"],
                                        "from": m["from"], "date": m["date"]}
                                       for m in unread[:5]]}
    except Exception as e:  # network/IMAP hiccups must never break dashboards
        result = {"connected": False, "count": 0, "messages": [],
                  "error": str(e)[:160]}

    _primary_unread_cache["data"] = result
    _primary_unread_cache["exp"] = time.time() + 45
    return result


@router.post("/gmail/disconnect")
async def gmail_disconnect(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    await db.gmail_accounts.delete_many({"user_id": user["user_id"]})
    _access_cache.pop(user["user_id"], None)
    return {"ok": True}


def _hdr(headers: list, name: str) -> str:
    for h in headers or []:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""


@router.get("/gmail/messages")
async def gmail_messages(
    q: Optional[str] = Query(None),
    page_token: Optional[str] = Query(None),
    label: str = Query("INBOX"),
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    # SMTP/IMAP fallback when Gmail OAuth is not connected.
    acct = await db.gmail_accounts.find_one({"user_id": user["user_id"]}, {"_id": 0, "user_id": 1})
    if not acct:
        smtp = await _smtp_settings()
        if not smtp:
            raise HTTPException(status_code=409, detail="Gmail is not connected")
        import asyncio as _asyncio
        try:
            msgs = await _asyncio.to_thread(_imap_list_sync, smtp, label, q)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"IMAP read failed: {str(e)[:200]}")
        return {"messages": msgs, "next_page_token": None, "via": "smtp"}
    token = await _access_token(user["user_id"])
    # Iter 126e — category tabs: CATEGORY_* labels combine with INBOX so
    # the tabs mirror Gmail's Primary / Promotions / Social / Updates.
    lab = (label or "INBOX").upper()
    label_ids = ["INBOX", lab] if lab.startswith("CATEGORY_") else [lab]
    params = [("maxResults", 25)] + [("labelIds", l) for l in label_ids]
    if q:
        params.append(("q", q))
    if page_token:
        params.append(("pageToken", page_token))
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.get(f"{GMAIL_API}/messages",
                         params=params,
                         headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Gmail list failed: {r.text[:200]}")
        data = r.json()
        ids = [m["id"] for m in data.get("messages", [])]
        out = []
        for mid in ids:
            mr = await cx.get(
                f"{GMAIL_API}/messages/{mid}",
                params={"format": "metadata",
                        "metadataHeaders": ["Subject", "From", "Date", "To"]},
                headers={"Authorization": f"Bearer {token}"},
            )
            if mr.status_code != 200:
                continue
            m = mr.json()
            hs = (m.get("payload") or {}).get("headers") or []
            out.append({
                "id": m["id"],
                "thread_id": m.get("threadId"),
                "snippet": m.get("snippet"),
                "subject": _hdr(hs, "Subject"),
                "from": _hdr(hs, "From"),
                "to": _hdr(hs, "To"),
                "date": _hdr(hs, "Date"),
                "unread": "UNREAD" in (m.get("labelIds") or []),
            })
    return {"messages": out, "next_page_token": data.get("nextPageToken")}


def _extract_body(payload: dict) -> dict:
    """Walk the MIME tree; prefer text/html, fall back to text/plain."""
    html = plain = None

    def walk(p):
        nonlocal html, plain
        mime = p.get("mimeType") or ""
        body = p.get("body") or {}
        data = body.get("data")
        if data:
            try:
                decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
            except (ValueError, TypeError):
                decoded = None
            if decoded:
                if mime == "text/html" and html is None:
                    html = decoded
                elif mime == "text/plain" and plain is None:
                    plain = decoded
        for part in p.get("parts") or []:
            walk(part)

    walk(payload or {})
    return {"html": html, "text": plain}


@router.get("/gmail/messages/{msg_id}")
async def gmail_message_detail(msg_id: str, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin", "sub_admin"])
    # SMTP/IMAP fallback when Gmail OAuth is not connected.
    acct = await db.gmail_accounts.find_one({"user_id": user["user_id"]}, {"_id": 0, "user_id": 1})
    if not acct:
        smtp = await _smtp_settings()
        if not smtp:
            raise HTTPException(status_code=409, detail="Gmail is not connected")
        import asyncio as _asyncio
        try:
            detail = await _asyncio.to_thread(_imap_detail_sync, smtp, msg_id)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"IMAP read failed: {str(e)[:200]}")
        if not detail:
            raise HTTPException(status_code=404, detail="Message not found")
        return detail
    token = await _access_token(user["user_id"])
    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.get(f"{GMAIL_API}/messages/{msg_id}",
                         params={"format": "full"},
                         headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Gmail read failed: {r.text[:200]}")
    m = r.json()
    hs = (m.get("payload") or {}).get("headers") or []
    body = _extract_body(m.get("payload") or {})
    return {
        "id": m["id"],
        "thread_id": m.get("threadId"),
        "subject": _hdr(hs, "Subject"),
        "from": _hdr(hs, "From"),
        "to": _hdr(hs, "To"),
        "date": _hdr(hs, "Date"),
        "message_id_header": _hdr(hs, "Message-ID"),
        "body_html": body["html"],
        "body_text": body["text"],
        "snippet": m.get("snippet"),
    }


@router.post("/gmail/send")
async def gmail_send(payload: dict, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["super_admin"])
    to = (payload.get("to") or "").strip()
    subject = payload.get("subject") or ""
    body = payload.get("body") or ""
    if not to or not body:
        raise HTTPException(status_code=400, detail="'to' and 'body' are required")
    # SMTP fallback when Gmail OAuth is not connected — send through the
    # shared Email SMTP & Notifications sender (and log it).
    acct = await db.gmail_accounts.find_one({"user_id": user["user_id"]}, {"_id": 0, "user_id": 1})
    if not acct:
        smtp = await _smtp_settings()
        if not smtp:
            raise HTTPException(status_code=409, detail="Gmail is not connected")
        from routes.email_notifications import _send_and_log
        entry = await _send_and_log(smtp, to, subject, body, "mailbox_compose")
        if entry.get("status") != "sent":
            raise HTTPException(status_code=502, detail=f"SMTP send failed: {entry.get('error') or 'unknown error'}")
        return {"ok": True, "id": entry.get("log_id"), "via": "smtp"}
    token = await _access_token(user["user_id"])

    msg = MIMEText(body)
    msg["To"] = to
    msg["Subject"] = subject
    in_reply_to = payload.get("in_reply_to")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    req: dict = {"raw": raw}
    if payload.get("thread_id"):
        req["threadId"] = payload["thread_id"]

    async with httpx.AsyncClient(timeout=30) as cx:
        r = await cx.post(f"{GMAIL_API}/messages/send",
                          json=req,
                          headers={"Authorization": f"Bearer {token}"})
    if r.status_code not in (200, 202):
        raise HTTPException(status_code=502, detail=f"Gmail send failed: {r.text[:200]}")
    return {"ok": True, "id": r.json().get("id")}
