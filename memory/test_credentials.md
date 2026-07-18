# Test Credentials

## Super Admin (updated Iter 93l)
- Email: sksharmaconsultancy@gmail.com
- Phone: +919680273960
- OTP: real email delivery ENABLED (OTP_EMAIL_ENABLED=true, Resend). dev_code still returned in response as fallback.
- PIN (admin-pin-login, 6-digit): CHANGED by user — 654321 no longer valid (verified 2026-06). Use password login instead.
- Password (admin-password-login): sharma123 — works with email (payload keys: {"email", "password"})

## Kankani Enterprises Firm (Iter 89 restored)
- Firm Name: Kankani Enterprises
- Company Code: KEPS
- Company ID: cmp_527fecdd7c
- Address: Industrial Area, Bhilwara, Rajasthan
- Business: Textile Manufacturing (loom-weaving)

## Kankani Company Admin
- Email: admin@kankani.local
- Phone: +919828100001
- Name: Prakash Kankani
- PIN: 1234
- Role: company_admin

## Kankani Employees (FRESH IMPORT 2026-07-09 from "Kankani Data.xls")
- 125 real employees imported (108 Labour + 17 Staff), employee codes 50–532 (plain numbers, e.g. "50", "212")
- bio_code = REAL device codes from updated sheet (2026-07-09), e.g. emp 50→bio 72, 65→19, 81→5. Duplicates: bio 55 (emp 437,460), bio 80 (emp 484,519)
- All PIN = 1234 (pin_hash preset); NO phone numbers in sheet → emp-code-login (needs phone last4) won't work until HR adds phones
- TEST EMPLOYEE (updated 2026-07 fork): code 50 SURENDRA SINGH → login via /pin-login screen: Username `TEST50`, PIN `123456` (login_id + pin_hash reset for UI testing)
- Salary: mostly DAILY rates (e.g. 745-1500/day); 3 MONTHLY staff (codes 212: 39000, 449: 23500, 479: 75000)
- salary_structure_actual: Basic Salary + Salary 1/2/3 attendance-bonus tiers (verbatim from legacy sheet)
- Spot checks: code 50 SURENDRA SINGH (Staff, daily 745), 212 MADAN KEER (Staff, monthly 39000)

## Attendance Data
- CLEARED on 2026-07-09 (fresh import) — no punches yet. Old seeded data backed up at /app/backups/kankani_backup_20260709_030725.json

## Env
- Backend: uvicorn on 0.0.0.0:8001
- Frontend: expo/metro on port 3000
- MongoDB: local, test_database
- Preview URL: https://emplo-connect-1.preview.emergentagent.com

## Iter 91 test data
- Test employee: user_ca0cba59bcdb (Ramesh Kumar Sharma, KEPS0001, Kankani cmp_527fecdd7c)
  - salary_structure_actual: Basic 15000 monthly; allowances HRA 4400.5, CONV. 2200; deductions PF 1320, ESI 165.25
- Firm master cmp_527fecdd7c: enabled allowances HRA/CONV./OVER TIME; deductions PF/ESI/ADVANCE
- Company admin OTP login: POST /api/auth/otp/request {channel:'sms', identifier:'+919828100001'} -> dev_code -> /api/auth/otp/verify. Token key (web localStorage): llc_session_token

## Firm Admin App/Web Credentials (Iter 93j)
- Kankani Enterprises admin (Prakash Kankani): User ID `Kankani123`. PASSWORD & PIN CHANGED BY USER (unknown). For testing as this admin, inject a session doc into user_sessions for user_0a38839e3568.
- Employee login (phoneless): employee_code + PIN via /auth/emp-code-login (phone_last4 field accepts the PIN, e.g. code 50 + 1234). Web gates employees to mobile app.

## Test Sub-Admin (Iter 123 — password reset, perms updated)
- Email: testsub@sksharma.co
- Password: testsub123 (password_must_change=false, working)
- sub_admin_permissions: employees:read, employees:write, attendance_policy:read, attendance_policy:write, companies:read
- sub_admin_company_scope: all
- Purpose: verify sub-admin Employee Master edit rights (user-rights gated)

## Test Employee (Iter 100 — employer-portal block testing)
- Employee code 50 (SURENDRA SINGH, Kankani): PIN reset to 654321 (6-digit, working). Phone cleared back to None.
- Note: "All PIN = 1234" for imported employees is STALE — backend requires 6-digit PINs.

## City Care Hospital (Iter 105 — hospital shift-change testing)
- Firm: City Care Hospital, Code CCH, company_id cmp_987f0d7da5, business_category=hospital
- Attendance policy: hospital preset (Morning 07-15, Evening 15-23, Night 23-07; 8h full / 4h half day)
- Employees (all PIN 654321, login via /auth/pin-login with phone):
  - CCH001 Nurse Anita Verma +919000000101 (shift swapped to Evening in test)
  - CCH002 Nurse Rekha Jain +919000000102 (Night after test approval)
  - CCH003 Ward Boy Sunil +919000000103 (Morning after test swap)
- Shift-change endpoints: GET /api/shift-change/options, POST /api/shift-change-requests, POST /api/admin/shift-change-requests/{id}/decide (approve requires replacement_user_id)

## Note (Iter 139, June 2026)
- Preview firm 'City Care Hospital' was recreated as cmp_adddad3f65 (old one force-deleted during delete-permission testing). Sub-admin testsub@sksharma.co is scoped to it. Its 3 placeholder employees were lost (preview data only).

## PROD (smartpayrolling.com) Super Admin — 2026-07-16
- Email: sksharmaconsultancy@gmail.com
- Password login ENABLED on prod via VPS script (bcrypt r12). Initial password Sharma@2026 — user advised to change it. PIN on prod is user's own (workspace temp PIN 246810 NOT valid on prod).
