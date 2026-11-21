"""
Student Telegram Bot.
Handles:
- Student Registration & Profile
- Wallet Top-up (via bank transfer) and Wallet Balance
- Booking: Full Car (6-min wait notice) and Shared Seat (10-min queue countdown)
- Location selection (13 locations, Zone tagging)
- Transparent Fare Breakdown (ride fare, charges, tax, total)
- Available Drivers list with average rating selection
- Unique check-in PIN code display
- Ride Status updates (driver en route, departed, arrived)
- Cancellations with refund policies
- Post-ride 1-5 star driver rating with optional comment
- Admin commands for payment confirmation, manual refunds, and stuck rides view
"""
import asyncio
import json
import logging
import random
import string
import uuid
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

import config
from db import db
import notifier
from timer_worker import run_timer_worker_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("student_bot")

dp = Dispatcher(storage=MemoryStorage())
bot_instance: Bot | None = None

# ----------------- FSM States -----------------

class StudentRegFlow(StatesGroup):
    entering_name = State()
    entering_phone = State()
    entering_matric = State()

class WalletTopUpFlow(StatesGroup):
    entering_amount = State()
    submitting_reference = State()

class BookingFlow(StatesGroup):
    choosing_pickup = State()
    choosing_dropoff = State()
    choosing_package = State()
    confirming_payment = State()
    selecting_driver = State()

class RatingFlow(StatesGroup):
    entering_comment = State()

# ----------------- Keyboards -----------------

def main_student_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚖 Book a Shuttle"), KeyboardButton(text="💳 My Wallet")],
            [KeyboardButton(text="📋 My Active Ride"), KeyboardButton(text="📜 Ride History")],
            [KeyboardButton(text="ℹ️ Campus Locations & Fares"), KeyboardButton(text="📞 Support & Info")]
        ],
        resize_keyboard=True
    )

def cancel_flow_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
    ])

# ----------------- Helpers -----------------

def generate_pin() -> str:
    """Generates a secure 4-digit check-in PIN."""
    return f"{random.randint(1000, 9999)}"

def generate_ride_id() -> str:
    """Generates a clean 6-character uppercase alphanumeric Ride ID (e.g., A7K9X2)."""
    chars = string.ascii_uppercase + string.digits
    # Avoid ambiguous characters if desired, but 6 alphanumeric chars gives >2 billion combinations
    return ''.join(random.choices(chars, k=6))

# ----------------- Start & Welcome -----------------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    user = db.get_user(uid)

    if not user or not user.get("full_name"):
        db.ensure_user(uid)
        await message.answer(
            "👋 <b>Welcome to Campus Shuttle Service!</b>\n\n"
            "To book rides quickly and safely, let's complete a quick 1-minute registration.\n\n"
            "Please enter your <b>Full Name</b> (e.g., Samuel Adeyemi):",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(StudentRegFlow.entering_name)
    else:
        await message.answer(
            f"👋 Welcome back, <b>{user['full_name']}</b>!\n"
            f"💳 Wallet Balance: <b>₦{user['wallet_balance']:,.2f}</b>\n\n"
            f"Where would you like to go today?",
            reply_markup=main_student_menu(),
            parse_mode=ParseMode.HTML
        )

# ----------------- Student Registration -----------------

@dp.message(StudentRegFlow.entering_name)
async def reg_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Please enter a valid full name.")
        return
    await state.update_data(full_name=name)
    await message.answer("Great! Now enter your <b>Phone Number</b> (e.g., 08012345678):", parse_mode=ParseMode.HTML)
    await state.set_state(StudentRegFlow.entering_phone)

@dp.message(StudentRegFlow.entering_phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 10:
        await message.answer("Please enter a valid phone number.")
        return
    await state.update_data(phone=phone)
    await message.answer("Enter your <b>Matriculation Number</b> (e.g., <code>24CD036546</code>):", parse_mode=ParseMode.HTML)
    await state.set_state(StudentRegFlow.entering_matric)

@dp.message(StudentRegFlow.entering_matric)
async def reg_matric(message: Message, state: FSMContext):
    matric = message.text.strip().upper()
    data = await state.get_data()
    db.update_user_profile(
        message.from_user.id,
        full_name=data["full_name"],
        phone=data["phone"],
        matric_no=matric
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Registration Complete!</b>\n\n"
        f"Name: <b>{data['full_name']}</b>\n"
        f"Phone: <b>{data['phone']}</b>\n"
        f"Matric: <b>{matric}</b>\n\n"
        f"You can now top up your wallet and book rides.",
        reply_markup=main_student_menu(),
        parse_mode=ParseMode.HTML
    )

# ----------------- Wallet Management -----------------

@dp.message(F.text == "💳 My Wallet")
@dp.message(Command("wallet"))
async def show_wallet(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    user = db.ensure_user(uid)

    history = db.get_wallet_history(uid, limit=5)
    history_text = ""
    if history:
        history_text = "\n\n<b>Recent Transactions:</b>\n"
        for tx in history:
            sign = "+" if tx["tx_type"] == "CREDIT" else "-"
            history_text += f"• {sign}₦{tx['amount']:,.2f} ({tx['description'] or tx['tx_type']})\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Top Up Wallet (Bank Transfer)", callback_data="wallet_topup")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="wallet_refresh")]
    ])

    await message.answer(
        f"💳 <b>Student Wallet</b>\n\n"
        f"Available Balance: <b>₦{user['wallet_balance']:,.2f}</b>"
        f"{history_text}\n"
        f"<i>All rides and instant refunds are paid directly to your wallet.</i>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "wallet_refresh")
async def cb_wallet_refresh(call: CallbackQuery):
    uid = call.from_user.id
    user = db.get_user(uid)
    history = db.get_wallet_history(uid, limit=5)
    history_text = ""
    if history:
        history_text = "\n\n<b>Recent Transactions:</b>\n"
        for tx in history:
            sign = "+" if tx["tx_type"] == "CREDIT" else "-"
            history_text += f"• {sign}₦{tx['amount']:,.2f} ({tx['description'] or tx['tx_type']})\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Top Up Wallet (Bank Transfer)", callback_data="wallet_topup")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="wallet_refresh")]
    ])

    await call.message.edit_text(
        f"💳 <b>Student Wallet</b>\n\n"
        f"Available Balance: <b>₦{user['wallet_balance']:,.2f}</b>"
        f"{history_text}\n"
        f"<i>All rides and instant refunds are paid directly to your wallet.</i>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await call.answer()

@dp.callback_query(F.data == "wallet_topup")
async def cb_wallet_topup(call: CallbackQuery, state: FSMContext):
    await call.answer()
    bank_name = db.get_setting("admin_bank_name", "Zenith Bank / Access Bank")
    acc_num = db.get_setting("admin_account_number", "1234567890")
    acc_name = db.get_setting("admin_account_name", "Campus Shuttle Operations")

    await call.message.answer(
        f"🏦 <b>Bank Transfer Wallet Top-Up</b>\n\n"
        f"Bank: <b>{bank_name}</b>\n"
        f"Account Number: <code>{acc_num}</code>\n"
        f"Account Name: <b>{acc_name}</b>\n\n"
        f"How much did you transfer? (Enter amount in Naira, e.g., <code>1500</code>):",
        reply_markup=cancel_flow_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(WalletTopUpFlow.entering_amount)

@dp.message(WalletTopUpFlow.entering_amount)
async def wallet_enter_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text.strip().replace(",", "").replace("₦", ""))
        if amt < 100:
            await message.answer("Minimum top-up is ₦100. Please enter a valid amount:")
            return
    except ValueError:
        await message.answer("Please enter numbers only (e.g., 1500):")
        return

    await state.update_data(amount=amt)
    await message.answer(
        f"Amount: <b>₦{amt:,.2f}</b>\n\n"
        f"Please enter your payment reference, sender name, or transaction description for confirmation:",
        reply_markup=cancel_flow_kb(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(WalletTopUpFlow.submitting_reference)

@dp.message(WalletTopUpFlow.submitting_reference)
async def wallet_enter_ref(message: Message, state: FSMContext):
    ref = message.text.strip()
    data = await state.get_data()
    amt = data["amount"]
    uid = message.from_user.id
    pid = f"PAY-{uuid.uuid4().hex[:6].upper()}"

    db.execute(
        "INSERT INTO payments (payment_id, user_id, amount, reference, status) VALUES (?, ?, ?, ?, 'pending_admin')",
        (pid, uid, amt, ref)
    )
    await state.clear()

    await message.answer(
        f"✅ <b>Top-Up Request Submitted!</b>\n\n"
        f"Reference ID: <code>{pid}</code>\n"
        f"Amount: <b>₦{amt:,.2f}</b>\n"
        f"Details: {ref}\n\n"
        f"Admin will verify your payment and credit your wallet shortly.",
        reply_markup=main_student_menu(),
        parse_mode=ParseMode.HTML
    )

    # Notify admin
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve Top-Up", callback_data=f"adm_appr_pay:{pid}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rej_pay:{pid}")
        ]
    ])
    await notifier.notify_admin(
        f"🔔 <b>New Bank Top-Up Request</b>\n\n"
        f"Student ID: <code>{uid}</code>\n"
        f"Payment ID: <code>{pid}</code>\n"
        f"Amount: <b>₦{amt:,.2f}</b>\n"
        f"Reference: {ref}",
        reply_markup=admin_kb
    )

# ----------------- Booking Flow -----------------

@dp.message(F.text == "🚖 Book a Shuttle")
@dp.message(Command("book"))
async def start_booking(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    user = db.get_user(uid)
    if not user or not user.get("full_name"):
        db.ensure_user(uid)
        await message.answer(
            "👋 <b>Welcome to DotRider!</b>\n\n"
            "Before booking your first ride, please complete your quick 1-minute registration.\n\n"
            "Please enter your <b>Full Name</b> (e.g., Samuel Adeyemi):",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(StudentRegFlow.entering_name)
        return

    active_ride = db.get_active_student_ride(uid)
    if active_ride:
        await message.answer(
            f"⚠️ You already have an active ride (<b>{active_ride['ride_id']}</b>) with status <code>{active_ride['status']}</code>.\n"
            f"Please wait until it finishes or cancel it before ordering another.",
            reply_markup=main_student_menu(),
            parse_mode=ParseMode.HTML
        )
        return

    locations = db.get_locations()
    buttons = []
    for loc in locations:
        tag = "⚙️" if loc["zone"] == "ENGINEERING" else "📍"
        buttons.append([InlineKeyboardButton(text=f"{tag} {loc['name']}", callback_data=f"pk:{loc['name']}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")])

    await message.answer(
        "📍 <b>Step 1: Choose Pickup Location</b>\n\n"
        "Locations with ⚙️ are in the Engineering zone.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(BookingFlow.choosing_pickup)

@dp.callback_query(BookingFlow.choosing_pickup, F.data.startswith("pk:"))
async def booking_pickup_selected(call: CallbackQuery, state: FSMContext):
    pickup = call.data[3:]
    await state.update_data(pickup=pickup)
    await call.answer()

    locations = db.get_locations()
    buttons = []
    for loc in locations:
        if loc["name"] == pickup:
            continue
        tag = "⚙️" if loc["zone"] == "ENGINEERING" else "📍"
        buttons.append([InlineKeyboardButton(text=f"{tag} {loc['name']}", callback_data=f"dp:{loc['name']}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")])

    await call.message.edit_text(
        f"Pickup: <b>{pickup}</b>\n\n"
        f"🏁 <b>Step 2: Choose Drop-off Destination</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(BookingFlow.choosing_dropoff)

@dp.callback_query(BookingFlow.choosing_dropoff, F.data.startswith("dp:"))
async def booking_dropoff_selected(call: CallbackQuery, state: FSMContext):
    dropoff = call.data[3:]
    data = await state.get_data()
    pickup = data["pickup"]
    await state.update_data(dropoff=dropoff)
    await call.answer()

    # Determine zone
    zone = db.determine_ride_zone(pickup, dropoff)
    await state.update_data(zone=zone)

    fc_fare = db.get_fare_config("full_car", zone)
    os_fare = db.get_fare_config("one_seat", zone)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🚗 Full Car (₦{fc_fare['total_fare']:,.0f})",
            callback_data="pkg:full_car"
        )],
        [InlineKeyboardButton(
            text=f"💺 One Seat (₦{os_fare['total_fare']:,.0f})",
            callback_data="pkg:one_seat"
        )],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]
    ])

    zone_info = "⚙️ <b>Engineering Zone Rate</b> (pickup or drop-off is in Engineering)" if zone == "ENGINEERING" else "📍 <b>Normal Zone Rate</b>"

    await call.message.edit_text(
        f"Route: <b>{pickup} ➡️ {dropoff}</b>\n"
        f"Zone: {zone_info}\n\n"
        f"Select your booking package:\n"
        f"1. <b>Full Car:</b> You get the entire shuttle. Maximum 6-minute wait time.\n"
        f"2. <b>One Seat:</b> Share the shuttle with students heading the same way. 10-minute queue window.",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await state.set_state(BookingFlow.choosing_package)

@dp.callback_query(BookingFlow.choosing_package, F.data.startswith("pkg:"))
async def booking_package_selected(call: CallbackQuery, state: FSMContext):
    pkg = call.data[4:]
    data = await state.get_data()
    pickup = data["pickup"]
    dropoff = data["dropoff"]
    zone = data["zone"]
    await state.update_data(booking_type=pkg)
    await call.answer()

    fare = db.get_fare_config(pkg, zone)
    await state.update_data(fare_breakdown=fare)

    wait_info = (
        "⏳ <b>Waiting policy:</b> Driver will arrive within maximum <b>6 minutes</b> of booking."
        if pkg == "full_car"
        else "⏳ <b>Waiting policy:</b> 10-minute window for the car to fill. If at least 2 seats fill, the car departs. Otherwise, upgrade or get a full refund."
    )

    uid = call.from_user.id
    user = db.ensure_user(uid)
    can_pay = user["wallet_balance"] >= fare["total_fare"]

    kb_rows = []
    if can_pay:
        kb_rows.append([InlineKeyboardButton(text=f"💳 Pay ₦{fare['total_fare']:,.0f} from Wallet & Proceed", callback_data="pay_confirm")])
    else:
        diff = fare["total_fare"] - user["wallet_balance"]
        kb_rows.append([InlineKeyboardButton(text=f"➕ Top Up Wallet (Needs +₦{diff:,.0f})", callback_data="wallet_topup")])
    kb_rows.append([InlineKeyboardButton(text="❌ Cancel Booking", callback_data="cancel_action")])

    await call.message.edit_text(
        f"📋 <b>Booking Fare Breakdown</b>\n\n"
        f"<b>Route:</b> {pickup} ➡️ {dropoff}\n"
        f"<b>Package:</b> {pkg.replace('_', ' ').title()}\n"
        f"<b>Zone:</b> {zone}\n\n"
        f"• Ride Fare: ₦{fare['ride_fare']:,.2f}\n"
        f"• Platform Charges: ₦{fare['charges']:,.2f}\n"
        f"• Campus Tax: ₦{fare['tax']:,.2f}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<b>Total Amount: ₦{fare['total_fare']:,.2f}</b>\n\n"
        f"{wait_info}\n\n"
        f"💳 Your Wallet Balance: <b>₦{user['wallet_balance']:,.2f}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(BookingFlow.confirming_payment)

@dp.callback_query(BookingFlow.confirming_payment, F.data == "pay_confirm")
async def booking_pay_confirm(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    data = await state.get_data()
    fare = data["fare_breakdown"]
    total = fare["total_fare"]

    # Debit wallet
    success, new_bal = db.debit_wallet(uid, total, f"Payment for ride: {data['pickup']} to {data['dropoff']}")
    if not success:
        await call.answer("Insufficient wallet balance!", show_alert=True)
        return

    await call.answer()
    ride_id = generate_ride_id()
    pin = generate_pin()
    await state.update_data(ride_id=ride_id, pin=pin)

    pkg = data["booking_type"]
    pickup = data["pickup"]
    dropoff = data["dropoff"]
    zone = data["zone"]

    # If it is a shared seat ride, check if there is an existing waiting queue on this route
    if pkg == "one_seat":
        existing_queue = db.fetchone("""
            SELECT * FROM rides
            WHERE booking_type = 'one_seat'
            AND pickup = ? AND dropoff = ?
            AND status = 'queue_waiting'
            AND seats_filled < required_seats
            ORDER BY created_at ASC LIMIT 1
        """, (pickup, dropoff))

        if existing_queue:
            q_ride_id = existing_queue["ride_id"]
            new_seats = existing_queue["seats_filled"] + 1
            db.execute("UPDATE rides SET seats_filled = ? WHERE ride_id = ?", (new_seats, q_ride_id))
            db.execute(
                "INSERT INTO ride_seats (ride_id, student_id, seat_count, fare_paid) VALUES (?, ?, 1, ?)",
                (q_ride_id, uid, total)
            )
            await state.clear()
            await call.message.edit_text(
                f"🎉 <b>Joined Shared Shuttle Queue!</b>\n\n"
                f"<b>Ride ID:</b> <code>{q_ride_id}</code>\n"
                f"<b>Route:</b> {pickup} ➡️ {dropoff}\n"
                f"<b>Seats Filled:</b> {new_seats}/4\n"
                f"<b>Check-in PIN:</b> <code>{existing_queue['pin_code']}</code>\n\n"
                f"You will be notified once the car reaches capacity or when the 10-minute timer dispatches.",
                reply_markup=None,
                parse_mode=ParseMode.HTML
            )
            await call.message.answer("Main Menu", reply_markup=main_student_menu())
            return

        # No queue exists -> Create new queue ride
        expire_at = (datetime.utcnow() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""
            INSERT INTO rides (
                ride_id, booking_type, pickup, dropoff, zone, fare_breakdown, total_fare,
                status, pin_code, creator_student_id, seats_filled, required_seats, queue_expires_at
            ) VALUES (?, 'one_seat', ?, ?, ?, ?, ?, 'queue_waiting', ?, ?, 1, 4, ?)
        """, (ride_id, pickup, dropoff, zone, json.dumps(fare), total, pin, uid, expire_at))

        db.execute(
            "INSERT INTO ride_seats (ride_id, student_id, seat_count, fare_paid) VALUES (?, ?, 1, ?)",
            (ride_id, uid, total)
        )
        await state.clear()

        await call.message.edit_text(
            f"🕒 <b>Shared Ride Queue Started!</b>\n\n"
            f"<b>Ride ID:</b> <code>{ride_id}</code>\n"
            f"<b>Route:</b> {pickup} ➡️ {dropoff}\n"
            f"<b>Seats Filled:</b> 1/4\n"
            f"<b>Your Check-in PIN:</b> <code>{pin}</code>\n\n"
            f"⏳ Waiting up to <b>10 minutes</b> for other students.\n"
            f"• If 2 or more seats fill, the ride dispatches immediately.\n"
            f"• If you remain the only passenger after 10 mins, you can upgrade to full car or get a full refund.",
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
        await call.message.answer("Main Menu", reply_markup=main_student_menu())
        return

    # If Full Car -> Let student select from available drivers
    available_drivers = db.get_available_drivers()
    if not available_drivers:
        # Create ride as pending_driver
        db.execute("""
            INSERT INTO rides (
                ride_id, booking_type, pickup, dropoff, zone, fare_breakdown, total_fare,
                status, pin_code, creator_student_id, seats_filled, required_seats
            ) VALUES (?, 'full_car', ?, ?, ?, ?, ?, 'pending_driver', ?, ?, 1, 4)
        """, (ride_id, pickup, dropoff, zone, json.dumps(fare), total, pin, uid))

        db.execute(
            "INSERT INTO ride_seats (ride_id, student_id, seat_count, fare_paid) VALUES (?, ?, 1, ?)",
            (ride_id, uid, total)
        )
        await state.clear()
        await call.message.edit_text(
            f"✅ <b>Payment Confirmed (₦{total:,.2f})!</b>\n\n"
            f"<b>Ride ID:</b> <code>{ride_id}</code>\n"
            f"<b>Check-in PIN:</b> <code>{pin}</code>\n\n"
            f"⚠️ All drivers are currently busy or offline. Your ride has been placed in the priority queue and will be assigned as soon as a driver comes online.",
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
        await call.message.answer("Main Menu", reply_markup=main_student_menu())
        return

    # Available drivers exist -> Present selection list
    buttons = []
    for d in available_drivers:
        stars = f"⭐ {d['rating_avg']:.1f}" if d["rating_count"] > 0 else "⭐ New Driver"
        btn_text = f"🚖 {d['full_name']} ({stars}) - {d['car_model']}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"sel_drv:{d['driver_id']}")])

    buttons.append([InlineKeyboardButton(text="🎲 Auto-Assign Any Available Driver", callback_data="sel_drv:auto")])

    await call.message.edit_text(
        f"✅ <b>Payment Confirmed (₦{total:,.2f})!</b>\n\n"
        f"<b>Route:</b> {pickup} ➡️ {dropoff}\n"
        f"<b>Your Check-in PIN:</b> <code>{pin}</code> (give this to your driver at pickup)\n\n"
        f"👉 <b>Choose your preferred driver:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(BookingFlow.selecting_driver)

@dp.callback_query(BookingFlow.selecting_driver, F.data.startswith("sel_drv:"))
async def booking_driver_selected(call: CallbackQuery, state: FSMContext):
    drv_choice = call.data[8:]
    data = await state.get_data()
    ride_id = data["ride_id"]
    pin = data["pin"]
    pickup = data["pickup"]
    dropoff = data["dropoff"]
    zone = data["zone"]
    fare = data["fare_breakdown"]
    total = fare["total_fare"]
    uid = call.from_user.id

    available_drivers = db.get_available_drivers()
    selected_driver = None
    if drv_choice == "auto":
        if available_drivers:
            selected_driver = available_drivers[0]
    else:
        target_id = int(drv_choice)
        for d in available_drivers:
            if d["driver_id"] == target_id:
                selected_driver = d
                break

    if not selected_driver and available_drivers:
        selected_driver = available_drivers[0]

    expire_at = (datetime.utcnow() + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")

    if selected_driver:
        drv_id = selected_driver["driver_id"]
        db.execute("""
            INSERT INTO rides (
                ride_id, booking_type, pickup, dropoff, zone, fare_breakdown, total_fare,
                status, assigned_driver_id, pin_code, creator_student_id, seats_filled, required_seats, driver_offer_expires_at
            ) VALUES (?, 'full_car', ?, ?, ?, ?, ?, 'driver_offered', ?, ?, ?, 1, 4, ?)
        """, (ride_id, pickup, dropoff, zone, json.dumps(fare), total, drv_id, pin, uid, expire_at))

        db.execute(
            "INSERT INTO ride_seats (ride_id, student_id, seat_count, fare_paid) VALUES (?, ?, 1, ?)",
            (ride_id, uid, total)
        )
        db.add_ride_offer(ride_id, drv_id)
        await state.clear()

        await call.message.edit_text(
            f"🚖 <b>Request Sent to Driver!</b>\n\n"
            f"<b>Driver:</b> {selected_driver['full_name']} (⭐ {selected_driver['rating_avg']})\n"
            f"<b>Car:</b> {selected_driver['car_model']} ({selected_driver['plate_number']})\n"
            f"<b>Ride ID:</b> <code>{ride_id}</code>\n"
            f"<b>Your Check-in PIN:</b> <code>{pin}</code>\n\n"
            f"⏰ The driver has <b>2 minutes</b> to accept. If they don't respond, we will automatically route your request to another available driver.",
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
        await call.message.answer("Main Menu", reply_markup=main_student_menu())

        # Notify Driver
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Accept Ride (2 mins)", callback_data=f"drv_accept:{ride_id}"),
                InlineKeyboardButton(text="❌ Decline", callback_data=f"drv_decline:{ride_id}")
            ]
        ])
        await notifier.notify_driver(
            drv_id,
            f"🚖 <b>New Full-Car Ride Request!</b>\n\n"
            f"<b>Ride ID:</b> {ride_id}\n"
            f"<b>Pickup:</b> {pickup}\n"
            f"<b>Drop-off:</b> {dropoff}\n"
            f"<b>Fare:</b> ₦{total:,.2f}\n\n"
            f"⏰ You have <b>2 minutes</b> to accept before it cascades to another driver.",
            reply_markup=kb
        )
    else:
        # No driver found -> refund
        db.credit_wallet(uid, total, f"Full refund for ride {ride_id} (No drivers available)")
        await state.clear()
        await call.message.edit_text(
            f"❌ <b>No Drivers Available</b>\n\n"
            f"We couldn't reach any available drivers right now.\n"
            f"A full refund of <b>₦{total:,.2f}</b> has been credited back to your wallet.",
            reply_markup=None,
            parse_mode=ParseMode.HTML
        )
        await call.message.answer("Main Menu", reply_markup=main_student_menu())

# ----------------- Active Ride & Cancellation -----------------

@dp.message(F.text == "📋 My Active Ride")
@dp.message(Command("ride", "status"))
async def show_active_ride(message: Message):
    uid = message.from_user.id
    ride = db.get_active_student_ride(uid)
    if not ride:
        await message.answer("You currently have no active or ongoing rides.", reply_markup=main_student_menu())
        return

    driver_info = "Searching for driver..."
    if ride["assigned_driver_id"]:
        d = db.get_driver(ride["assigned_driver_id"])
        if d:
            driver_info = f"{d['full_name']} (Phone: {d['phone']}, Car: {d['car_model']} [{d['plate_number']}])"

    status_desc = {
        "queue_waiting": "Waiting for other students to join (10-minute window)",
        "pending_driver": "Finding an available driver",
        "driver_offered": "Driver is reviewing your ride request",
        "driver_accepted": "Driver accepted - preparing for pickup",
        "departed": "Driver is on the way to you",
        "arrived": "Driver has arrived at your pickup point!",
        "in_progress": "Trip in progress"
    }.get(ride["status"], ride["status"])

    kb_buttons = []
    # If trip is in progress or arrived, student can confirm trip completion & rate
    if ride["status"] in ("in_progress", "arrived", "departed"):
        kb_buttons.append([InlineKeyboardButton(text="🏁 Completed Ride (Finish & Rate)", callback_data=f"stu_complete:{ride['ride_id']}")])

    # Allow cancellation if not yet in progress
    if ride["status"] not in ("in_progress", "completed", "cancelled"):
        kb_buttons.append([InlineKeyboardButton(text="❌ Cancel Ride", callback_data=f"stu_cancel:{ride['ride_id']}")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    await message.answer(
        f"🚖 <b>Active Ride Status</b>\n\n"
        f"<b>Ride ID:</b> <code>{ride['ride_id']}</code>\n"
        f"<b>Route:</b> {ride['pickup']} ➡️ {ride['dropoff']}\n"
        f"<b>Status:</b> {status_desc}\n"
        f"<b>Driver:</b> {driver_info}\n"
        f"<b>Your Check-in PIN:</b> <code>{ride['pin_code']}</code>\n\n"
        f"<i>Please give this PIN to your driver when boarding.</i>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("stu_complete:"))
async def student_confirm_completed(call: CallbackQuery):
    ride_id = call.data[13:]
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] in ("completed", "cancelled"):
        await call.answer("This ride is already completed or cancelled.", show_alert=True)
        return

    # Mark ride completed
    db.execute("""
        UPDATE rides
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP
        WHERE ride_id = ?
    """, (ride_id,))

    # Free driver
    if ride["assigned_driver_id"]:
        db.execute("UPDATE drivers SET current_ride_id = NULL WHERE driver_id = ?", (ride["assigned_driver_id"],))
        await notifier.notify_driver(
            ride["assigned_driver_id"],
            f"🏁 <b>Ride Completed!</b>\n\nPassenger marked ride <code>{ride_id}</code> as completed. You are now free for new rides."
        )

    rating_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"rate_stars:1:{ride_id}"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"rate_stars:2:{ride_id}"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"rate_stars:3:{ride_id}"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"rate_stars:4:{ride_id}"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"rate_stars:5:{ride_id}")
        ]
    ])

    await call.message.edit_text(
        f"🏁 <b>Ride Completed!</b>\n\n"
        f"We hope you had a safe and comfortable ride.\n\n"
        f"Please rate your driver partner:",
        reply_markup=rating_kb,
        parse_mode=ParseMode.HTML
    )
    await call.answer("Ride completed!")

@dp.callback_query(F.data.startswith("stu_cancel:"))
async def student_cancel_ride(call: CallbackQuery):
    ride_id = call.data[11:]
    uid = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] in ("completed", "cancelled"):
        await call.answer("This ride is no longer active.", show_alert=True)
        return

    status = ride["status"]
    total = ride["total_fare"]
    cancel_charge = float(db.get_setting("cancellation_charge", "200.0"))

    # Rules:
    # 1. Student cancels before driver accepts -> full refund
    # 2. Student cancels after driver accepts, before driver departs -> refund minus charges (200)
    # 3. Student cancels after driver departed or arrived -> no refund
    # 4. Driver > 10 minutes late -> full refund
    if status in ("queue_waiting", "pending_driver", "driver_offered", "queue_decision"):
        refund_amount = total
        note = "Full refund (cancelled before driver accepted)"
    elif status == "driver_accepted":
        refund_amount = max(0.0, total - cancel_charge)
        note = f"Refund minus ₦{cancel_charge:,.2f} cancellation charges"
    else:  # departed, arrived, in_progress
        refund_amount = 0.0
        note = "No refund (driver already departed/arrived)"

    # Execute cancellation
    db.execute("""
        UPDATE rides
        SET status = 'cancelled',
            cancelled_at = CURRENT_TIMESTAMP,
            cancellation_reason = ?
        WHERE ride_id = ?
    """, (f"Student cancelled ({note})", ride_id))

    if refund_amount > 0:
        new_bal = db.credit_wallet(uid, refund_amount, f"Refund for cancelled ride {ride_id}")
        refund_text = f"A refund of <b>₦{refund_amount:,.2f}</b> has been credited to your wallet.\n💳 New Balance: <b>₦{new_bal:,.2f}</b>"
    else:
        refund_text = "As per policy, no refund applies because the driver had already departed or arrived."

    # Free up driver if assigned
    if ride["assigned_driver_id"]:
        db.execute("UPDATE drivers SET current_ride_id = NULL WHERE driver_id = ?", (ride["assigned_driver_id"],))
        await notifier.notify_driver(
            ride["assigned_driver_id"],
            f"ℹ️ Passenger cancelled ride <b>{ride_id}</b>. You are now available for new rides."
        )

    await call.message.edit_text(
        f"❌ <b>Ride Cancelled</b>\n\n"
        f"Ride ID: <code>{ride_id}</code>\n"
        f"Reason: {note}\n\n"
        f"{refund_text}",
        reply_markup=None,
        parse_mode=ParseMode.HTML
    )
    await call.message.answer("Main Menu", reply_markup=main_student_menu())
    await call.answer()

# ----------------- Shared Ride Queue Timeout Actions -----------------

@dp.callback_query(F.data.startswith("sh_upgrade:"))
async def shared_upgrade_to_full(call: CallbackQuery):
    ride_id = call.data[11:]
    uid = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] != "queue_decision":
        await call.answer("This offer is no longer valid.", show_alert=True)
        return

    zone = ride["zone"]
    full_car_fare = db.get_fare_config("full_car", zone)["total_fare"]
    paid = ride["total_fare"]
    diff = full_car_fare - paid

    user = db.get_user(uid)
    if user["wallet_balance"] < diff:
        await call.answer(f"Insufficient funds! You need ₦{diff:,.2f} to upgrade. Please top up your wallet.", show_alert=True)
        return

    # Debit difference
    db.debit_wallet(uid, diff, f"Upgrade shared ride {ride_id} to full car")
    new_fare_dict = db.get_fare_config("full_car", zone)

    db.execute("""
        UPDATE rides
        SET booking_type = 'full_car',
            fare_breakdown = ?,
            total_fare = ?,
            status = 'pending_driver'
        WHERE ride_id = ?
    """, (json.dumps(new_fare_dict), full_car_fare, ride_id))

    await call.message.edit_text(
        f"🎉 <b>Upgraded to Full Car!</b>\n\n"
        f"Ride ID: <code>{ride_id}</code>\n"
        f"Total Fare: <b>₦{full_car_fare:,.2f}</b>\n\n"
        f"Your ride is now being dispatched to available drivers.",
        reply_markup=None,
        parse_mode=ParseMode.HTML
    )
    await call.message.answer("Main Menu", reply_markup=main_student_menu())

    # Auto assign driver
    avail = db.get_available_drivers()
    if avail:
        drv = avail[0]
        expire_at = (datetime.utcnow() + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""
            UPDATE rides
            SET assigned_driver_id = ?,
                status = 'driver_offered',
                driver_offer_expires_at = ?
            WHERE ride_id = ?
        """, (drv["driver_id"], expire_at, ride_id))
        db.add_ride_offer(ride_id, drv["driver_id"])

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Accept Ride (2 mins)", callback_data=f"drv_accept:{ride_id}"),
                InlineKeyboardButton(text="❌ Decline", callback_data=f"drv_decline:{ride_id}")
            ]
        ])
        await notifier.notify_driver(
            drv["driver_id"],
            f"🚖 <b>New Full-Car Ride Dispatch!</b>\n\n"
            f"<b>Ride ID:</b> {ride_id}\n"
            f"<b>Pickup:</b> {ride['pickup']}\n"
            f"<b>Drop-off:</b> {ride['dropoff']}\n"
            f"<b>Fare:</b> ₦{full_car_fare:,.2f}\n\n"
            f"⏰ You have <b>2 minutes</b> to accept.",
            reply_markup=kb
        )

@dp.callback_query(F.data.startswith("sh_cancel:"))
async def shared_cancel_and_refund(call: CallbackQuery):
    ride_id = call.data[10:]
    uid = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] != "queue_decision":
        await call.answer("This offer is no longer valid.", show_alert=True)
        return

    # Refund full fare
    total = ride["total_fare"]
    db.execute("""
        UPDATE rides
        SET status = 'cancelled',
            cancelled_at = CURRENT_TIMESTAMP,
            cancellation_reason = 'Shared ride timed out with single passenger'
        WHERE ride_id = ?
    """, (ride_id,))

    new_bal = db.credit_wallet(uid, total, f"Full refund for expired shared ride {ride_id}")
    await call.message.edit_text(
        f"✅ <b>Ride Cancelled & Refunded</b>\n\n"
        f"A full refund of <b>₦{total:,.2f}</b> has been returned to your wallet.\n"
        f"💳 New Balance: <b>₦{new_bal:,.2f}</b>",
        reply_markup=None,
        parse_mode=ParseMode.HTML
    )
    await call.message.answer("Main Menu", reply_markup=main_student_menu())

# ----------------- Post-Ride Rating -----------------

@dp.callback_query(F.data.startswith("rate_stars:"))
async def student_rating_stars(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    stars = int(parts[1])
    ride_id = parts[2]
    ride = db.get_ride(ride_id)

    if not ride:
        await call.answer("Ride not found.", show_alert=True)
        return

    driver_id = ride["assigned_driver_id"]
    uid = call.from_user.id

    # Store rating in database
    db.execute(
        "INSERT INTO ratings (ride_id, driver_id, student_id, stars) VALUES (?, ?, ?, ?)",
        (ride_id, driver_id, uid, stars)
    )
    db.update_driver_rating(driver_id, stars)

    await state.update_data(rating_ride_id=ride_id, rating_driver_id=driver_id)
    await call.message.edit_text(
        f"⭐ You rated this driver <b>{stars}/5 stars</b>!\n\n"
        f"Would you like to leave an optional comment? Type your feedback below, or tap Skip.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Skip Comment", callback_data="rate_skip")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(RatingFlow.entering_comment)

@dp.message(RatingFlow.entering_comment)
async def student_rating_comment(message: Message, state: FSMContext):
    comment = message.text.strip()
    data = await state.get_data()
    ride_id = data.get("rating_ride_id")
    if ride_id:
        db.execute("UPDATE ratings SET comment = ? WHERE ride_id = ?", (comment, ride_id))
    await state.clear()
    await message.answer("🙏 Thank you for your feedback! It helps improve campus shuttle service.", reply_markup=main_student_menu())

@dp.callback_query(RatingFlow.entering_comment, F.data == "rate_skip")
async def student_rating_skip(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🙏 Thank you for your rating!", reply_markup=None)
    await call.answer()

# ----------------- Static Info & Locations -----------------

@dp.message(F.text == "ℹ️ Campus Locations & Fares")
@dp.message(Command("fares", "locations"))
async def info_locations(message: Message):
    locs = db.get_locations()
    text = "📍 <b>Approved Campus Locations & Zones</b>\n\n"
    text += "<b>Engineering Zone:</b>\n"
    for l in locs:
        if l["zone"] == "ENGINEERING":
            text += f"• ⚙️ {l['name']}\n"
    text += "\n<b>Normal Zone:</b>\n"
    for l in locs:
        if l["zone"] == "NORMAL":
            text += f"• 📍 {l['name']}\n"

    fc_norm = db.get_fare_config("full_car", "NORMAL")
    fc_eng = db.get_fare_config("full_car", "ENGINEERING")
    os_norm = db.get_fare_config("one_seat", "NORMAL")
    os_eng = db.get_fare_config("one_seat", "ENGINEERING")

    text += (
        f"\n💰 <b>Fare Rates:</b>\n"
        f"<b>Full Car:</b>\n"
        f"• Normal Zone: ₦{fc_norm['total_fare']:,.0f} (Fare {fc_norm['ride_fare']:,.0f} + Charges {fc_norm['charges']:,.0f} + Tax {fc_norm['tax']:,.0f})\n"
        f"• Engineering Zone: ₦{fc_eng['total_fare']:,.0f} (Fare {fc_eng['ride_fare']:,.0f} + Charges {fc_eng['charges']:,.0f} + Tax {fc_eng['tax']:,.0f})\n\n"
        f"<b>One Seat (Shared):</b>\n"
        f"• Normal Zone: ₦{os_norm['total_fare']:,.0f} per seat\n"
        f"• Engineering Zone: ₦{os_eng['total_fare']:,.0f} per seat\n\n"
        f"<i>Note: Engineering price applies if EITHER pickup or drop-off is in the Engineering zone.</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "📜 Ride History")
@dp.message(Command("history"))
async def ride_history(message: Message):
    uid = message.from_user.id
    rides = db.fetchall("""
        SELECT * FROM rides
        WHERE creator_student_id = ?
        ORDER BY created_at DESC LIMIT 5
    """, (uid,))
    if not rides:
        await message.answer("You haven't taken any rides yet.")
        return

    text = "📜 <b>Your Recent Rides:</b>\n\n"
    for r in rides:
        text += (
            f"• <b>{r['ride_id']}</b> ({r['booking_type'].replace('_', ' ').title()})\n"
            f"  Route: {r['pickup']} ➡️ {r['dropoff']}\n"
            f"  Fare: ₦{r['total_fare']:,.2f} | Status: <code>{r['status']}</code>\n\n"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "📞 Support & Info")
@dp.message(Command("support", "help"))
async def support_info(message: Message):
    await message.answer(
        f"📞 <b>Campus Shuttle Support</b>\n\n"
        f"Emergency Line: <code>{config.SUPPORT_PHONE}</code>\n"
        f"Dispatch Desk: <b>{config.DISPATCH_DESK}</b>\n\n"
        f"If you encounter any issues, please reach out to dispatch.",
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "cancel_action")
async def cancel_any_action(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Action cancelled.", reply_markup=None)
    await call.answer()

# ----------------- Admin Telegram Menu -----------------

@dp.message(Command("admin"))
async def admin_menu(message: Message):
    admin_id = config.ADMIN_CHAT_ID
    if admin_id and str(message.from_user.id) != str(admin_id):
        await message.answer("Access restricted.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Pending Bank Payments", callback_data="adm_view_payments")],
        [InlineKeyboardButton(text="⚡ Quick Credit My Wallet (₦5,000)", callback_data="adm_quick_credit")],
        [InlineKeyboardButton(text="⚠️ Stuck Rides Inspector", callback_data="adm_view_stuck")],
        [InlineKeyboardButton(text="📊 System Summary", callback_data="adm_view_summary")]
    ])
    await message.answer("🛠️ <b>Campus Shuttle Admin Panel</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "adm_quick_credit")
async def admin_quick_credit(call: CallbackQuery):
    admin_id = config.ADMIN_CHAT_ID
    if admin_id and str(call.from_user.id) != str(admin_id):
        await call.answer("Unauthorized", show_alert=True)
        return
    new_bal = db.credit_wallet(call.from_user.id, 5000.0, "Admin testing top-up")
    await call.message.edit_text(
        f"✅ <b>Wallet Credited!</b>\n\n"
        f"Added: <b>₦5,000.00</b>\n"
        f"💳 New Balance: <b>₦{new_bal:,.2f}</b>\n\n"
        f"You can now test booking rides immediately!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Admin", callback_data="adm_back")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await call.answer()

@dp.callback_query(F.data == "adm_view_payments")
async def admin_payments_list(call: CallbackQuery):
    payments = db.fetchall("SELECT * FROM payments WHERE status = 'pending_admin' ORDER BY created_at ASC LIMIT 10")
    if not payments:
        await call.message.edit_text("No pending bank payments at the moment.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Admin", callback_data="adm_back")]
        ]))
        return

    buttons = []
    for p in payments:
        buttons.append([InlineKeyboardButton(text=f"₦{p['amount']:,.0f} - {p['reference'][:15]}", callback_data=f"adm_pay_detail:{p['payment_id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="adm_back")])

    await call.message.edit_text("⏳ <b>Pending Bank Top-Up Requests:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("adm_pay_detail:"))
async def admin_payment_detail(call: CallbackQuery):
    pid = call.data[15:]
    p = db.fetchone("SELECT * FROM payments WHERE payment_id = ?", (pid,))
    if not p:
        await call.answer("Payment not found.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve & Credit", callback_data=f"adm_appr_pay:{pid}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rej_pay:{pid}")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_view_payments")]
    ])
    await call.message.edit_text(
        f"💳 <b>Payment Request Details</b>\n\n"
        f"ID: <code>{p['payment_id']}</code>\n"
        f"Student ID: <code>{p['user_id']}</code>\n"
        f"Amount: <b>₦{p['amount']:,.2f}</b>\n"
        f"Reference: <code>{p['reference']}</code>\n"
        f"Date: {p['created_at']}",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("adm_appr_pay:"))
async def admin_approve_payment(call: CallbackQuery):
    pid = call.data[13:]
    p = db.fetchone("SELECT * FROM payments WHERE payment_id = ?", (pid,))
    if not p or p["status"] != "pending_admin":
        await call.answer("Payment already processed.")
        return

    db.execute("UPDATE payments SET status = 'approved', reviewed_by = ? WHERE payment_id = ?", (call.from_user.id, pid))
    new_bal = db.credit_wallet(p["user_id"], p["amount"], f"Bank top-up approved ({pid})")

    # Notify student
    await notifier.notify_student(
        p["user_id"],
        f"🎉 <b>Bank Top-Up Approved!</b>\n\n"
        f"Amount: <b>₦{p['amount']:,.2f}</b> has been added to your wallet.\n"
        f"💳 Available Balance: <b>₦{new_bal:,.2f}</b>"
    )

    await call.message.edit_text(f"✅ Payment <code>{pid}</code> approved and wallet credited with ₦{p['amount']:,.2f}.", reply_markup=None)
    await call.answer()

@dp.callback_query(F.data.startswith("adm_rej_pay:"))
async def admin_reject_payment(call: CallbackQuery):
    pid = call.data[12:]
    p = db.fetchone("SELECT * FROM payments WHERE payment_id = ?", (pid,))
    if not p or p["status"] != "pending_admin":
        await call.answer("Payment already processed.")
        return

    db.execute("UPDATE payments SET status = 'rejected', reviewed_by = ? WHERE payment_id = ?", (call.from_user.id, pid))
    await notifier.notify_student(
        p["user_id"],
        f"❌ <b>Bank Top-Up Declined</b>\n\n"
        f"Your top-up of ₦{p['amount']:,.2f} (Ref: {p['reference']}) could not be verified.\n"
        f"Please check your transaction details or contact support."
    )
    await call.message.edit_text(f"❌ Payment <code>{pid}</code> rejected.", reply_markup=None)
    await call.answer()

@dp.callback_query(F.data == "adm_view_stuck")
async def admin_stuck_rides(call: CallbackQuery):
    stuck = db.fetchall("""
        SELECT * FROM rides
        WHERE status IN ('pending_driver', 'driver_offered', 'queue_waiting', 'departed', 'arrived')
        ORDER BY created_at ASC LIMIT 10
    """)
    if not stuck:
        await call.message.edit_text("No stuck rides found. All clear!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="adm_back")]
        ]))
        return

    text = "⚠️ <b>Active / Potential Stuck Rides:</b>\n\n"
    for r in stuck:
        text += (
            f"• <b>{r['ride_id']}</b> ({r['status']})\n"
            f"  Route: {r['pickup']} ➡️ {r['dropoff']}\n"
            f"  Driver: {r['assigned_driver_id'] or 'None'}\n"
            f"  Created: {r['created_at']}\n\n"
        )
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_back")]
    ]), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "adm_back")
async def admin_go_back(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Pending Bank Payments", callback_data="adm_view_payments")],
        [InlineKeyboardButton(text="⚠️ Stuck Rides Inspector", callback_data="adm_view_stuck")],
        [InlineKeyboardButton(text="📊 System Summary", callback_data="adm_view_summary")]
    ])
    await call.message.edit_text("🛠️ <b>Campus Shuttle Admin Panel</b>", reply_markup=kb, parse_mode=ParseMode.HTML)

async def main():
    db.init_schema()
    token = config.STUDENT_BOT_TOKEN
    if not token:
        logger.error("STUDENT_BOT_TOKEN is not set.")
        return

    global bot_instance
    bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # Run background timer worker alongside bot
    asyncio.create_task(run_timer_worker_loop())

    logger.info("Student Bot starting polling...")
    await dp.start_polling(bot_instance)

if __name__ == "__main__":
    asyncio.run(main())
