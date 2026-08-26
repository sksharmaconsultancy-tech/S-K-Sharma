"""Helper: login super admin via password + 2FA (mongo swap)."""
import os, hashlib, sys, requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
BASE = os.environ.get('EXPO_PUBLIC_BACKEND_URL', 'https://emplo-connect-1.preview.emergentagent.com').rstrip('/')
MONGO = os.environ['MONGO_URL']
DB = os.environ.get('DB_NAME', 'test_database')

def login():
    r = requests.post(f"{BASE}/api/auth/admin-password-login",
                      json={"email": "sksharmaconsultancy@gmail.com", "password": "sharma123"},
                      timeout=30)
    r.raise_for_status()
    data = r.json()
    pending = data.get("pending_token")
    if not pending:
        # already returns session_token in some setups
        if data.get("session_token"):
            return data["session_token"]
        raise RuntimeError(f"No pending_token: {data}")

    client = MongoClient(MONGO)
    db = client[DB]
    otp_hash = hashlib.sha256(b"123456").hexdigest()
    res = db.twofa_pending.update_one({"pending_id": pending}, {"$set": {"otp_hash": otp_hash}})
    if res.matched_count == 0:
        # try alternative key
        res2 = db.twofa_pending.update_one({"pending_token": pending}, {"$set": {"otp_hash": otp_hash}})
        if res2.matched_count == 0:
            raise RuntimeError(f"pending doc not found for {pending}")

    r2 = requests.post(f"{BASE}/api/auth/2fa/verify",
                       json={"pending_token": pending, "otp": "123456"}, timeout=30)
    r2.raise_for_status()
    tok = r2.json().get("session_token")
    if not tok:
        raise RuntimeError(f"No session_token: {r2.json()}")
    return tok

if __name__ == "__main__":
    print(login())
