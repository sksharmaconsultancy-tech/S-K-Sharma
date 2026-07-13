"""Seed manual punches for iter93 UI testing.

- user_44cd6f561da0 (SURENDRA SINGH, code 50): IN + OUT (Auto-Punches tab)
- user_4111f8eea5d3 (ALI HASAN, code 65): IN only (Manual Entries tab, OUT MISSING)
- user_c053ce367ca9 (RAJENDRA MEENA, code 81): no punch (Manual Entries tab, BOTH MISSING)

Also stores record_ids in /app/test_reports/iter93_seed.json for cleanup.
"""
import json, os, requests

BASE = "https://emplo-connect-1.preview.emergentagent.com"
DATE = "2026-07-09"
r = requests.post(f"{BASE}/api/auth/admin-password-login",
                  json={"email":"sksharma","password":"sharma123"}, timeout=30)
tok = r.json()["session_token"]
H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

# First delete any existing punches for these 3 users on that day
q = requests.get(f"{BASE}/api/admin/attendance/day-status/cmp_527fecdd7c",
                 params={"from_date": DATE, "to_date": DATE}, headers=H).json()
targets = {"user_44cd6f561da0","user_4111f8eea5d3","user_c053ce367ca9"}
for row in q["rows"]:
    if row["user_id"] in targets:
        for c in (row.get("in"), row.get("out")):
            if c and c.get("record_id"):
                requests.delete(f"{BASE}/api/admin/attendance/{c['record_id']}",
                                params={"reason":"iter93_seed_clean"}, headers=H)

created = []
def punch(uid, kind, tm):
    r = requests.post(f"{BASE}/api/admin/attendance/manual-punch",
                     json={"user_id":uid,"kind":kind,
                           "at":f"{DATE}T{tm}:00+05:30",
                           "reason":"iter93_ui_seed"}, headers=H)
    if r.status_code in (200,201):
        rid = (r.json().get("record") or r.json()).get("record_id")
        created.append(rid)
        print("created", uid, kind, tm, "->", rid)
    else:
        print("FAIL", uid, kind, r.status_code, r.text)

punch("user_44cd6f561da0","in","09:00")
punch("user_44cd6f561da0","out","18:00")
punch("user_4111f8eea5d3","in","09:15")
# user_c053ce367ca9 gets no punch (BOTH MISSING)

with open("/app/test_reports/iter93_seed.json","w") as f:
    json.dump({"date":DATE,"record_ids":created,"token":tok},f)
print("seed complete:", len(created), "records")
