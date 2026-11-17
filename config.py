"""
Configuration settings for Covenant University Shuttle Bot.
Complies with SRS requirements (Locations, Fares, Rush Hour, and Discounts).
"""
import os
from datetime import datetime, time
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")

# Initial Pilot Approved Locations (FR-14 & FR-16)
# Note: Front of Engineering buildings is disabled per university policy until approved.
HALLS = [
    "Peter Hall",
    "Paul Hall",
    "John Hall",
    "Joseph Hall",
    "Daniel Hall",
    "Esther Hall",
    "Mary Hall",
    "Lydia Hall",
    "Dorcas Hall",
    "Deborah Hall"
]

DESTINATIONS = [
    "Class / Lecture Theatres (LT1 / LT2)",
    "CMSS Building",
    "CEDS",
    "CST Building",
    "CUCRID",
    "Caf 2",
    "PET Car Park",
    "Zenith Bank",
    "Access Bank",
    "ICT Centre",
    "Guest House",
    "Civil / Mech / EIE (Walkway Bay)"
]

# FR-21: Rush-hour period initially configured as 7:50 AM to 10:30 AM
RUSH_HOUR_START = time(7, 50)
RUSH_HOUR_END = time(10, 30)

BASE_FARE = 100        # Standard fare in Naira per passenger
RUSH_FARE = 150        # Rush-hour fare in Naira per passenger

def is_rush_hour() -> bool:
    """Checks if current time falls within morning rush hour (7:50 AM - 10:30 AM)"""
    current = datetime.now().time()
    return RUSH_HOUR_START <= current <= RUSH_HOUR_END

# FR-39: Promotional discount codes
DISCOUNT_CODES = {
    "WELCOME10": {"type": "percentage", "value": 10}, # 10% off
    "CU2026": {"type": "fixed", "value": 50}          # ₦50 off
}
