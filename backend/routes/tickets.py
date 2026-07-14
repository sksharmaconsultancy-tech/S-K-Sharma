"""Iter 86 - Route module: Support Tickets.

Extracted from `server.py` as part of the modularization effort.

Endpoints (all `/api` prefixed):
  * POST   /tickets                              - Create a new ticket
                                                   (with optional base64
                                                   file attachments).
  * GET    /tickets                              - List tickets (mine|all).
  * GET    /tickets/{ticket_id}/attachments/{i}  - Fetch one attachment's
                                                   full base64 body.
  * PATCH  /tickets/{ticket_id}                  - Admin update
                                                   (status + reply).

Shared state (`db`, auth helpers, Pydantic models `TicketCreate`,
`TicketUpdate`, `now_iso`) is imported from the `server` module -- see
`routes/__init__.py` for the import-order safety notes.
"""
import base64
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from server import (  # noqa: E402
    db,
    get_user_from_token,
    require_role,
    now_iso,
    TicketCreate,
    TicketUpdate,
)

router = APIRouter(prefix="/api", tags=["tickets"])


@router.post("/tickets")
async def create_ticket(payload: TicketCreate, authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)

    # Validate & normalise attachments. Cap: 5 files x 5 MB each.
    MAX_FILES = 5
    MAX_BYTES = 5 * 1024 * 1024
    attachments_meta: list[dict] = []
    attachments_data: list[dict] = []
    if payload.attachments:
        if len(payload.attachments) > MAX_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"You can attach at most {MAX_FILES} files per ticket.",
            )
        for idx, att in enumerate(payload.attachments):
            raw_b64 = (att.data_base64 or "").strip()
            # strip data URL prefix if present
            if "," in raw_b64 and raw_b64.lower().startswith("data:"):
                raw_b64 = raw_b64.split(",", 1)[1]
            # Reject empty / non-base64
            try:
                blob = base64.b64decode(raw_b64, validate=True)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Attachment '{att.name}' is not valid base64.",
                )
            if len(blob) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Attachment '{att.name}' is empty.",
                )
            if len(blob) > MAX_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Attachment '{att.name}' is {len(blob) // 1024} KB - "
                        f"maximum allowed is {MAX_BYTES // (1024 * 1024)} MB per file."
                    ),
                )
            safe_name = (att.name or f"attachment-{idx + 1}").strip()[:120]
            attachments_meta.append({
                "index": idx,
                "name": safe_name,
                "mime": att.mime,
                "size": len(blob),
            })
            attachments_data.append({
                "index": idx,
                "name": safe_name,
                "mime": att.mime,
                "size": len(blob),
                "data_base64": raw_b64,
            })

    ticket = {
        "ticket_id": f"tkt_{uuid.uuid4().hex[:10]}",
        "user_id": user["user_id"],
        "company_id": user.get("company_id"),
        "user_name": user["name"],
        "user_email": user["email"],
        "category": payload.category,
        "subject": payload.subject,
        "description": payload.description,
        "status": "open",
        "admin_reply": None,
        "created_at": now_iso(),
        # Full attachment bodies live on the doc; list endpoints only
        # return the metadata slice.
        "attachments": attachments_data,
    }
    await db.tickets.insert_one(ticket)
    # Iter 103 — automated email trigger
    try:
        from routes.email_notifications import fire_email_event
        await fire_email_event(
            "ticket_raised", company_id=user.get("company_id"),
            employee_user_id=user["user_id"], details=payload.subject)
    except Exception:
        pass
    # Response mirrors the list endpoint - attachment metadata only.
    out = {k: v for k, v in ticket.items() if k != "_id"}
    out["attachments"] = attachments_meta
    return out


@router.get("/tickets/{ticket_id}/attachments/{index}")
async def get_ticket_attachment(
    ticket_id: str,
    index: int,
    authorization: Optional[str] = Header(None),
):
    """Return the full base64 body of a specific attachment. Employee can
    only fetch their own tickets' attachments; company_admin can fetch
    any within their company; super_admin sees all."""
    user = await get_user_from_token(authorization)
    ticket = await db.tickets.find_one({"ticket_id": ticket_id}, {"_id": 0})
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    role = user.get("role")
    if role == "employee":
        if ticket.get("user_id") != user.get("user_id"):
            raise HTTPException(status_code=403, detail="Not your ticket")
    elif role == "company_admin":
        if ticket.get("company_id") != user.get("company_id"):
            raise HTTPException(status_code=403, detail="Not your company")
    # super_admin: unrestricted

    atts = ticket.get("attachments") or []
    if index < 0 or index >= len(atts):
        raise HTTPException(status_code=404, detail="Attachment not found")
    att = atts[index]
    return {
        "index": index,
        "name": att.get("name"),
        "mime": att.get("mime"),
        "size": att.get("size"),
        "data_base64": att.get("data_base64"),
    }


@router.get("/tickets")
async def list_tickets(scope: str = Query("mine"),
                       authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    if scope == "all":
        require_role(user, ["company_admin", "super_admin"])
        q = {}
        if user["role"] == "company_admin" and user.get("company_id"):
            q = {"company_id": user["company_id"]}
    else:
        q = {"user_id": user["user_id"]}
    tickets = await db.tickets.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Strip base64 blobs from list responses - clients call the per-
    # attachment endpoint on demand. This keeps ticket-list payloads
    # small even when several PDFs are attached.
    for t in tickets:
        atts = t.get("attachments") or []
        t["attachments"] = [
            {
                "index": (a.get("index") if a.get("index") is not None else i),
                "name": a.get("name"),
                "mime": a.get("mime"),
                "size": a.get("size"),
            }
            for i, a in enumerate(atts)
        ]
    return {"tickets": tickets}


@router.patch("/tickets/{ticket_id}")
async def update_ticket(ticket_id: str, payload: TicketUpdate,
                        authorization: Optional[str] = Header(None)):
    user = await get_user_from_token(authorization)
    require_role(user, ["company_admin", "super_admin"])
    r = await db.tickets.update_one(
        {"ticket_id": ticket_id},
        {"$set": {"status": payload.status,
                  "admin_reply": payload.admin_reply,
                  "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    ticket = await db.tickets.find_one({"ticket_id": ticket_id}, {"_id": 0})
    # Iter 103 — automated email trigger on resolution
    try:
        if payload.status in ("resolved", "closed"):
            from routes.email_notifications import fire_email_event
            await fire_email_event(
                "ticket_resolved", company_id=ticket.get("company_id"),
                employee_user_id=ticket.get("user_id"),
                details=ticket.get("subject") or ticket_id)
    except Exception:
        pass
    return ticket
