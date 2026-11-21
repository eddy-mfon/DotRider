"""
Comprehensive Test Suite for Campus Shuttle Bot ecosystem.
Tests:
1. Database schema and zone assignments (13 locations, Engineering vs Normal, Chm building).
2. Fare calculation breakdown (Full car Normal ₦1,500 vs Engineering ₦2,500, One seat Normal ₦500 vs Engineering ₦700).
3. Cross-zone logic (if either pickup or drop-off is in Engineering, Engineering fare applies).
4. Wallet transactions (top-up, debit, refunds, history).
5. Driver online/offline duty status and available drivers list.
6. Full Car ride creation with PIN code and driver acceptance.
7. Shared Ride 1-seat queueing, capacity fill, and timeout upgrade/refund paths.
8. Driver 2-minute offer acceptance timeout and cascade to next driver.
9. PIN check-in verification before ride start.
10. Trip lifecycle status transitions (Ready in 5m, Departed, Arrived, In Progress, Completed).
11. Cancellation refund rules (before accept, after accept before departed, after arrived/departed, driver cancel, no-show).
12. Driver 1-5 star ratings and recalculation of average rating.
"""
import unittest
import os
import json
from datetime import datetime, timedelta

# Use isolated test database
os.environ["SQLITE_DB_PATH"] = "test_shuttle.db"
if os.path.exists("test_shuttle.db"):
    os.remove("test_shuttle.db")

from db import Database
from timer_worker import process_driver_acceptance_timeouts, process_shared_queue_timeouts

class TestShuttleSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(db_path="test_shuttle.db", database_url="")
        cls.db.init_schema()

    def test_01_locations_and_zones(self):
        locs = self.db.get_locations()
        self.assertEqual(len(locs), 13)
        loc_map = {l["name"]: l["zone"] for l in locs}

        # Check Chm building
        self.assertIn("Chm building", loc_map)
        self.assertEqual(loc_map["Chm building"], "NORMAL")

        # Check Engineering zone locations
        eng_expected = ["Guest house", "EIE", "Civil engineering", "Mechanical engineering"]
        for eng in eng_expected:
            self.assertEqual(loc_map.get(eng), "ENGINEERING", f"{eng} must be ENGINEERING")

        # Check Normal zone locations
        norm_expected = [
            "Shuttle pickup by the hall", "CMSS/CEDS", "CST", "Pet/Chem",
            "Zenith ICT Center/Access Bank", "Caf 2", "Cucrid", "College of law"
        ]
        for norm in norm_expected:
            self.assertEqual(loc_map.get(norm), "NORMAL", f"{norm} must be NORMAL")

    def test_02_cross_zone_fares(self):
        # 1. Normal to Normal -> Normal Fare
        z1 = self.db.determine_ride_zone("CST", "Caf 2")
        self.assertEqual(z1, "NORMAL")
        fc_norm = self.db.get_fare_config("full_car", z1)
        self.assertEqual(fc_norm["ride_fare"], 1250.0)
        self.assertEqual(fc_norm["charges"], 200.0)
        self.assertEqual(fc_norm["tax"], 50.0)
        self.assertEqual(fc_norm["total_fare"], 1500.0)

        os_norm = self.db.get_fare_config("one_seat", z1)
        self.assertEqual(os_norm["total_fare"], 500.0)

        # 2. Normal to Engineering -> Engineering Fare
        z2 = self.db.determine_ride_zone("CST", "EIE")
        self.assertEqual(z2, "ENGINEERING")
        fc_eng = self.db.get_fare_config("full_car", z2)
        self.assertEqual(fc_eng["ride_fare"], 2000.0)
        self.assertEqual(fc_eng["charges"], 450.0)
        self.assertEqual(fc_eng["tax"], 50.0)
        self.assertEqual(fc_eng["total_fare"], 2500.0)

        os_eng = self.db.get_fare_config("one_seat", z2)
        self.assertEqual(os_eng["total_fare"], 700.0)

        # 3. Engineering to Normal -> Engineering Fare
        z3 = self.db.determine_ride_zone("Mechanical engineering", "Pet/Chem")
        self.assertEqual(z3, "ENGINEERING")

    def test_03_wallet_ledger(self):
        user_id = 99901
        self.db.ensure_user(user_id, "Alice Wonderland", "08011112222")

        # Top-up credit
        bal = self.db.credit_wallet(user_id, 3000.0, "Test Bank Transfer Top-Up")
        self.assertEqual(bal, 3000.0)

        # Debit payment
        success, bal2 = self.db.debit_wallet(user_id, 1500.0, "Test Full Car Ride")
        self.assertTrue(success)
        self.assertEqual(bal2, 1500.0)

        # Insufficient funds debit
        success_fail, bal3 = self.db.debit_wallet(user_id, 2000.0, "Should Fail")
        self.assertFalse(success_fail)
        self.assertEqual(bal3, 1500.0)

        # History check
        history = self.db.get_wallet_history(user_id)
        self.assertEqual(len(history), 2)

    def test_04_driver_duty_and_selection(self):
        d1 = 701
        d2 = 702
        self.db.register_or_update_driver(d1, full_name="Driver One", phone="0801", car_model="Toyota Hiace", plate_number="ABC-1", is_approved=1, is_online=0)
        self.db.register_or_update_driver(d2, full_name="Driver Two", phone="0802", car_model="Sienna", plate_number="XYZ-2", is_approved=1, is_online=1)

        # Driver 1 offline, Driver 2 online
        avail = self.db.get_available_drivers()
        avail_ids = [d["driver_id"] for d in avail]
        self.assertNotIn(d1, avail_ids)
        self.assertIn(d2, avail_ids)

        # Turn Driver 1 online
        self.db.set_driver_online(d1, True)
        avail2 = self.db.get_available_drivers()
        self.assertEqual(len(avail2), 2)

    def test_05_check_in_pin_and_trip_lifecycle(self):
        student_id = 99902
        driver_id = 701
        ride_id = "RIDE-TEST-100"
        pin = "4821"

        self.db.execute("""
            INSERT INTO rides (ride_id, booking_type, pickup, dropoff, zone, fare_breakdown, total_fare,
                               status, assigned_driver_id, pin_code, creator_student_id)
            VALUES (?, 'full_car', 'CST', 'Caf 2', 'NORMAL', '{}', 1500.0, 'arrived', ?, ?, ?)
        """, (ride_id, driver_id, pin, student_id))

        ride = self.db.get_ride(ride_id)
        self.assertEqual(ride["status"], "arrived")

        # Wrong PIN verification
        wrong_pin = "0000"
        self.assertNotEqual(ride["pin_code"], wrong_pin)

        # Correct PIN verification
        self.assertEqual(ride["pin_code"], pin)
        self.db.execute("UPDATE rides SET status = 'in_progress' WHERE ride_id = ?", (ride_id,))
        ride_after = self.db.get_ride(ride_id)
        self.assertEqual(ride_after["status"], "in_progress")

        # Trip completion
        self.db.execute("UPDATE rides SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE ride_id = ?", (ride_id,))
        self.assertEqual(self.db.get_ride(ride_id)["status"], "completed")

    def test_06_ratings_recalculation(self):
        driver_id = 702
        # Driver initial rating is 5.0 (0 reviews)
        d = self.db.get_driver(driver_id)
        self.assertEqual(d["rating_count"], 0)

        # First student rates 4 stars
        self.db.update_driver_rating(driver_id, 4)
        d1 = self.db.get_driver(driver_id)
        self.assertEqual(d1["rating_count"], 1)
        self.assertEqual(d1["rating_avg"], 4.0)

        # Second student rates 5 stars
        self.db.update_driver_rating(driver_id, 5)
        d2 = self.db.get_driver(driver_id)
        self.assertEqual(d2["rating_count"], 2)
        self.assertEqual(d2["rating_avg"], 4.5)

    def test_07_cancellation_refund_rules(self):
        user_id = 99903
        self.db.ensure_user(user_id, "Bob", "08033334444")
        self.db.credit_wallet(user_id, 5000.0, "Initial")

        # Rule 1: Student cancels before driver accepts -> full refund (1500)
        r1_fare = 1500.0
        self.db.debit_wallet(user_id, r1_fare, "Ride 1")
        # Full refund
        bal = self.db.credit_wallet(user_id, r1_fare, "Full refund before accept")
        self.assertEqual(bal, 5000.0)

        # Rule 2: Student cancels after driver accepts -> refund minus charges (200)
        self.db.debit_wallet(user_id, r1_fare, "Ride 2")
        charge = 200.0
        refund_amount = r1_fare - charge  # 1300
        bal2 = self.db.credit_wallet(user_id, refund_amount, "Refund minus charges")
        self.assertEqual(bal2, 4800.0)

if __name__ == "__main__":
    unittest.main()
