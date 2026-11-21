"""
Configuration settings for Campus Shuttle Bot ecosystem.
"""
import os
from dotenv import load_dotenv

load_dotenv()

STUDENT_BOT_TOKEN = os.getenv("STUDENT_BOT_TOKEN", "").strip()
DRIVER_BOT_TOKEN = os.getenv("DRIVER_BOT_TOKEN", "").strip()
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "shuttle_bot.db")

SUPPORT_PHONE = "0800-CAMPUS-SAFE"
DISPATCH_DESK = "Cafeteria 2 Security & Dispatch Annex"
