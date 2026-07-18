# S.K. Sharma & Co. — Labour Law Compliance & Payroll Portal
Multi-tenant B2B portal: geofenced biometric attendance, payroll (EPF/ESIC/PT/TDS),
labour-law statutory reports, employee self-service PWA, admin web portal.

- `backend/` — FastAPI + MongoDB (run on port 8001, routes prefixed /api)
- `frontend/` — Expo (React Native Web) portal + PWA
- `deploy_vps_iter179.sh` — VPS deployment script (includes litellm pip fix)

> Note: `.env` files are NOT in the repo. Create `backend/.env` (MONGO_URL, DB_NAME, EMERGENT_LLM_KEY...) and `frontend/.env` (EXPO_PUBLIC_BACKEND_URL) on the server.
