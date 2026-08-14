"""MSG91 provider — ALL MSG91-specific code lives here (Iter 576).

Per latest MSG91 docs: Flow API v5 for template SMS, self-generated OTPs
are sent through a DLT-approved OTP flow. Credentials come from the
sms_settings collection (server-side only) — never from the frontend.
"""
from typing import Any, Dict
import httpx

BASE_URL = "https://control.msg91.com"


class MSG91Error(RuntimeError):
    pass


async def send_flow(authkey: str, flow_id: str, sender: str, mobile: str,
                    variables: Dict[str, str]) -> Dict[str, Any]:
    """POST /api/v5/flow/ — returns {'request_id': ...}. Mobile must be
    international format 91XXXXXXXXXX (no +)."""
    recipient = {"mobiles": mobile, **{k: str(v) for k, v in variables.items()}}
    payload = {"flow_id": flow_id, "sender": sender, "recipients": [recipient]}
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as hc:
        r = await hc.post(f"{BASE_URL}/api/v5/flow/", json=payload,
                          headers={"authkey": authkey, "Content-Type": "application/json"})
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:200]}
    if r.is_error or str(data.get("type", "")).lower() == "error":
        raise MSG91Error(f"HTTP {r.status_code}: {str(data)[:200]}")
    return {"request_id": data.get("message"), "raw_type": data.get("type")}


def normalize_mobile(phone: str) -> str:
    """→ 91XXXXXXXXXX or '' if not a valid Indian mobile."""
    d = "".join(c for c in (phone or "") if c.isdigit())
    if len(d) == 10 and d[0] in "6789":
        return "91" + d
    if len(d) == 12 and d.startswith("91") and d[2] in "6789":
        return d
    return ""


def mask_mobile(phone: str) -> str:
    d = "".join(c for c in (phone or "") if c.isdigit())
    return f"{d[:2]}XXXXXX{d[-2:]}" if len(d) >= 10 else "XXXX"
