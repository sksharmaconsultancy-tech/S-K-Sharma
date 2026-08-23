#!/bin/bash
# Local dev helper — mint a super-admin session token (OTP bypass via mongo).
B=http://localhost:8001/api
PT=$(curl -s -X POST $B/auth/admin-password-login -H 'Content-Type: application/json' -d '{"email":"sksharmaconsultancy@gmail.com","password":"sharma123"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['pending_token'])")
HH=$(python3 -c "import hashlib;print(hashlib.sha256(b'123456').hexdigest())")
mongosh --quiet test_database --eval "db.twofa_pending.updateMany({pending_id:'$PT'},{\$set:{otp_hash:'$HH',attempts:0,blocked:false}})" >/dev/null
curl -s -X POST $B/auth/2fa/verify -H 'Content-Type: application/json' -d "{\"pending_token\":\"$PT\",\"otp\":\"123456\"}" | python3 -c "import json,sys;print(json.load(sys.stdin)['session_token'])" | tee /tmp/skc_token.txt
