#!/usr/bin/env python3
"""Swap OTP hash in Mongo for automated 2FA tests. Usage: python swap_otp.py <pending_token>"""
import sys, os, hashlib
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
pending = sys.argv[1]
db = MongoClient(os.environ['MONGO_URL'])[os.environ.get('DB_NAME', 'test_database')]
r = db.twofa_pending.update_one(
    {'pending_id': pending},
    {'$set': {'otp_hash': hashlib.sha256(b'123456').hexdigest(), 'attempts': 0}}
)
print(f"matched={r.matched_count} modified={r.modified_count}")
