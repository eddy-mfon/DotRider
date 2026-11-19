"""
Configuration settings for Covenant University Shuttle Bot.
Approved pilot campus locations, flat fares, landmarks, and driver payouts.
"""
import os
from datetime import datetime, time
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")

# Pilot Approved Campus Locations (Halls removed, Chapel Shuttle Stand added)
CAMPUS_LOCATIONS = [
    "Chapel Shuttle Stand",
    "Lecture Theatres",
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
    "Civil / Mech / EIE",
]

# Aliases for backwards compatibility
DESTINATIONS = CAMPUS_LOCATIONS
HALLS = CAMPUS_LOCATIONS

# Location landmarks
LOCATION_LANDMARKS = {
    "Chapel Shuttle Stand": "Chapel Main Car Park / Shuttle Loading Bay",
    "Lecture Theatres": "Lecture Theatre Walkway Canopy",
    "CMSS Building": "CMSS Front Steps & Roundabout",
    "CEDS": "CEDS Walkway Entrance",
    "CST Building": "CST Courtyard Drop-off Point",
    "CUCRID": "CUCRID Main Reception Forecourt",
    "Caf 2": "Cafeteria 2 Front Plaza",
    "PET Car Park": "PET Car Park Drop-off Bay",
    "Zenith Bank": "Zenith Bank Bus Stop",
    "Access Bank": "Access Bank Bus Stop",
    "ICT Centre": "ICT Centre Main Entrance",
    "Guest House": "Guest House Gate",
    "Civil / Mech / EIE": "Engineering Building Forecourt",
}

def get_landmark(loc: str) -> str:
    return LOCATION_LANDMARKS.get(loc, f"{loc} Designated Waiting Bay")

# Flat fare rule: ₦200 per passenger
BASE_FARE = 200
RUSH_FARE = 200

def is_rush_hour() -> bool:
    return False

# FR-39: Promotional discount codes
DISCOUNT_CODES = {
    "WELCOME10": {"type": "percentage", "value": 10},
    "CU2026": {"type": "fixed", "value": 50}
}

# FR-44: Configurable Driver Payout Rule (85% to driver, 15% platform fee)
DRIVER_PAYOUT_PERCENTAGE = 85.0

def calculate_driver_payout(fare: float) -> float:
    return round(fare * (DRIVER_PAYOUT_PERCENTAGE / 100.0), 2)

REQUEST_TIMEOUT_SECONDS = 60

PRIVACY_NOTICE = (
    "📜 **Driver Privacy & Data Protection Notice (NDPR Compliant)**\n\n"
    "By registering as a dot.rider Driver Partner, you authorize Covenant University "
    "and dot.rider Dispatch to collect your legal name, phone number, vehicle details, "
    "and vehicle/identity documents solely for passenger transport verification, campus safety, "
    "and payout administration.\n\n"
    "Your documents are stored securely and never shared publicly."
)

SUPPORT_PHONE = "0800-CAMPUS-SAFE"
DISPATCH_DESK = "Cafeteria 2 Security & Dispatch Annex"
