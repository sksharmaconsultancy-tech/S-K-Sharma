#!/bin/bash
# S.K. Sharma & Co. — VPS backend repair (Iter 441)
# Diagnoses why the backend is down after deploy435 and auto-fixes the
# common causes (failed pip install, stuck port, stale process).
APP_DIR=/home/sksharma/app
PY=$APP_DIR/backend/venv/bin/python
PIP=$APP_DIR/backend/venv/bin/pip

echo "=============================================="
echo " STEP 1/5 — Last backend error lines"
echo "=============================================="
sudo supervisorctl tail -4000 sksharma-backend stderr 2>/dev/null | tail -40 || true

echo ""
echo "=============================================="
echo " STEP 2/5 — Manual import test (shows the exact crash)"
echo "=============================================="
cd $APP_DIR/backend
$PY - << 'PYEOF'
import traceback
try:
    import server  # noqa: F401
    print("IMPORT OK — server.py loads fine, the crash is not an import error")
except Exception:
    traceback.print_exc()
PYEOF

echo ""
echo "=============================================="
echo " STEP 3/5 — Reinstalling backend requirements"
echo "=============================================="
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q && echo "pip OK" || echo "pip had errors (see above)"
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo ""
echo "=============================================="
echo " STEP 4/5 — Restarting backend"
echo "=============================================="
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 5

echo ""
echo "=============================================="
echo " STEP 5/5 — Health check"
echo "=============================================="
if curl -s http://localhost:8001/api/health | grep -q ok; then
  echo "✅ BACKEND IS UP — open the website and press Ctrl+Shift+R once."
else
  echo "❌ Backend is STILL down. Fresh error below — send this to the agent:"
  sudo supervisorctl tail -4000 sksharma-backend stderr 2>/dev/null | tail -40
fi
