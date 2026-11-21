"""
Driver Telegram Bot.
Handles:
- Driver Onboarding & Registration
- Going Online / Offline (duty toggle)
- Receiving ride requests with a 2-minute acceptance timer
- Acceptance / Decline handlers
- 5-Minute Readiness confirmation
- "Departed" and "Arrived" status updates with passenger alerts
- PIN / Check-in code verification before trip start
- 5-Minute Passenger No-Show enforcement (only active after Arrived)
- Trip completion & driver stats
"""
import asyncio
import logging
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
logger = logging.getLogger("driver_bot")

dp = Dispatcher(storage=MemoryStorage())
bot_instance: Bot | None = None

# ----------------- FSM States -----------------

class DriverRegFlow(StatesGroup):
    entering_name = State()
    entering_phone = State()
    entering_car = State()
    entering_plate = State()

class DriverVerifyPinFlow(StatesGroup):
    entering_pin = State()

# ----------------- Keyboards -----------------

def main_driver_menu(is_online: bool = False):
    status_btn = KeyboardButton(text="🔴 Go Offline (End Duty)") if is_online else KeyboardButton(text="🟢 Go Online (Ready for Rides)")
    return ReplyKeyboardMarkup(
        keyboard=[
            [status_btn, KeyboardButton(text="📋 Current Active Trip")],
            [KeyboardButton(text="📊 My Profile & Rating"), KeyboardButton(text="ℹ️ Campus Help")]
        ],
        resize_keyboard=True
    )

# ----------------- Start & Welcome -----------------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    drv_id = message.from_user.id
    driver = db.get_driver(drv_id)

    if not driver:
        await message.answer(
            "👋 <b>Welcome to the Campus Shuttle Driver Bot!</b>\n\n"
            "You are not yet registered as an authorized driver partner.\n"
            "Let's complete your registration.\n\n"
            "Please enter your <b>Full Name</b>:",
            parse_mode=ParseMode.HTML
        )
        await state.set_state(DriverRegFlow.entering_name)
    else:
        is_online = bool(driver["is_online"])
        status_txt = "🟢 Online (Ready for ride requests)" if is_online else "🔴 Offline (Off duty)"
        await message.answer(
            f"👋 Welcome back, <b>{driver['full_name']}</b>!\n"
            f"Status: {status_txt}\n"
            f"Rating: ⭐ <b>{driver['rating_avg']:.1f}</b> ({driver['rating_count']} reviews)\n"
            f"Vehicle: <b>{driver['car_model']}</b> (<code>{driver['plate_number']}</code>)",
            reply_markup=main_driver_menu(is_online),
            parse_mode=ParseMode.HTML
        )

# ----------------- Driver Registration -----------------

@dp.message(DriverRegFlow.entering_name)
async def reg_driver_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Please enter a valid full name.")
        return
    await state.update_data(full_name=name)
    await message.answer("Enter your <b>Phone Number</b> (e.g. 08012345678):", parse_mode=ParseMode.HTML)
    await state.set_state(DriverRegFlow.entering_phone)

@dp.message(DriverRegFlow.entering_phone)
async def reg_driver_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 10:
        await message.answer("Please enter a valid phone number.")
        return
    await state.update_data(phone=phone)
    await message.answer("Enter your <b>Car Model / Make</b> (e.g., Toyota Sienna / HiAce):", parse_mode=ParseMode.HTML)
    await state.set_state(DriverRegFlow.entering_car)

@dp.message(DriverRegFlow.entering_car)
async def reg_driver_car(message: Message, state: FSMContext):
    car = message.text.strip()
    await state.update_data(car_model=car)
    await message.answer("Enter your <b>Vehicle Plate Number</b> (e.g. KSF-123-AB):", parse_mode=ParseMode.HTML)
    await state.set_state(DriverRegFlow.entering_plate)

@dp.message(DriverRegFlow.entering_plate)
async def reg_driver_plate(message: Message, state: FSMContext):
    plate = message.text.strip().upper()
    data = await state.get_data()
    drv_id = message.from_user.id

    db.register_or_update_driver(
        drv_id,
        full_name=data["full_name"],
        phone=data["phone"],
        car_model=data["car_model"],
        plate_number=plate,
        is_approved=1,
        is_online=0
    )
    await state.clear()

    await message.answer(
        f"✅ <b>Driver Registration Successful!</b>\n\n"
        f"Name: <b>{data['full_name']}</b>\n"
        f"Car: <b>{data['car_model']}</b> (<code>{plate}</code>)\n"
        f"Phone: <b>{data['phone']}</b>\n\n"
        f"Tap <b>'🟢 Go Online'</b> whenever you are ready to accept rides on campus.",
        reply_markup=main_driver_menu(is_online=False),
        parse_mode=ParseMode.HTML
    )

# ----------------- Duty Toggle (Online/Offline) -----------------

@dp.message(F.text == "🟢 Go Online (Ready for Rides)")
async def driver_go_online(message: Message):
    drv_id = message.from_user.id
    driver = db.get_driver(drv_id)
    if not driver:
        await message.answer("Please register first by typing /start.")
        return

    db.set_driver_online(drv_id, True)
    await message.answer(
        "🟢 <b>You are now ONLINE!</b>\n\n"
        "You will receive incoming ride requests in your area.\n"
        "Remember you have <b>2 minutes</b> to accept each offer before it passes to another driver.",
        reply_markup=main_driver_menu(is_online=True),
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "🔴 Go Offline (End Duty)")
async def driver_go_offline(message: Message):
    drv_id = message.from_user.id
    active = db.get_active_driver_ride(drv_id)
    if active:
        await message.answer(
            f"⚠️ You cannot go offline while you have an active trip (<b>{active['ride_id']}</b>).\n"
            f"Please complete or cancel your trip first.",
            parse_mode=ParseMode.HTML
        )
        return

    db.set_driver_online(drv_id, False)
    await message.answer(
        "🔴 <b>You are now OFFLINE.</b>\n\n"
        "You will not receive any new ride requests until you go online again.",
        reply_markup=main_driver_menu(is_online=False),
        parse_mode=ParseMode.HTML
    )

# ----------------- Ride Offer Acceptance & Decline -----------------

@dp.callback_query(F.data.startswith("drv_accept:"))
async def driver_accept_ride(call: CallbackQuery):
    ride_id = call.data[11:]
    drv_id = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride:
        await call.answer("Ride not found.", show_alert=True)
        return

    if ride["status"] != "driver_offered" or ride["assigned_driver_id"] != drv_id:
        await call.answer("This offer has already expired or been reassigned.", show_alert=True)
        return

    # Check 2-minute expiration
    if ride["driver_offer_expires_at"]:
        exp = datetime.strptime(ride["driver_offer_expires_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.utcnow() > exp:
            await call.answer("Time expired! You had 2 minutes to accept.", show_alert=True)
            return

    # Accept ride
    db.execute("""
        UPDATE rides
        SET status = 'driver_accepted',
            driver_offer_expires_at = NULL
        WHERE ride_id = ?
    """, (ride_id,))
    db.execute("UPDATE drivers SET current_ride_id = ? WHERE driver_id = ?", (ride_id, drv_id))
    db.mark_driver_offer_status(ride_id, drv_id, "accepted")

    driver = db.get_driver(drv_id)

    # Notify student that driver accepted
    await notifier.notify_student(
        ride["creator_student_id"],
        f"✅ <b>Driver Accepted!</b>\n\n"
        f"<b>Driver:</b> {driver['full_name']} (⭐ {driver['rating_avg']})\n"
        f"<b>Car:</b> {driver['car_model']} (<code>{driver['plate_number']}</code>)\n"
        f"<b>Phone:</b> {driver['phone']}\n"
        f"<b>Check-in PIN:</b> <code>{ride['pin_code']}</code>\n\n"
        f"Your driver is preparing for pickup."
    )

    # Simplified driver journey: Accept Ride -> On way -> Confirm PIN -> Complete
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 On the Way", callback_data=f"trip_dep:{ride_id}")],
        [InlineKeyboardButton(text="❌ Cancel Trip", callback_data=f"trip_cancel:{ride_id}")]
    ])

    await call.message.edit_text(
        f"🎉 <b>Trip Accepted!</b>\n\n"
        f"<b>Ride ID:</b> <code>{ride_id}</code>\n"
        f"<b>Pickup:</b> {ride['pickup']}\n"
        f"<b>Drop-off:</b> {ride['dropoff']}\n"
        f"<b>Fare:</b> ₦{ride['total_fare']:,.2f}\n\n"
        f"Tap below when you start heading to pickup:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await call.answer()

@dp.callback_query(F.data.startswith("drv_decline:"))
async def driver_decline_ride(call: CallbackQuery):
    ride_id = call.data[12:]
    drv_id = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] != "driver_offered" or ride["assigned_driver_id"] != drv_id:
        await call.answer("Offer is no longer active.", show_alert=True)
        return

    db.mark_driver_offer_status(ride_id, drv_id, "declined")
    await call.message.edit_text(f"❌ You declined ride <code>{ride_id}</code>.", reply_markup=None)
    await call.answer()

    # Re-route to next available driver
    rejected = db.get_rejected_driver_ids_for_ride(ride_id)
    available = db.get_available_drivers()
    next_drv = None
    for d in available:
        if d["driver_id"] not in rejected and d["driver_id"] != drv_id:
            next_drv = d
            break

    student_id = ride["creator_student_id"]

    if next_drv:
        new_driver_id = next_drv["driver_id"]
        expire_at = (datetime.utcnow() + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""
            UPDATE rides
            SET assigned_driver_id = ?,
                driver_offer_expires_at = ?
            WHERE ride_id = ?
        """, (new_driver_id, expire_at, ride_id))
        db.add_ride_offer(ride_id, new_driver_id)

        await notifier.notify_student(
            student_id,
            f"🔄 Routing your ride request to another driver: <b>{next_drv['full_name']}</b> (⭐ {next_drv['rating_avg']})."
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Accept Ride (2 mins)", callback_data=f"drv_accept:{ride_id}"),
                InlineKeyboardButton(text="❌ Decline", callback_data=f"drv_decline:{ride_id}")
            ]
        ])
        await notifier.notify_driver(
            new_driver_id,
            f"🚖 <b>New Ride Request!</b>\n\n"
            f"<b>Ride ID:</b> {ride_id}\n"
            f"<b>Pickup:</b> {ride['pickup']}\n"
            f"<b>Drop-off:</b> {ride['dropoff']}\n"
            f"<b>Fare:</b> ₦{ride['total_fare']:,.2f}\n\n"
            f"⏰ You have <b>2 minutes</b> to accept.",
            reply_markup=kb
        )
    else:
        # No driver found -> Cancel & full refund
        db.execute("""
            UPDATE rides
            SET status = 'cancelled',
                cancelled_at = CURRENT_TIMESTAMP,
                cancellation_reason = 'No driver available after decline'
            WHERE ride_id = ?
        """, (ride_id,))

        refund_amt = ride["total_fare"]
        new_bal = db.credit_wallet(student_id, refund_amt, f"Full refund for ride {ride_id} (No available driver)")
        await notifier.notify_student(
            student_id,
            f"❌ <b>No Drivers Available</b>\n\n"
            f"All available drivers declined or are busy.\n"
            f"A <b>full refund</b> of ₦{refund_amt:,.2f} has been added back to your wallet.\n"
            f"💳 Available Balance: <b>₦{new_bal:,.2f}</b>"
        )

# ----------------- Simplified Trip Lifecycle Controls -----------------

@dp.callback_query(F.data.startswith("trip_dep:"))
async def driver_trip_departed(call: CallbackQuery):
    ride_id = call.data[9:]
    ride = db.get_ride(ride_id)
    if not ride:
        await call.answer("Trip not found.")
        return

    db.execute("""
        UPDATE rides
        SET status = 'departed',
            departed_at = CURRENT_TIMESTAMP
        WHERE ride_id = ?
    """, (ride_id,))

    # Notify student
    await notifier.notify_student(
        ride["creator_student_id"],
        f"🚀 <b>Driver is On The Way!</b>\n\n"
        f"Your driver is heading to <b>{ride['pickup']}</b>.\n"
        f"Your check-in PIN is: <code>{ride['pin_code']}</code>."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Confirm PIN & Start Ride", callback_data=f"trip_pin:{ride_id}")],
        [InlineKeyboardButton(text="⏳ Passenger No-Show (5 mins)", callback_data=f"trip_noshow:{ride_id}")],
        [InlineKeyboardButton(text="❌ Cancel Trip", callback_data=f"trip_cancel:{ride_id}")]
    ])
    await call.message.edit_text(
        f"🚀 <b>On The Way to Pickup</b>\n\n"
        f"<b>Ride ID:</b> <code>{ride_id}</code>\n"
        f"<b>Pickup:</b> {ride['pickup']}\n"
        f"<b>Drop-off:</b> {ride['dropoff']}\n\n"
        f"When you meet the passenger, ask for their 4-digit PIN and tap <b>'Confirm PIN & Start Ride'</b>:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await call.answer("Status updated: On the way")

# ----------------- PIN Verification & Ride Start -----------------

@dp.callback_query(F.data.startswith("trip_pin:"))
async def driver_prompt_pin(call: CallbackQuery, state: FSMContext):
    ride_id = call.data[9:]
    await state.update_data(active_ride_id=ride_id)
    await call.message.answer(
        f"🔑 <b>Enter Passenger Check-in PIN:</b>\n\n"
        f"Please enter the 4-digit code given to you by the student for ride <code>{ride_id}</code>:",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(DriverVerifyPinFlow.entering_pin)
    await call.answer()

@dp.message(DriverVerifyPinFlow.entering_pin)
async def driver_verify_pin(message: Message, state: FSMContext):
    entered_pin = message.text.strip()
    data = await state.get_data()
    ride_id = data.get("active_ride_id")
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] not in ("arrived", "departed"):
        await message.answer("Trip is not currently awaiting PIN verification.")
        await state.clear()
        return

    if entered_pin != ride["pin_code"]:
        await message.answer(
            "❌ <b>Wrong PIN Code!</b>\n\n"
            "The entered code does not match the passenger's booking. Please check with the passenger and try again:",
            parse_mode=ParseMode.HTML
        )
        return

    # Correct PIN! Start ride
    db.execute("""
        UPDATE rides
        SET status = 'in_progress'
        WHERE ride_id = ?
    """, (ride_id,))
    await state.clear()

    # Notify student
    await notifier.notify_student(
        ride["creator_student_id"],
        f"🎉 <b>Check-in Verified!</b>\n\n"
        f"Your ride <b>{ride_id}</b> has commenced.\n"
        f"Have a pleasant trip to <b>{ride['dropoff']}</b>!"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏁 Complete Ride", callback_data=f"trip_complete:{ride_id}")]
    ])
    await message.answer(
        f"✅ <b>PIN Verified Successfully!</b>\n\n"
        f"<b>Trip In Progress:</b> {ride['pickup']} ➡️ {ride['dropoff']}\n\n"
        f"Tap below once you have safely arrived at the destination:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

# ----------------- Completing Trip & Rating Trigger -----------------

@dp.callback_query(F.data.startswith("trip_complete:"))
async def driver_trip_complete(call: CallbackQuery):
    ride_id = call.data[14:]
    drv_id = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] != "in_progress":
        await call.answer("Trip cannot be completed in current state.", show_alert=True)
        return

    db.execute("""
        UPDATE rides
        SET status = 'completed',
            completed_at = CURRENT_TIMESTAMP
        WHERE ride_id = ?
    """, (ride_id,))
    db.execute("UPDATE drivers SET current_ride_id = NULL WHERE driver_id = ?", (drv_id,))

    # Trigger post-ride rating for student
    rating_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"rate_stars:1:{ride_id}"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"rate_stars:2:{ride_id}"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"rate_stars:3:{ride_id}"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"rate_stars:4:{ride_id}"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"rate_stars:5:{ride_id}")
        ]
    ])
    await notifier.notify_student(
        ride["creator_student_id"],
        f"🏁 <b>You Have Arrived!</b>\n\n"
        f"Your ride to <b>{ride['dropoff']}</b> is complete.\n\n"
        f"Please take a moment to rate your driver:",
        reply_markup=rating_kb
    )

    await call.message.edit_text(
        f"🏁 <b>Trip Completed!</b>\n\n"
        f"Ride <code>{ride_id}</code> is officially recorded as completed.\n"
        f"You are now ready to accept new rides.",
        reply_markup=None,
        parse_mode=ParseMode.HTML
    )
    await call.answer("Ride completed successfully!")

# ----------------- Passenger No-Show -----------------

@dp.callback_query(F.data.startswith("trip_noshow:"))
async def driver_trip_noshow(call: CallbackQuery):
    ride_id = call.data[12:]
    drv_id = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] != "arrived":
        await call.answer("No-show can only be applied after arriving at pickup.", show_alert=True)
        return

    # Check 5 minutes after arrived_at
    if ride["arrived_at"]:
        arr_time = datetime.strptime(ride["arrived_at"], "%Y-%m-%d %H:%M:%S")
        elapsed = (datetime.utcnow() - arr_time).total_seconds()
        if elapsed < 300:
            remaining = int(300 - elapsed)
            await call.answer(f"Please wait 5 full minutes. {remaining}s remaining.", show_alert=True)
            return

    # Close ride as no-show (no refund as per rules)
    db.execute("""
        UPDATE rides
        SET status = 'cancelled',
            cancelled_at = CURRENT_TIMESTAMP,
            cancellation_reason = 'Passenger no-show (5+ minutes)'
        WHERE ride_id = ?
    """, (ride_id,))
    db.execute("UPDATE drivers SET current_ride_id = NULL WHERE driver_id = ?", (drv_id,))

    # Notify student
    await notifier.notify_student(
        ride["creator_student_id"],
        f"❌ <b>Ride Closed: Passenger No-Show</b>\n\n"
        f"Your driver waited over 5 minutes at <b>{ride['pickup']}</b> without check-in.\n"
        f"The ride has been cancelled without refund in accordance with campus shuttle guidelines."
    )

    await call.message.edit_text(
        f"🛑 <b>Ride Cancelled: Passenger No-Show</b>\n\n"
        f"Ride <code>{ride_id}</code> has been closed. You are now free to take new passengers.",
        reply_markup=None,
        parse_mode=ParseMode.HTML
    )
    await call.answer()

# ----------------- Driver Cancellation -----------------

@dp.callback_query(F.data.startswith("trip_cancel:"))
async def driver_trip_cancel(call: CallbackQuery):
    ride_id = call.data[12:]
    drv_id = call.from_user.id
    ride = db.get_ride(ride_id)

    if not ride or ride["status"] in ("completed", "cancelled"):
        await call.answer("Trip cannot be cancelled.", show_alert=True)
        return

    # Driver cancels -> full refund to student and re-offer
    db.execute("""
        UPDATE rides
        SET status = 'cancelled',
            cancelled_at = CURRENT_TIMESTAMP,
            cancellation_reason = 'Driver cancelled'
        WHERE ride_id = ?
    """, (ride_id,))
    db.execute("UPDATE drivers SET current_ride_id = NULL WHERE driver_id = ?", (drv_id,))

    # Full refund to student
    student_id = ride["creator_student_id"]
    refund_amt = ride["total_fare"]
    new_bal = db.credit_wallet(student_id, refund_amt, f"Full refund for ride {ride_id} (Driver cancelled)")

    await notifier.notify_student(
        student_id,
        f"⚠️ <b>Driver Cancelled Trip</b>\n\n"
        f"Your driver was unable to fulfill ride <b>{ride_id}</b>.\n"
        f"A <b>full refund</b> of ₦{refund_amt:,.2f} has been credited to your wallet.\n"
        f"💳 Available Balance: <b>₦{new_bal:,.2f}</b>\n\n"
        f"You can order another shuttle anytime!"
    )

    await call.message.edit_text("❌ Trip cancelled. You are now available for other rides.", reply_markup=None)
    await call.answer()

# ----------------- Active Trip & Profile -----------------

@dp.message(F.text == "📋 Current Active Trip")
async def driver_view_active(message: Message):
    drv_id = message.from_user.id
    ride = db.get_active_driver_ride(drv_id)
    if not ride:
        await message.answer("You currently have no active trip.")
        return

    kb_rows = []
    if ride["status"] == "driver_accepted":
        kb_rows = [
            [InlineKeyboardButton(text="🚀 On the Way", callback_data=f"trip_dep:{ride['ride_id']}")],
            [InlineKeyboardButton(text="❌ Cancel Trip", callback_data=f"trip_cancel:{ride['ride_id']}")]
        ]
    elif ride["status"] == "departed":
        kb_rows = [
            [InlineKeyboardButton(text="🔑 Confirm PIN & Start Ride", callback_data=f"trip_pin:{ride['ride_id']}")],
            [InlineKeyboardButton(text="⏳ Passenger No-Show (5 mins)", callback_data=f"trip_noshow:{ride['ride_id']}")]
        ]
    elif ride["status"] == "arrived":
        kb_rows = [
            [InlineKeyboardButton(text="🔑 Confirm PIN & Start Ride", callback_data=f"trip_pin:{ride['ride_id']}")],
            [InlineKeyboardButton(text="⏳ Passenger No-Show (5 mins)", callback_data=f"trip_noshow:{ride['ride_id']}")]
        ]
    elif ride["status"] == "in_progress":
        kb_rows = [
            [InlineKeyboardButton(text="🏁 Complete Ride", callback_data=f"trip_complete:{ride['ride_id']}")]
        ]
        kb_rows = [
            [InlineKeyboardButton(text="📍 Arrived at Pickup", callback_data=f"trip_arr:{ride['ride_id']}")],
            [InlineKeyboardButton(text="❌ Cancel Trip", callback_data=f"trip_cancel:{ride['ride_id']}")]
        ]
    elif ride["status"] == "arrived":
        kb_rows = [
            [InlineKeyboardButton(text="🔑 Enter Passenger PIN", callback_data=f"trip_pin:{ride['ride_id']}")],
            [InlineKeyboardButton(text="⏳ Passenger No-Show (5 mins)", callback_data=f"trip_noshow:{ride['ride_id']}")]
        ]
    elif ride["status"] == "in_progress":
        kb_rows = [
            [InlineKeyboardButton(text="🏁 Complete Ride", callback_data=f"trip_complete:{ride['ride_id']}")]
        ]

    await message.answer(
        f"🚖 <b>Active Trip Details</b>\n\n"
        f"<b>Ride ID:</b> <code>{ride['ride_id']}</code>\n"
        f"<b>Route:</b> {ride['pickup']} ➡️ {ride['dropoff']}\n"
        f"<b>Status:</b> <code>{ride['status']}</code>\n"
        f"<b>Total Fare:</b> ₦{ride['total_fare']:,.2f}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None,
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "📊 My Profile & Rating")
async def driver_profile_view(message: Message):
    drv_id = message.from_user.id
    d = db.get_driver(drv_id)
    if not d:
        await message.answer("Driver profile not found.")
        return

    ratings = db.fetchall("SELECT stars, comment FROM ratings WHERE driver_id = ? ORDER BY created_at DESC LIMIT 3", (drv_id,))
    reviews_text = ""
    if ratings:
        reviews_text = "\n\n<b>Recent Student Reviews:</b>\n"
        for r in ratings:
            reviews_text += f"• ⭐ {r['stars']}/5: {r['comment'] or 'No comment'}\n"

    await message.answer(
        f"🚗 <b>Driver Profile</b>\n\n"
        f"Name: <b>{d['full_name']}</b>\n"
        f"Vehicle: <b>{d['car_model']}</b> (<code>{d['plate_number']}</code>)\n"
        f"Average Rating: ⭐ <b>{d['rating_avg']:.1f}</b> ({d['rating_count']} total ratings)\n"
        f"Duty Status: {'🟢 Online' if d['is_online'] else '🔴 Offline'}"
        f"{reviews_text}",
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text == "ℹ️ Campus Help")
async def driver_help_view(message: Message):
    await message.answer(
        f"ℹ️ <b>Driver Partner Dispatch Support</b>\n\n"
        f"Security & Dispatch: <code>{config.SUPPORT_PHONE}</code>\n"
        f"Office: <b>{config.DISPATCH_DESK}</b>\n\n"
        f"<b>Key Rules:</b>\n"
        f"• You have 2 minutes to accept incoming requests.\n"
        f"• Always confirm readiness 5 minutes before pickup.\n"
        f"• Never start a trip without entering the student's 4-digit PIN.\n"
        f"• Wait 5 minutes after arriving before marking a no-show.",
        parse_mode=ParseMode.HTML
    )

async def main():
    db.init_schema()
    token = config.DRIVER_BOT_TOKEN
    if not token:
        logger.error("DRIVER_BOT_TOKEN is not configured.")
        return

    global bot_instance
    bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    logger.info("Driver Bot starting polling...")
    await dp.start_polling(bot_instance)

if __name__ == "__main__":
    asyncio.run(main())
