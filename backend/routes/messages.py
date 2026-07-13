"""Iter 86 - Route module: In-App Messaging.

Admin (company_admin or super_admin) composes announcements or DMs;
each message stores a `recipient_user_ids` list plus a `read_by` list
to power unread badges. One-way for now - employees can only read.

Endpoints:
  * POST /messages                                       - Send
  * GET  /messages/inbox                                 - Recipient view
  * GET  /messages/unread-count                          - Badge
  * GET  /messages/sent                                  - Sender outbox
  * GET  /messages/{message_id}/attachments/{attachment_id} - Download
  * POST /messages/{message_id}/read                     - Mark read
  * GET  /messages/recipients                            - Picker
"""
import base64 as _b64
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    MessageCreate,
)

router = APIRouter(prefix="/api", tags=["messages"])

ALLOWED_ATTACH_MIME = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "application/pdf",
}


@router.post("/messages")
async def send_message(
    payload: MessageCreate,
    authorization: Optional[str] = Header(None),
):
    """Admin sends a message to one or more employees, or broadcasts to
    the whole company."""
    sender = await get_user_from_token(authorization)
    require_role(sender, ["company_admin", "super_admin"])

    subject = (payload.subject or "").strip()
    body = (payload.body or "").strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject is required")
    if not body:
        raise HTTPException(status_code=400, detail="Message body is required")
    if len(subject) > 200:
        raise HTTPException(status_code=400, detail="Subject too long (max 200 chars)")
    if len(body) > 5000:
        raise HTTPException(status_code=400, detail="Message body too long (max 5000 chars)")

    if sender["role"] == "company_admin":
        target_company_id = sender.get("company_id")
    else:  # super_admin
        target_company_id = (payload.company_id or "").strip() or None

    if payload.broadcast:
        q: dict = {"role": "employee"}
        if target_company_id:
            q["company_id"] = target_company_id
        recipients_docs = await db.users.find(
            q, {"_id": 0, "user_id": 1, "company_id": 1},
        ).to_list(10000)
        recipient_ids = [u["user_id"] for u in recipients_docs]
    else:
        if not payload.recipient_user_ids:
            raise HTTPException(
                status_code=400,
                detail="Provide at least one recipient (or set broadcast=true).",
            )
        q = {"user_id": {"$in": payload.recipient_user_ids}}
        if sender["role"] == "company_admin":
            q["company_id"] = sender.get("company_id")
        recipients_docs = await db.users.find(
            q, {"_id": 0, "user_id": 1, "company_id": 1},
        ).to_list(10000)
        recipient_ids = [u["user_id"] for u in recipients_docs]
        if not recipient_ids:
            raise HTTPException(
                status_code=400,
                detail="No valid recipients found in your scope.",
            )

    message = {
        "message_id": f"msg_{uuid.uuid4().hex[:12]}",
        "sender_user_id": sender["user_id"],
        "sender_name": sender.get("name"),
        "sender_role": sender.get("role"),
        "company_id": target_company_id,
        "subject": subject,
        "body": body,
        "sent_at": now_iso(),
        "recipient_user_ids": recipient_ids,
        "recipient_count": len(recipient_ids),
        "read_by": [],
        "is_broadcast": bool(payload.broadcast),
    }

    attachments_stored: List[Dict[str, Any]] = []
    incoming = payload.attachments or []
    if len(incoming) > 3:
        raise HTTPException(
            status_code=400,
            detail="At most 3 attachments per message.",
        )
    for i, att in enumerate(incoming, start=1):
        mime = (att.mime_type or "").lower().strip()
        if mime not in ALLOWED_ATTACH_MIME:
            raise HTTPException(
                status_code=400,
                detail=f"Attachment {i}: unsupported type {mime!r}. Allowed: JPG/PNG/WebP images or PDF.",
            )
        b64_raw = att.base64 or ""
        if "," in b64_raw and b64_raw.strip().startswith("data:"):
            b64_raw = b64_raw.split(",", 1)[1]
        b64_raw = b64_raw.strip()
        if not b64_raw:
            raise HTTPException(status_code=400, detail=f"Attachment {i} is empty.")
        try:
            approx_bytes = (len(b64_raw) * 3) // 4
        except Exception:
            approx_bytes = 0
        if approx_bytes > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail=f"Attachment {i} exceeds the 5 MB limit.",
            )
        attachments_stored.append({
            "attachment_id": f"att_{uuid.uuid4().hex[:10]}",
            "filename": (att.filename or f"attachment_{i}").strip()[:180] or f"attachment_{i}",
            "mime_type": mime,
            "size_bytes": att.size_bytes or approx_bytes,
            "base64": b64_raw,
        })
    if attachments_stored:
        message["attachments"] = attachments_stored
        message["attachment_count"] = len(attachments_stored)

    await db.messages.insert_one(message)
    message.pop("_id", None)
    if attachments_stored:
        message["attachments"] = [
            {k: v for k, v in a.items() if k != "base64"}
            for a in attachments_stored
        ]
    return {"ok": True, "message": message}


@router.get("/messages/inbox")
async def get_inbox(
    limit: int = 100,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    limit = max(1, min(500, int(limit or 100)))
    msgs = await db.messages.find(
        {"recipient_user_ids": user["user_id"]},
        {
            "_id": 0,
            "message_id": 1, "subject": 1, "body": 1,
            "sender_name": 1, "sender_role": 1,
            "sent_at": 1, "read_by": 1, "is_broadcast": 1,
            "attachments": 1, "attachment_count": 1,
        },
    ).sort("sent_at", -1).to_list(limit)
    for m in msgs:
        m["read"] = user["user_id"] in (m.get("read_by") or [])
        m.pop("read_by", None)
        if m.get("attachments"):
            m["attachments"] = [
                {k: v for k, v in a.items() if k != "base64"}
                for a in m["attachments"]
            ]
    return {"messages": msgs, "count": len(msgs)}


@router.get("/messages/unread-count")
async def get_unread_count(authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    n = await db.messages.count_documents({
        "recipient_user_ids": user["user_id"],
        "read_by": {"$ne": user["user_id"]},
    })
    return {"unread": n}


@router.get("/messages/sent")
async def get_sent_messages(
    limit: int = 100,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin"])
    limit = max(1, min(500, int(limit or 100)))
    msgs = await db.messages.find(
        {"sender_user_id": user["user_id"]},
        {"_id": 0},
    ).sort("sent_at", -1).to_list(limit)
    for m in msgs:
        m["read_count"] = len(m.get("read_by") or [])
        if m.get("attachments"):
            m["attachments"] = [
                {k: v for k, v in a.items() if k != "base64"}
                for a in m["attachments"]
            ]
    return {"messages": msgs, "count": len(msgs)}


@router.get("/messages/{message_id}/attachments/{attachment_id}")
async def download_message_attachment(
    message_id: str,
    attachment_id: str,
    inline: bool = False,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    msg = await db.messages.find_one({"message_id": message_id}, {"_id": 0})
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    is_recipient = user["user_id"] in (msg.get("recipient_user_ids") or [])
    is_sender = msg.get("sender_user_id") == user["user_id"]
    is_super = user.get("role") == "super_admin"
    if not (is_recipient or is_sender or is_super):
        raise HTTPException(status_code=403, detail="Not your message")
    attachments = msg.get("attachments") or []
    att = next((a for a in attachments if a.get("attachment_id") == attachment_id), None)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    try:
        raw = _b64.b64decode(att.get("base64") or "", validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Corrupted attachment") from exc
    mime = att.get("mime_type") or "application/octet-stream"
    fname = att.get("filename") or "attachment"
    disp = "inline" if inline else "attachment"
    return Response(
        content=raw,
        media_type=mime,
        headers={"Content-Disposition": f'{disp}; filename="{fname}"'},
    )


@router.post("/messages/{message_id}/read")
async def mark_message_read(
    message_id: str,
    authorization: Optional[str] = Header(None),
):
    user = await get_user_from_token(authorization)
    msg = await db.messages.find_one({"message_id": message_id}, {"_id": 0, "recipient_user_ids": 1})
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if user["user_id"] not in (msg.get("recipient_user_ids") or []):
        raise HTTPException(status_code=403, detail="Not your message")
    await db.messages.update_one(
        {"message_id": message_id},
        {"$addToSet": {"read_by": user["user_id"]}},
    )
    return {"ok": True}


@router.get("/messages/recipients")
async def list_message_recipients(
    company_id: Optional[str] = None,
    q: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["company_admin", "super_admin"])
    query: dict = {"role": "employee"}
    if admin["role"] == "company_admin":
        query["company_id"] = admin.get("company_id")
    elif admin["role"] == "super_admin" and company_id and company_id != "all":
        query["company_id"] = company_id
    if q:
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [{"name": rx}, {"employee_code": rx}]
    users = await db.users.find(
        query,
        {
            "_id": 0, "user_id": 1, "name": 1,
            "employee_code": 1, "company_id": 1,
        },
    ).sort("name", 1).to_list(2000)
    return {"employees": users, "count": len(users)}
