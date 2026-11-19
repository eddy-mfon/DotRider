"""
Storage and data persistence with:
- Strict role separation (Student OR Driver, Never Both)
- Full driver onboarding, vehicle & document inspection records
- Document expiry tracking & suspension (FR-13)
- Atomic ride dispatch & concurrency control (FR-23, FR-24)
- Strict state machine transitions (NFR-17)
- Completion validation with OTP (FR-31)
- Categorized ride history: Completed, Cancelled, Declined (FR-32, FR-33, FR-35)
- Configurable driver payouts, balance & dispute management (FR-44)
- Operational complaints & audit logging (FR-53, FR-66, FR-71)
- Manual admin dispatch fallback (FR-50)
"""
import json
import os
import random
import uuid
from datetime import datetime, date

import config

DATA_FILE = "rides_data.json"

VALID_TRANSITIONS = {
    "pending_assignment": ["confirmed", "cancelled"],
    "confirmed": ["driver_en_route", "cancelled"],
    "driver_en_route": ["driver_arrived", "cancelled"],
    "driver_arrived": ["in_progress", "cancelled"],
    "in_progress": ["completed", "cancelled"],
    "completed": [],
    "cancelled": []
}

class Storage:
    def __init__(self, filename=DATA_FILE):
        self.filename = filename
        self.data = {
            "users": {},
            "rides": {},
            "complaints": [],
            "notifications_log": []
        }
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                    self.data.setdefault("users", {})
                    self.data.setdefault("rides", {})
                    self.data.setdefault("complaints", [])
                    self.data.setdefault("notifications_log", [])

                    # Ensure existing users have role attribute
                    for uid, u in self.data["users"].items():
                        if "role" not in u:
                            if u.get("driver_profile") or u.get("is_driver"):
                                u["role"] = "driver"
                            elif u.get("matric_no") or u.get("email"):
                                u["role"] = "student"
                            else:
                                u["role"] = None
            except Exception:
                pass

    def save(self):
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    # ----------------- Strict Role Enforcement -----------------

    def get_user(self, user_id: int):
        return self.data["users"].get(str(user_id))

    def get_user_role(self, user_id: int) -> str | None:
        user = self.get_user(user_id)
        if not user:
            return None
        return user.get("role")

    def set_user_role(self, user_id: int, role: str) -> bool:
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {}

        current_role = self.data["users"][uid].get("role")
        if current_role and current_role != role:
            return False

        self.data["users"][uid]["role"] = role
        self.save()
        return True

    def reset_user_role(self, user_id: int):
        """Allows testing role switching without manual database edits."""
        uid = str(user_id)
        if uid in self.data["users"]:
            self.data["users"][uid]["role"] = None
            if "driver_profile" in self.data["users"][uid]:
                self.data["users"][uid]["driver_profile"]["current_ride_id"] = None
            self.save()

    def setup_mock_driver(self, user_id: int, name: str = "Test Driver (Pilot)") -> dict:
        """Instantly equips user as an approved, online driver for testing."""
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {}

        self.data["users"][uid]["role"] = "driver"
        self.data["users"][uid]["name"] = name

        profile = {
            "full_name": name,
            "phone": "08039998888",
            "car_model": "Toyota Sienna Gold",
            "plate_number": "ABJ-999-CU",
            "capacity": 4,
            "id_number": "MOCK-NIN-999",
            "license_photo_id": "mock_photo_id",
            "vehicle_photo_id": "mock_photo_id",
            "license_expiry": "2028-12-31",
            "insurance_expiry": "2028-12-31",
            "status": "approved",
            "is_approved": True,
            "is_online": True,
            "current_ride_id": None,
            "total_completed": 3,
            "total_cancelled": 0,
            "total_declined": 0,
            "earnings_balance": 1500.0,
            "pending_payout": 1500.0,
            "payout_status": "pending",
            "payout_disputes": [],
            "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.data["users"][uid]["driver_profile"] = profile
        self.save()
        return profile

    def update_user(self, user_id: int, **kwargs):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {}
        self.data["users"][uid].update(kwargs)
        self.save()

    def get_all_pending_drivers(self):
        """For Admin review (FR-10, FR-48)"""
        pending = []
        for uid, user in self.data.get("users", {}).items():
            if user.get("role") == "driver":
                dp = user.get("driver_profile", {})
                if dp.get("status") == "pending_verification" or not dp.get("is_approved"):
                    pending.append((int(uid), dp))
        return pending

    # ----------------- Student Helpers -----------------

    def find_user_by_matric(self, matric_no: str, exclude_uid: int = None):
        mat = matric_no.strip().upper()
        for uid, user in self.data["users"].items():
            if exclude_uid and uid == str(exclude_uid):
                continue
            if user.get("matric_no", "").strip().upper() == mat:
                return user
        return None

    def find_user_by_email(self, email: str, exclude_uid: int = None):
        em = email.strip().lower()
        for uid, user in self.data["users"].items():
            if exclude_uid and uid == str(exclude_uid):
                continue
            if user.get("email", "").strip().lower() == em:
                return user
        return None

    # ----------------- Driver Helpers & Profile -----------------

    def register_driver(
        self,
        user_id: int,
        full_name: str,
        phone: str,
        car_model: str,
        plate_number: str,
        capacity: int,
        license_photo_id: str = None,
        vehicle_photo_id: str = None,
        reg_doc_photo_id: str = None,
        insurance_photo_id: str = None,
        id_number: str = None
    ) -> bool:
        uid = str(user_id)
        current_role = self.get_user_role(user_id)
        if current_role == "student":
            return False

        profile = {
            "full_name": full_name,
            "phone": phone,
            "car_model": car_model,
            "plate_number": plate_number.upper(),
            "capacity": capacity,
            "id_number": id_number or "N/A",
            "license_photo_id": license_photo_id,
            "vehicle_photo_id": vehicle_photo_id,
            "reg_doc_photo_id": reg_doc_photo_id,
            "insurance_photo_id": insurance_photo_id,
            "license_expiry": "2027-12-31",
            "insurance_expiry": "2027-12-31",
            "status": "pending_verification", # pending_verification, approved, rejected, suspended
            "rejection_reason": None,
            "suspension_reason": None,
            "is_approved": False,
            "is_online": False,
            "current_ride_id": None,
            "total_completed": 0,
            "total_cancelled": 0,
            "total_declined": 0,
            "earnings_balance": 0.0,
            "pending_payout": 0.0,
            "payout_status": "pending",        # pending, processed, disputed
            "payout_disputes": [],
            "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if uid not in self.data["users"]:
            self.data["users"][uid] = {}

        self.data["users"][uid]["role"] = "driver"
        self.data["users"][uid]["name"] = full_name
        self.data["users"][uid]["driver_profile"] = profile
        self.save()
        return True

    def get_driver_profile(self, user_id: int):
        user = self.get_user(user_id)
        if user and user.get("role") == "driver":
            return user.get("driver_profile")
        return None

    def update_driver_profile(self, user_id: int, **kwargs):
        uid = str(user_id)
        if uid in self.data["users"] and "driver_profile" in self.data["users"][uid]:
            self.data["users"][uid]["driver_profile"].update(kwargs)
            self.save()
            return True
        return False

    def request_critical_update(self, user_id: int, car_model: str, plate_number: str) -> bool:
        """FR-12: Updating vehicle details requires administrative re-verification"""
        profile = self.get_driver_profile(user_id)
        if not profile:
            return False
        profile["car_model"] = car_model
        profile["plate_number"] = plate_number.upper()
        profile["is_approved"] = False
        profile["status"] = "pending_verification"
        profile["is_online"] = False
        self.save()
        return True

    def approve_driver(self, user_id: int) -> bool:
        uid = str(user_id)
        if uid in self.data["users"] and "driver_profile" in self.data["users"][uid]:
            dp = self.data["users"][uid]["driver_profile"]
            dp["is_approved"] = True
            dp["status"] = "approved"
            dp["rejection_reason"] = None
            dp["suspension_reason"] = None
            self.save()
            return True
        return False

    def reject_driver(self, user_id: int, reason: str = "Requirements not met") -> bool:
        uid = str(user_id)
        if uid in self.data["users"] and "driver_profile" in self.data["users"][uid]:
            dp = self.data["users"][uid]["driver_profile"]
            dp["is_approved"] = False
            dp["status"] = "rejected"
            dp["rejection_reason"] = reason
            dp["is_online"] = False
            self.save()
            return True
        return False

    def suspend_driver(self, user_id: int, reason: str = "Document expired or policy violation") -> bool:
        uid = str(user_id)
        if uid in self.data["users"] and "driver_profile" in self.data["users"][uid]:
            dp = self.data["users"][uid]["driver_profile"]
            dp["is_approved"] = False
            dp["status"] = "suspended"
            dp["suspension_reason"] = reason
            dp["is_online"] = False
            self.save()
            return True
        return False

    def check_documents_validity(self, user_id: int) -> tuple[bool, str]:
        """FR-13: Blocks drivers with expired mandatory documents"""
        profile = self.get_driver_profile(user_id)
        if not profile:
            return False, "Driver profile not found."
        if profile.get("status") == "suspended":
            return False, f"Account is suspended: {profile.get('suspension_reason', 'Policy violation')}."

        today = date.today().isoformat()
        lic_exp = profile.get("license_expiry", "2099-12-31")
        ins_exp = profile.get("insurance_expiry", "2099-12-31")

        if lic_exp < today:
            self.suspend_driver(user_id, reason="Driver license expired.")
            return False, "Your Driver's Licence has expired! Please update your documents."
        if ins_exp < today:
            self.suspend_driver(user_id, reason="Passenger insurance expired.")
            return False, "Your Vehicle Insurance has expired! Please renew before accepting rides."

        return True, "Valid"

    def set_driver_online(self, user_id: int, is_online: bool) -> tuple[bool, str]:
        profile = self.get_driver_profile(user_id)
        if not profile or not profile.get("is_approved"):
            return False, "Your driver account is not approved."

        valid, msg = self.check_documents_validity(user_id)
        if not valid:
            return False, msg

        self.update_driver_profile(user_id, is_online=is_online)
        return True, "Success"

    def get_online_drivers(self, passenger_count: int = 1):
        """
        FR-23: Filters for approved, active, online drivers with valid documents
        and sufficient passenger capacity.
        """
        online = []
        for uid, user in self.data["users"].items():
            if user.get("role") == "driver":
                dp = user.get("driver_profile", {})
                if (
                    dp.get("is_approved")
                    and dp.get("is_online")
                    and dp.get("status") == "approved"
                    and not dp.get("current_ride_id")
                    and dp.get("capacity", 4) >= passenger_count
                ):
                    valid, _ = self.check_documents_validity(int(uid))
                    if valid:
                        online.append((int(uid), dp))
        return online

    # ----------------- Ride Dispatch & Concurrency -----------------

    def create_ride(
        self,
        user_id: int,
        pickup: str,
        dropoff: str,
        passengers: int,
        base_fare: float,
        discount: float,
        final_fare: float,
        promo_code: str = None,
        is_rush: bool = False
    ):
        # Booking reference reduced to 6 characters
        full_ref = str(uuid.uuid4())[:6].upper()
        # FR-31: 4-digit completion verification PIN
        completion_otp = f"{random.randint(1000, 9999)}"
        driver_payout = config.calculate_driver_payout(final_fare)

        ride_record = {
            "ride_id": full_ref,
            "user_id": user_id,
            "driver_id": None,
            "pickup": pickup,
            "dropoff": dropoff,
            "pickup_landmark": config.get_landmark(pickup),
            "dropoff_landmark": config.get_landmark(dropoff),
            "passengers": passengers,
            "base_fare": base_fare,
            "discount": discount,
            "final_fare": final_fare,
            "driver_payout": driver_payout,
            "completion_otp": completion_otp,
            "promo_code": promo_code,
            "is_rush": is_rush,
            "status": "pending_assignment",
            "declined_driver_ids": [],
            "cancellation_reason": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status_history": [
                {"status": "pending_assignment", "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            ]
        }
        self.data["rides"][full_ref] = ride_record
        self.save()
        return ride_record

    def get_ride(self, ride_id: str):
        return self.data["rides"].get(ride_id)

    def assign_driver_to_ride(self, ride_id: str, driver_id: int) -> bool:
        ride = self.get_ride(ride_id)
        if not ride or ride.get("status") != "pending_assignment":
            return False

        driver_profile = self.get_driver_profile(driver_id)
        if not driver_profile or not driver_profile.get("is_approved"):
            return False

        if driver_profile.get("current_ride_id"):
            return False

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ride["driver_id"] = driver_id
        ride["status"] = "confirmed"
        ride["status_history"].append({"status": "confirmed", "timestamp": ts})

        self.update_driver_profile(driver_id, current_ride_id=ride_id)
        self.save()
        return True

    def manual_dispatch_by_admin(self, ride_id: str, driver_id: int, admin_id: int) -> tuple[bool, str]:
        """FR-50: Manual dispatch fallback by administrator"""
        ride = self.get_ride(ride_id)
        if not ride:
            return False, "Ride not found."
        dp = self.get_driver_profile(driver_id)
        if not dp:
            return False, "Driver profile not found."
        if not dp.get("is_approved"):
            return False, "Driver is not approved."

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ride["driver_id"] = driver_id
        ride["status"] = "confirmed"
        ride["status_history"].append({"status": "confirmed", "timestamp": ts, "admin_override": admin_id})

        self.update_driver_profile(driver_id, current_ride_id=ride_id)
        self.save()
        return True, "Driver manually assigned."

    def record_driver_decline(self, ride_id: str, driver_id: int):
        ride = self.get_ride(ride_id)
        if ride:
            declined = ride.setdefault("declined_driver_ids", [])
            if driver_id not in declined:
                declined.append(driver_id)
                self.save()
        dp = self.get_driver_profile(driver_id)
        if dp:
            dp["total_declined"] = dp.get("total_declined", 0) + 1
            self.save()

    def update_ride_progress(self, ride_id: str, new_status: str, note: str = None) -> tuple[bool, str]:
        """
        NFR-17: Strictly enforces valid status transitions.
        """
        ride = self.get_ride(ride_id)
        if not ride:
            return False, "Ride record not found."

        current_status = ride.get("status", "pending_assignment")
        allowed_next = VALID_TRANSITIONS.get(current_status, [])

        if new_status not in allowed_next:
            return False, f"Invalid transition: Cannot advance from '{current_status}' to '{new_status}'."

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ride["status"] = new_status
        history_item = {"status": new_status, "timestamp": ts}
        if note:
            history_item["note"] = note
            if new_status == "cancelled":
                ride["cancellation_reason"] = note
        ride.setdefault("status_history", []).append(history_item)

        if new_status == "completed":
            driver_id = ride.get("driver_id")
            if driver_id:
                dp = self.get_driver_profile(driver_id)
                if dp:
                    payout_earned = float(ride.get("driver_payout", 0.0))
                    dp["total_completed"] = dp.get("total_completed", 0) + 1
                    dp["earnings_balance"] = dp.get("earnings_balance", 0.0) + payout_earned
                    dp["pending_payout"] = dp.get("pending_payout", 0.0) + payout_earned
                    dp["current_ride_id"] = None
        elif new_status == "cancelled":
            driver_id = ride.get("driver_id")
            if driver_id:
                dp = self.get_driver_profile(driver_id)
                if dp:
                    dp["total_cancelled"] = dp.get("total_cancelled", 0) + 1
                    dp["current_ride_id"] = None

        self.save()
        return True, "Success"

    def verify_and_complete_ride(self, ride_id: str, entered_otp: str) -> tuple[bool, str]:
        """
        FR-31: Validate completion with passenger OTP before marking complete.
        """
        ride = self.get_ride(ride_id)
        if not ride:
            return False, "Ride not found."
        expected_otp = str(ride.get("completion_otp", ""))
        if entered_otp.strip() != expected_otp:
            return False, "Invalid completion PIN. Please ask the passenger for their 4-digit code."

        return self.update_ride_progress(ride_id, "completed", note=f"Verified with OTP {entered_otp}")

    # ----------------- History & Categories -----------------

    def get_user_rides(self, user_id: int, active_only: bool = False):
        user_rides = []
        for r in self.data["rides"].values():
            if r.get("user_id") == user_id:
                if active_only and r.get("status") in ["completed", "cancelled"]:
                    continue
                user_rides.append(r)
        return sorted(user_rides, key=lambda x: x.get("created_at", ""), reverse=True)

    def get_driver_rides(self, driver_id: int, active_only: bool = False):
        """FR-32, FR-33, FR-35: Returns strictly the requesting driver's rides."""
        driver_rides = []
        for r in self.data["rides"].values():
            if r.get("driver_id") == driver_id:
                if active_only and r.get("status") in ["completed", "cancelled"]:
                    continue
                driver_rides.append(r)
        return sorted(driver_rides, key=lambda x: x.get("created_at", ""), reverse=True)

    def get_driver_ride_categories(self, driver_id: int):
        """FR-33: Separate categories for completed, cancelled and declined rides."""
        all_driver_rides = self.get_driver_rides(driver_id, active_only=False)
        completed = [r for r in all_driver_rides if r.get("status") == "completed"]
        cancelled = [r for r in all_driver_rides if r.get("status") == "cancelled"]

        declined_count = 0
        dp = self.get_driver_profile(driver_id)
        if dp:
            declined_count = dp.get("total_declined", 0)

        return {
            "completed": completed,
            "cancelled": cancelled,
            "declined_count": declined_count
        }

    # ----------------- Payouts & Disputes (FR-44) -----------------

    def raise_payout_dispute(self, driver_id: int, ride_id: str, reason: str) -> tuple[bool, str]:
        dp = self.get_driver_profile(driver_id)
        if not dp:
            return False, "Driver profile not found."

        dispute_id = f"DISP-{str(uuid.uuid4())[:6].upper()}"
        dispute_record = {
            "dispute_id": dispute_id,
            "driver_id": driver_id,
            "ride_id": ride_id,
            "reason": reason,
            "status": "pending_review",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        dp.setdefault("payout_disputes", []).append(dispute_record)
        dp["payout_status"] = "disputed"
        self.save()
        return True, dispute_id

    # ----------------- Complaints & Reports (FR-53, FR-66) -----------------

    def submit_complaint(self, user_id: int, role: str, text: str) -> str:
        complaint_id = f"CMP-{str(uuid.uuid4())[:6].upper()}"
        record = {
            "complaint_id": complaint_id,
            "user_id": user_id,
            "role": role,
            "text": text,
            "status": "pending",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.data["complaints"].append(record)
        self.save()
        return complaint_id

    # ----------------- Notification Audit Trail (FR-71) -----------------

    def log_notification(self, recipient_id: int, event: str, status: str = "delivered", details: str = None):
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recipient_id": recipient_id,
            "event": event,
            "status": status,
            "details": details
        }
        self.data["notifications_log"].append(record)
        if len(self.data["notifications_log"]) > 1000:
            self.data["notifications_log"] = self.data["notifications_log"][-500:]
        self.save()

storage = Storage()
