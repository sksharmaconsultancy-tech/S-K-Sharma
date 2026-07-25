"""Productivity endpoints — data-wide Global Search.

GET /api/admin/global-search?q= — searches employees (name / code / bio
code / Aadhaar / PAN / UAN), firms and returns grouped results for the
top-bar search dropdown. Role-scoped: company admins only see their firm.
"""
import re
from typing import Optional

from fastapi import APIRouter, Header, Query

from server import db, get_user_from_token, require_role  # noqa: E402

router = APIRouter(prefix="/api", tags=["productivity"])


@router.get("/admin/global-search")
async def global_search(
    q: str = Query(..., min_length=2),
    authorization: Optional[str] = Header(None),
):
    admin = await get_user_from_token(authorization)
    require_role(admin, ["super_admin", "company_admin", "sub_admin"])
    term = q.strip()
    rx = {"$regex": re.escape(term), "$options": "i"}

    emp_q: dict = {"role": "employee", "$or": [
        {"name": rx},
        {"employee_code": {"$regex": f"^{re.escape(term)}", "$options": "i"}},
        {"bio_code": {"$regex": f"^{re.escape(term)}", "$options": "i"}},
        {"aadhaar": {"$regex": f"^{re.escape(term)}"}},
        {"pan": {"$regex": f"^{re.escape(term)}", "$options": "i"}},
        {"uan": {"$regex": f"^{re.escape(term)}"}},
    ]}
    if admin["role"] == "company_admin":
        emp_q["company_id"] = admin.get("company_id")
    employees = await db.users.find(emp_q, {
        "_id": 0, "user_id": 1, "name": 1, "employee_code": 1,
        "designation": 1, "company_id": 1,
    }).to_list(6)

    companies = []
    if admin["role"] in ("super_admin", "sub_admin"):
        companies = await db.companies.find(
            {"$or": [{"name": rx}, {"code": rx}]},
            {"_id": 0, "company_id": 1, "name": 1, "code": 1},
        ).to_list(4)

    # Firm-name lookup for employee subtitle
    firm_names = {}
    cids = {e.get("company_id") for e in employees if e.get("company_id")}
    if cids:
        async for c in db.companies.find(
            {"company_id": {"$in": list(cids)}}, {"_id": 0, "company_id": 1, "name": 1}
        ):
            firm_names[c["company_id"]] = c["name"]
    for e in employees:
        e["firm_name"] = firm_names.get(e.get("company_id"), "")

    return {"employees": employees, "companies": companies}
