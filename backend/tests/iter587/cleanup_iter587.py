"""Iter 587 cleanup."""
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

sub, emp = "user_test587sub", "user_test587emp"
r1 = db.users.delete_many({"user_id": {"$in": [sub, emp]}})
r2 = db.user_sessions.delete_many({"user_id": sub})
r3 = db.pending_approvals.delete_many({"target_user_id": emp})
r4 = db.salary_history.delete_many({"user_id": emp})
r5 = db.kyc_history.delete_many({"user_id": emp})
r6 = db.activity_log.delete_many({"user_id": sub})
print("users:", r1.deleted_count, "sessions:", r2.deleted_count,
      "approvals:", r3.deleted_count, "salary_hist:", r4.deleted_count,
      "kyc_hist:", r5.deleted_count, "activity:", r6.deleted_count)
