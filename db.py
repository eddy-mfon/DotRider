"""
Central Database Layer supporting both SQLite (WAL mode) and Supabase / PostgreSQL.
Handles all models: users, drivers, locations, fares_config, settings,
rides, ride_assignments, ride_seats, wallet_transactions, payments, ratings.
"""
import os
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "shuttle_bot.db")

class Database:
    def __init__(self, db_path: str = SQLITE_DB_PATH, database_url: str = DATABASE_URL):
        self.db_path = db_path
        self.database_url = database_url
        self.is_postgres = bool(database_url and database_url.startswith(("postgres://", "postgresql://")))

    def get_connection(self):
        if self.is_postgres:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(self.database_url, cursor_factory=psycopg2.extras.RealDictCursor)
            return conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for high concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            return conn

    def execute(self, query: str, params: tuple = ()) -> int:
        """Executes INSERT/UPDATE/DELETE and returns lastrowid or rowcount."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            # If postgres and using ? placeholders, translate ? to %s
            if self.is_postgres:
                query = query.replace("?", "%s")
            cur.execute(query, params)
            conn.commit()
            last_id = getattr(cur, "lastrowid", 0)
            cur.close()
            return last_id
        finally:
            conn.close()

    def fetchone(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if self.is_postgres:
                query = query.replace("?", "%s")
            cur.execute(query, params)
            row = cur.fetchone()
            cur.close()
            return dict(row) if row else None
        finally:
            conn.close()

    def fetchall(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if self.is_postgres:
                query = query.replace("?", "%s")
            cur.execute(query, params)
            rows = cur.fetchall()
            cur.close()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def init_schema(self):
        """Initializes tables and seeds default locations, fares, and system settings."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            
            # Users table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'student',
                full_name TEXT,
                phone TEXT,
                matric_no TEXT,
                email TEXT,
                wallet_balance REAL NOT NULL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Drivers table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS drivers (
                driver_id BIGINT PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                id_number TEXT,
                car_model TEXT NOT NULL,
                plate_number TEXT NOT NULL,
                capacity INTEGER NOT NULL DEFAULT 4,
                license_file_id TEXT,
                is_approved INTEGER NOT NULL DEFAULT 1,
                is_online INTEGER NOT NULL DEFAULT 0,
                rating_avg REAL NOT NULL DEFAULT 5.0,
                rating_count INTEGER NOT NULL DEFAULT 0,
                current_ride_id TEXT,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Locations table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                zone TEXT NOT NULL DEFAULT 'NORMAL'
            )
            """ if not self.is_postgres else """
            CREATE TABLE IF NOT EXISTS locations (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                zone TEXT NOT NULL DEFAULT 'NORMAL'
            )
            """)

            # Fares config table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS fares_config (
                booking_type TEXT NOT NULL,
                zone TEXT NOT NULL,
                ride_fare REAL NOT NULL,
                charges REAL NOT NULL,
                tax REAL NOT NULL,
                total_fare REAL NOT NULL,
                PRIMARY KEY (booking_type, zone)
            )
            """)

            # System settings table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """)

            # Rides table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS rides (
                ride_id TEXT PRIMARY KEY,
                booking_type TEXT NOT NULL,
                pickup TEXT NOT NULL,
                dropoff TEXT NOT NULL,
                zone TEXT NOT NULL,
                fare_breakdown TEXT NOT NULL,
                total_fare REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_driver',
                assigned_driver_id BIGINT,
                pin_code TEXT NOT NULL,
                creator_student_id BIGINT NOT NULL,
                seats_filled INTEGER NOT NULL DEFAULT 1,
                required_seats INTEGER NOT NULL DEFAULT 4,
                driver_offer_expires_at TIMESTAMP,
                queue_expires_at TIMESTAMP,
                departed_at TIMESTAMP,
                arrived_at TIMESTAMP,
                completed_at TIMESTAMP,
                cancelled_at TIMESTAMP,
                cancellation_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Ride Seats (for group / shared 1-seat rides)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS ride_seats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ride_id TEXT NOT NULL,
                student_id BIGINT NOT NULL,
                seat_count INTEGER NOT NULL DEFAULT 1,
                fare_paid REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'joined',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """ if not self.is_postgres else """
            CREATE TABLE IF NOT EXISTS ride_seats (
                id SERIAL PRIMARY KEY,
                ride_id TEXT NOT NULL,
                student_id BIGINT NOT NULL,
                seat_count INTEGER NOT NULL DEFAULT 1,
                fare_paid REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'joined',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Driver Ride Offer Queue (to cascade through available drivers)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS ride_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ride_id TEXT NOT NULL,
                driver_id BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """ if not self.is_postgres else """
            CREATE TABLE IF NOT EXISTS ride_offers (
                id SERIAL PRIMARY KEY,
                ride_id TEXT NOT NULL,
                driver_id BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Wallet Transactions table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id BIGINT NOT NULL,
                amount REAL NOT NULL,
                balance_after REAL NOT NULL,
                tx_type TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """ if not self.is_postgres else """
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                tx_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount REAL NOT NULL,
                balance_after REAL NOT NULL,
                tx_type TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Payments (Bank top-ups pending admin approval)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount REAL NOT NULL,
                reference TEXT,
                status TEXT NOT NULL DEFAULT 'pending_admin',
                reviewed_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Ratings table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ride_id TEXT NOT NULL,
                driver_id BIGINT NOT NULL,
                student_id BIGINT NOT NULL,
                stars INTEGER NOT NULL,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """ if not self.is_postgres else """
            CREATE TABLE IF NOT EXISTS ratings (
                id SERIAL PRIMARY KEY,
                ride_id TEXT NOT NULL,
                driver_id BIGINT NOT NULL,
                student_id BIGINT NOT NULL,
                stars INTEGER NOT NULL,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            conn.commit()
            cur.close()
        finally:
            conn.close()

        # Seed initial data
        self.seed_defaults()

    def seed_defaults(self):
        """Seeds locations, fare configs, and refund settings."""
        # Locations with Zone tagging
        # ENGINEERING zone = EIE, Civil engineering, Mechanical engineering, Guest house
        # All others = NORMAL zone
        locations = [
            ("Shuttle pickup by the hall", "NORMAL"),
            ("CMSS/CEDS", "NORMAL"),
            ("CST", "NORMAL"),
            ("Pet/Chem", "NORMAL"),
            ("Zenith ICT Center/Access Bank", "NORMAL"),
            ("Caf 2", "NORMAL"),
            ("Cucrid", "NORMAL"),
            ("College of law", "NORMAL"),
            ("Chm building", "NORMAL"),
            ("Guest house", "ENGINEERING"),
            ("EIE", "ENGINEERING"),
            ("Civil engineering", "ENGINEERING"),
            ("Mechanical engineering", "ENGINEERING"),
        ]

        for name, zone in locations:
            self.execute(
                "INSERT OR IGNORE INTO locations (name, zone) VALUES (?, ?)" if not self.is_postgres
                else "INSERT INTO locations (name, zone) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (name, zone)
            )

        # Fares table
        # Full car:
        # Normal zone: Ride fare 1250 + Charges 200 + Tax 50 = 1500
        # Engineering zone: Ride fare 2000 + Charges 450 + Tax 50 = 2500
        # Per seat:
        # Normal zone: 500 per seat (Fare 450, Charges 40, Tax 10)
        # Engineering zone: 700 per seat (Fare 630, Charges 50, Tax 20)
        fares = [
            ("full_car", "NORMAL", 1250.0, 200.0, 50.0, 1500.0),
            ("full_car", "ENGINEERING", 2000.0, 450.0, 50.0, 2500.0),
            ("one_seat", "NORMAL", 450.0, 40.0, 10.0, 500.0),
            ("one_seat", "ENGINEERING", 630.0, 50.0, 20.0, 700.0),
        ]

        for b_type, zone, r_fare, chg, tx, total in fares:
            self.execute(
                "INSERT OR REPLACE INTO fares_config (booking_type, zone, ride_fare, charges, tax, total_fare) VALUES (?, ?, ?, ?, ?, ?)" if not self.is_postgres
                else """INSERT INTO fares_config (booking_type, zone, ride_fare, charges, tax, total_fare) 
                        VALUES (%s, %s, %s, %s, %s, %s) 
                        ON CONFLICT (booking_type, zone) DO UPDATE 
                        SET ride_fare=EXCLUDED.ride_fare, charges=EXCLUDED.charges, tax=EXCLUDED.tax, total_fare=EXCLUDED.total_fare""",
                (b_type, zone, r_fare, chg, tx, total)
            )

        # System settings for rules and timers
        settings = {
            "driver_accept_seconds": "120",      # 2 minutes to accept
            "shared_timeout_minutes": "10",      # 10 minutes wait for car to fill
            "shared_min_dispatch_seats": "2",    # minimum seats to dispatch if timeout reached
            "full_car_max_wait_minutes": "6",    # 6 minutes max waiting after booking
            "driver_no_show_wait_minutes": "5",  # driver waits 5 mins after arrived
            "driver_late_cancel_minutes": "10",  # student can cancel if driver > 10m late
            "cancellation_charge": "200.0",      # deducted if student cancels after driver accepts
            "admin_bank_name": "Zenith Bank / Access Bank",
            "admin_account_number": "1234567890",
            "admin_account_name": "Campus Shuttle Operations",
        }

        for k, v in settings.items():
            self.execute(
                "INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)" if not self.is_postgres
                else "INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                (k, v)
            )

    # ------------------ Location & Zone Helpers ------------------
    def get_locations(self) -> List[Dict[str, Any]]:
        return self.fetchall("SELECT * FROM locations ORDER BY name ASC")

    def get_location_zone(self, name: str) -> str:
        row = self.fetchone("SELECT zone FROM locations WHERE name = ?", (name,))
        return row["zone"] if row else "NORMAL"

    def determine_ride_zone(self, pickup: str, dropoff: str) -> str:
        """Engineering zone price applies if EITHER pickup or dropoff is in Engineering zone."""
        p_zone = self.get_location_zone(pickup)
        d_zone = self.get_location_zone(dropoff)
        if p_zone == "ENGINEERING" or d_zone == "ENGINEERING":
            return "ENGINEERING"
        return "NORMAL"

    # ------------------ Fare Helpers ------------------
    def get_fare_config(self, booking_type: str, zone: str) -> Dict[str, Any]:
        row = self.fetchone(
            "SELECT * FROM fares_config WHERE booking_type = ? AND zone = ?",
            (booking_type, zone)
        )
        if row:
            return row
        # Fallback safety
        return {
            "booking_type": booking_type,
            "zone": zone,
            "ride_fare": 1250.0 if booking_type == "full_car" else 450.0,
            "charges": 200.0 if booking_type == "full_car" else 40.0,
            "tax": 50.0 if booking_type == "full_car" else 10.0,
            "total_fare": 1500.0 if booking_type == "full_car" else 500.0
        }

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.fetchone("SELECT value FROM system_settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        self.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)" if not self.is_postgres
            else "INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            (key, value)
        )

    # ------------------ User & Wallet Helpers ------------------
    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    def ensure_user(self, user_id: int, full_name: str = "", phone: str = "") -> Dict[str, Any]:
        u = self.get_user(user_id)
        if not u:
            self.execute(
                "INSERT INTO users (user_id, role, full_name, phone, wallet_balance) VALUES (?, 'student', ?, ?, 0.0)",
                (user_id, full_name, phone)
            )
            u = self.get_user(user_id)
        return u

    def update_user_profile(self, user_id: int, **kwargs):
        u = self.ensure_user(user_id)
        updates = []
        params = []
        for k, v in kwargs.items():
            updates.append(f"{k} = ?")
            params.append(v)
        if updates:
            params.append(user_id)
            self.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", tuple(params))

    def credit_wallet(self, user_id: int, amount: float, description: str) -> float:
        self.ensure_user(user_id)
        user = self.get_user(user_id)
        new_balance = round(user["wallet_balance"] + amount, 2)
        self.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?", (new_balance, user_id))
        self.execute(
            "INSERT INTO wallet_transactions (user_id, amount, balance_after, tx_type, description) VALUES (?, ?, ?, 'CREDIT', ?)",
            (user_id, amount, new_balance, description)
        )
        return new_balance

    def debit_wallet(self, user_id: int, amount: float, description: str) -> Tuple[bool, float]:
        self.ensure_user(user_id)
        user = self.get_user(user_id)
        if user["wallet_balance"] < amount:
            return False, user["wallet_balance"]
        new_balance = round(user["wallet_balance"] - amount, 2)
        self.execute("UPDATE users SET wallet_balance = ? WHERE user_id = ?", (new_balance, user_id))
        self.execute(
            "INSERT INTO wallet_transactions (user_id, amount, balance_after, tx_type, description) VALUES (?, ?, ?, 'DEBIT', ?)",
            (user_id, amount, new_balance, description)
        )
        return True, new_balance

    def get_wallet_history(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        return self.fetchall(
            "SELECT * FROM wallet_transactions WHERE user_id = ? ORDER BY tx_id DESC LIMIT ?",
            (user_id, limit)
        )

    # ------------------ Driver Management ------------------
    def get_driver(self, driver_id: int) -> Optional[Dict[str, Any]]:
        return self.fetchone("SELECT * FROM drivers WHERE driver_id = ?", (driver_id,))

    def register_or_update_driver(self, driver_id: int, **kwargs) -> Dict[str, Any]:
        d = self.get_driver(driver_id)
        if not d:
            cols = ["driver_id"] + list(kwargs.keys())
            placeholders = ["?"] * len(cols)
            vals = [driver_id] + list(kwargs.values())
            self.execute(
                f"INSERT INTO drivers ({', '.join(cols)}) VALUES ({', '.join(placeholders)})",
                tuple(vals)
            )
        else:
            updates = []
            params = []
            for k, v in kwargs.items():
                updates.append(f"{k} = ?")
                params.append(v)
            if updates:
                params.append(driver_id)
                self.execute(f"UPDATE drivers SET {', '.join(updates)} WHERE driver_id = ?", tuple(params))
        return self.get_driver(driver_id)

    def set_driver_online(self, driver_id: int, is_online: bool):
        self.execute("UPDATE drivers SET is_online = ? WHERE driver_id = ?", (1 if is_online else 0, driver_id))

    def get_available_drivers(self) -> List[Dict[str, Any]]:
        """Returns drivers who are approved, online, and not currently on an active ride."""
        return self.fetchall(
            "SELECT * FROM drivers WHERE is_approved = 1 AND is_online = 1 AND current_ride_id IS NULL ORDER BY rating_avg DESC"
        )

    def update_driver_rating(self, driver_id: int, stars: int):
        d = self.get_driver(driver_id)
        if not d:
            return
        curr_count = d["rating_count"]
        curr_avg = d["rating_avg"]
        new_count = curr_count + 1
        new_avg = round(((curr_avg * curr_count) + stars) / new_count, 2)
        self.execute("UPDATE drivers SET rating_avg = ?, rating_count = ? WHERE driver_id = ?", (new_avg, new_count, driver_id))

    # ------------------ Ride Operations ------------------
    def get_ride(self, ride_id: str) -> Optional[Dict[str, Any]]:
        return self.fetchone("SELECT * FROM rides WHERE ride_id = ?", (ride_id,))

    def get_active_student_ride(self, student_id: int) -> Optional[Dict[str, Any]]:
        """Returns an ongoing ride for the student if any."""
        return self.fetchone("""
            SELECT r.* FROM rides r
            LEFT JOIN ride_seats rs ON r.ride_id = rs.ride_id
            WHERE (r.creator_student_id = ? OR rs.student_id = ?)
            AND r.status IN ('pending_driver', 'driver_offered', 'driver_accepted', 'departed', 'arrived', 'in_progress', 'queue_waiting')
            ORDER BY r.created_at DESC LIMIT 1
        """, (student_id, student_id))

    def get_active_driver_ride(self, driver_id: int) -> Optional[Dict[str, Any]]:
        """Returns the active trip the driver is currently assigned to."""
        return self.fetchone("""
            SELECT * FROM rides
            WHERE assigned_driver_id = ?
            AND status IN ('driver_offered', 'driver_accepted', 'departed', 'arrived', 'in_progress')
            ORDER BY created_at DESC LIMIT 1
        """, (driver_id,))

    def get_ride_seats(self, ride_id: str) -> List[Dict[str, Any]]:
        return self.fetchall("SELECT * FROM ride_seats WHERE ride_id = ? AND status = 'joined'", (ride_id,))

    def add_ride_offer(self, ride_id: str, driver_id: int):
        self.execute("INSERT INTO ride_offers (ride_id, driver_id, status) VALUES (?, ?, 'pending')", (ride_id, driver_id))

    def get_rejected_driver_ids_for_ride(self, ride_id: str) -> List[int]:
        rows = self.fetchall("SELECT driver_id FROM ride_offers WHERE ride_id = ? AND status = 'declined'", (ride_id,))
        return [r["driver_id"] for r in rows]

    def mark_driver_offer_status(self, ride_id: str, driver_id: int, status: str):
        self.execute(
            "UPDATE ride_offers SET status = ? WHERE ride_id = ? AND driver_id = ?",
            (status, ride_id, driver_id)
        )

# Global database singleton
db = Database()
if __name__ == "__main__":
    db.init_schema()
    print("Database schema successfully initialized!")
    print(f"Total Locations: {len(db.get_locations())}")
