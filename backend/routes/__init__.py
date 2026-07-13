"""Iter 86 - Route modularization.

Route modules are progressively being extracted from the monolithic
`server.py` into themed sub-modules under this package. Each module
exposes a `router: APIRouter` that `server.py` imports and includes
AFTER all shared helpers (`db`, `get_user_from_token`, `require_role`,
etc.) have been defined - so the sub-modules can safely do
``from server import db, get_user_from_token``.

Modules extracted so far:
  * reports_extra  - Users log audit trail across firms & admins.

Still inline in server.py (to be extracted in follow-up sessions):
  * auth (login, OTP, sessions)
  * attendance (punches, approvals, monthly-grid, .dat import)
  * payroll (salary-runs, compliance-salary-runs, actual-salary-process)
  * masters (companies, employee master, groups, shifts)
  * misc (tickets, messages, notifications)
"""
