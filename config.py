"""
Configuration settings for Covenant University Shuttle Bot.
Complies with SRS requirements (Locations, Landmarks, Fares, Rush Hour, Discounts, and Driver Payouts).
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
    "Joshua Hall",
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

# FR-18: Helpful location descriptions and designated landmarks
LOCATION_LANDMARKS = {
    "Peter Hall": "Peter Hall Porters' Gate / Car Park",
    "Paul Hall": "Paul Hall Front Car Park",
    "John Hall": "John Hall Waiting Bay",
    "Joseph Hall": "Joseph Hall Quadrangle",
    "Daniel Hall": "Daniel Hall Main Drop-off Circle",
    "Joshua Hall": "Joshua Hall Turnaround",
    "Mary Hall": "Mary Hall Front Porch",
    "Lydia Hall": "Lydia Hall Walkway Entrance",
    "Dorcas Hall": "Dorcas Hall Front Gate",
    "Deborah Hall": "Deborah Hall Loading Bay",
    "Class / Lecture Theatres (LT1 / LT2)": "LT1/LT2 Walkway canopy",
    "CMSS Building": "CMSS Front steps & roundabout",
    "CEDS": "CEDS Main entrance walkway",
    "CST Building": "CST Courtyard car drop-off",
    "CUCRID": "CUCRID Main Entrance Reception",
    "Caf 2": "Cafeteria 2 Front Plaza",
    "PET Car Park": "PET Center Parking Lot",
    "Zenith Bank": "Zenith Bank ATM Forecourt",
    "Access Bank": "Access Bank Waiting Canopy",
    "ICT Centre": "ICT Building roundabout",
    "Guest House": "University Guest House Main Driveway",
    "Civil / Mech / EIE (Walkway Bay)": "Walkway Bay (outside Engineering security barrier)"
}

def get_landmark(loc: str) -> str:
    return LOCATION_LANDMARKS.get(loc, f"{loc} Designated Waiting Point")

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

# FR-44: Configurable Driver Payout Rule (Default 85% to driver, 15% platform fee)
DRIVER_PAYOUT_PERCENTAGE = 85.0

def calculate_driver_payout(fare: float) -> float:
    return round(fare * (DRIVER_PAYOUT_PERCENTAGE / 100.0), 2)

# FR-24: Ride acceptance timeout in seconds
REQUEST_TIMEOUT_SECONDS = 60

# NFR-24: Driver Privacy & Data Collection Notice
PRIVACY_NOTICE = (
    "📜 **Driver Privacy & Data Protection Notice (NDPR Compliant)**\n\n"
    "By registering as a dot.rider Driver Partner, you authorize Covenant University "
    "and dot.rider Dispatch to collect your legal name, phone number, vehicle details, "
    "and vehicle/identity documents solely for passenger transport verification, campus safety, "
    "and payout administration.\n\n"
    "Your documents will be stored securely and will never be shared publicly or used for "
    "unauthorized commercial purposes."
)

SUPPORT_PHONE = "0800-CAMPUS-SAFE"
DISPATCH_DESK = "Cafeteria 2 Security & Dispatch Annex"
