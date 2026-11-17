"""
Storage and data persistence with FR-01/FR-02 verification and duplicate prevention.
"""
import json
import os
import uuid
from datetime import datetime

DATA_FILE = "rides_data.json"

class Storage:
    def __init__(self, filename=DATA_FILE):
        self.filename = filename
        self.data = {
            "users": {},   # user_id: {"name": ..., "email": ..., "matric_no": ..., "is_verified": bool}
            "rides": {}    # ride_id: {"user_id": ..., "pickup": ..., "dropoff": ..., "status": ..., ...}
        }
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass

    def save(self):
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def get_user(self, user_id: int):
        return self.data["users"].get(str(user_id))

    def update_user(self, user_id: int, **kwargs):
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {}
        self.data["users"][uid].update(kwargs)
        self.save()

    def find_user_by_matric(self, matric_no: str, exclude_uid: int = None):
        """FR-06: Duplicate prevention by matriculation number"""
        mat = matric_no.strip().upper()
        for uid, user in self.data["users"].items():
            if exclude_uid and uid == str(exclude_uid):
                continue
            if user.get("matric_no", "").strip().upper() == mat:
                return user
        return None

    def find_user_by_email(self, email: str, exclude_uid: int = None):
        """FR-06: Duplicate prevention by email"""
        em = email.strip().lower()
        for uid, user in self.data["users"].items():
            if exclude_uid and uid == str(exclude_uid):
                continue
            if user.get("email", "").strip().lower() == em:
                return user
        return None

    def create_ride(self, user_id: int, pickup: str, dropoff: str, passengers: int, base_fare: float, discount: float, final_fare: float, promo_code: str = None, is_rush: bool = False):
        ride_id = str(uuid.uuid4())[:8].upper()
        full_ref = f"DOT-{ride_id}"
        ride_record = {
            "ride_id": full_ref,
            "user_id": user_id,
            "pickup": pickup,
            "dropoff": dropoff,
            "passengers": passengers,
            "base_fare": base_fare,
            "discount": discount,
            "final_fare": final_fare,
            "promo_code": promo_code,
            "is_rush": is_rush,
            "status": "pending_assignment", # pending_assignment, confirmed, completed, cancelled
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.data["rides"][full_ref] = ride_record
        self.save()
        return ride_record

    def get_ride(self, ride_id: str):
        return self.data["rides"].get(ride_id)

    def update_ride_status(self, ride_id: str, status: str):
        if ride_id in self.data["rides"]:
            self.data["rides"][ride_id]["status"] = status
            self.save()
            return True
        return False

    def get_user_rides(self, user_id: int, active_only: bool = False):
        user_rides = []
        for r in self.data["rides"].values():
            if r.get("user_id") == user_id:
                if active_only and r.get("status") in ["completed", "cancelled"]:
                    continue
                user_rides.append(r)
        return sorted(user_rides, key=lambda x: x.get("created_at", ""), reverse=True)

storage = Storage()
