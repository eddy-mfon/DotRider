"""
Covenant University Shuttle Bot Implementation
Complies with SRS requirements and telegram bot specifications:
- Section 1: Signing up and getting approved [FR-08, FR-09, FR-10, NFR-06, FR-06, NFR-24]
- Section 2: Going online and offline & document expiry [FR-11, FR-13]
- Section 3: Receiving and answering ride requests [FR-18, FR-19, FR-20, FR-23, FR-24, FR-44]
- Section 4: Updating the ride status with strict valid transitions [FR-25, FR-26, NFR-17, FR-70]
- Section 5: Cancelling a ride with recorded reasons [FR-27, FR-29]
- Section 6: Completing a ride with student verification PIN / OTP [FR-30, FR-31]
- Section 7: Ride history and categorized performance [FR-32, FR-33, FR-34, FR-35, NFR-02]
- Section 8: Payouts, earnings ledger & dispute resolution [FR-44]
- Section 9: Notification audit logging [FR-29, FR-71]
- Section 10: Reports, complaints and support [FR-53, FR-66, FR-67, FR-68]
- Section 11: Profile management & re-verification on critical updates [FR-12]
- Section 12 & 13: Security, Privacy, Reliability & Manual Dispatch [NFR-02, NFR-05, NFR-10, NFR-15, NFR-16, FR-50]
- Strict Role Separation: A user is either a Student OR a Driver, never both.
"""
import asyncio
import logging
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, BotCommand

import config
import keyboards as kb
from storage import storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ----------------- FSM States -----------------

class RegistrationFlow(StatesGroup):
    entering_name = State()
    entering_matric = State()
    entering_email = State()

class BookingFlow(StatesGroup):
    choosing_pickup = State()
    choosing_dropoff = State()
    choosing_passengers = State()
    confirming = State()

class DriverRegFlow(StatesGroup):
    accepting_privacy = State()
    entering_name = State()
    entering_phone = State()
    entering_id_number = State()
    entering_car = State()
    entering_plate = State()
    choosing_capacity = State()
    uploading_license = State()
    uploading_vehicle_photo = State()

class DriverOtpFlow(StatesGroup):
    entering_otp = State()

class DriverDisputeFlow(StatesGroup):
    entering_reason = State()

class DriverComplaintFlow(StatesGroup):
    entering_text = State()

class DriverVehicleUpdateFlow(StatesGroup):
    entering_new_details = State()

dp = Dispatcher(storage=MemoryStorage())
bot_instance: Bot | None = None

# ----------------- Role Guards & Audit Helpers -----------------

def check_role(user_id: int, required_role: str) -> bool:
    role = storage.get_user_role(user_id)
    return role == required_role

async def send_and_log(chat_id: int, text: str, event: str, reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    if not bot_instance:
        return
    try:
        await bot_instance.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        storage.log_notification(recipient_id=chat_id, event=event, status="delivered")
    except Exception as e:
        logger.error(f"Failed to send notification to {chat_id}: {e}")
        storage.log_notification(recipient_id=chat_id, event=event, status="failed", details=str(e))

# ----------------- Start & Welcome -----------------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    user_name = user.first_name if user else "User"
    user_id = user.id

    role = storage.get_user_role(user_id)

    # 1. Unassigned Role: Present Role Selection Gateway
    if role is None:
        welcome_text = (
            f"👋 **Welcome to dot.rider, {user_name}!**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎓 *Covenant University Campus Ride & Dispatch*\n\n"
            f"Please choose your account type to proceed:\n\n"
            f"• **Student:** Book shuttles across campus using your verified CU credentials.\n"
            f"• **Driver:** Register your vehicle, get approved, and earn by picking up campus rides.\n\n"
            f"⚠️ *Important: An account can only be a Student OR a Driver, not both.*"
        )
        await message.answer(
            welcome_text,
            reply_markup=kb.get_role_selection_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # 2. Driver Role
    if role == "driver":
        dp_profile = storage.get_driver_profile(user_id)
        if not dp_profile:
            await state.set_state(DriverRegFlow.accepting_privacy)
            await message.answer(
                f"{config.PRIVACY_NOTICE}\n\nDo you accept these terms to register as a Driver Partner?",
                reply_markup=kb.get_privacy_notice_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        is_approved = dp_profile.get("is_approved", False)
        is_online = dp_profile.get("is_online", False)
        has_active_trip = bool(dp_profile.get("current_ride_id"))
        status = dp_profile.get("status", "pending_verification")

        if status == "suspended":
            status_text = f"🛑 **Status:** SUSPENDED ({dp_profile.get('suspension_reason', 'Document Expired')})"
        elif not is_approved:
            status_text = "🟡 **Status:** Application Under Review / Pending Admin Approval"
        elif is_online:
            status_text = "🟢 **Duty:** Online (Available for Ride Dispatches)"
        else:
            status_text = "🔴 **Duty:** Offline (End of Duty)"

        driver_text = (
            f"🚗 **Driver Portal — Welcome, {dp_profile.get('full_name')}!**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{status_text}\n"
            f"🚘 **Vehicle:** {dp_profile.get('car_model')} (`{dp_profile.get('plate_number')}`)\n"
            f"👥 **Max Capacity:** {dp_profile.get('capacity')} passenger(s)\n"
            f"💳 **Pending Payout:** ₦{dp_profile.get('pending_payout', 0.0):,.0f}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Use the menu below to manage duty, review trips, or check payouts."
        )
        await message.answer(
            driver_text,
            reply_markup=kb.get_driver_main_menu(is_approved, is_online, has_active_trip),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # 3. Student Role
    user_data = storage.get_user(user_id)
    is_registered = bool(user_data and user_data.get("is_verified"))

    if not is_registered:
        welcome_text = (
            f"👋 **Welcome, {user_name}!**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎓 *Covenant University Campus Shuttle Dispatch*\n\n"
            f"To access student ride-booking across campus, you must complete your **Student Registration** with your official Covenant University credentials.\n\n"
            f"Click **📝 Register / Sign Up** below to begin."
        )
    else:
        welcome_text = (
            f"👋 **Welcome back, {user_name}!**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎓 *dot.rider — Campus Shuttle Dispatch*\n\n"
            f"Order rides between any campus pickup points including Chapel Shuttle Stand, Lecture Theatres, CST Building, CMSS Building, CEDS, CUCRID, Caf 2, and more.\n"
            f"💵 Flat Fare: **₦200** per passenger.\n\n"
            f"Tap **🚖 Book a Ride** below to get started:"
        )

    await message.answer(
        welcome_text,
        reply_markup=kb.get_main_menu_keyboard(is_registered=is_registered),
        parse_mode=ParseMode.MARKDOWN
    )

# ----------------- Role Selection Callback & Mock Tools -----------------

@dp.callback_query(F.data.startswith("select_role:"))
async def on_role_selected(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    current_role = storage.get_user_role(user_id)

    if role == "mock_driver":
        # Instantly configure mock driver
        storage.setup_mock_driver(user_id, name=f"Pilot Driver ({callback.from_user.first_name})")
        await callback.message.delete()
        await callback.message.answer(
            "🧪 **Mock Driver Mode Activated!**\n\n"
            "You are now an approved, online dot.rider driver with a pre-configured vehicle:\n"
            "• **Car:** Toyota Sienna Gold (`ABJ-999-CU`)\n"
            "• **Duty:** 🟢 Online & Available\n"
            "• **Starting Balance:** ₦1,500\n\n"
            "👇 **How to test:**\n"
            "1. Tap **🧪 Test Ride Request** below to simulate an incoming student ride dispatch.\n"
            "2. Tap **Accept Ride** to test the full live trip lifecycle!\n"
            "3. Switch back anytime with `/reset_role`.",
            reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=True),
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer("Mock Driver Active!")
        return

    if current_role and current_role != role:
        await callback.answer(f"❌ You are already registered as a {current_role.title()}! Use /reset_role to change.", show_alert=True)
        return

    storage.set_user_role(user_id, role)
    await callback.message.delete()

    if role == "student":
        user_data = storage.get_user(user_id) or {}
        is_registered = bool(user_data.get("is_verified"))
        await callback.message.answer(
            "🎓 **Student Account Initialized!**\n\n"
            "Please register with your Covenant University matriculation number and student email to unlock shuttle bookings.",
            reply_markup=kb.get_main_menu_keyboard(is_registered=is_registered),
            parse_mode=ParseMode.MARKDOWN
        )
    elif role == "driver":
        await state.set_state(DriverRegFlow.accepting_privacy)
        await callback.message.answer(
            f"{config.PRIVACY_NOTICE}\n\nDo you accept these terms to register as a Driver Partner?",
            reply_markup=kb.get_privacy_notice_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    await callback.answer()

@dp.message(Command("mock_driver", "mockdriver", "mock"))
@dp.message(F.text.startswith("/mock driver"))
@dp.message(F.text.startswith("/mock_driver"))
async def cmd_mock_driver(message: Message):
    """Instantly switches current user to an approved, online mock driver."""
    user = message.from_user
    name = f"Pilot Driver ({user.first_name})"
    storage.setup_mock_driver(user.id, name=name)
    await message.answer(
        "🧪 **Mock Driver Profile Activated!**\n\n"
        "You are now an approved, online driver.\n"
        "• Vehicle: Toyota Sienna Gold (`ABJ-999-CU`)\n"
        "• Capacity: 4 passengers\n"
        "• Duty: 🟢 Online\n\n"
        "Tap **🧪 Test Ride Request** on your keyboard below to simulate an incoming passenger request!",
        reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=True),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("reset_role", "resetrole", "reset"))
@dp.message(F.text.startswith("/reset role"))
@dp.message(F.text.startswith("/reset_role"))
async def cmd_reset_role(message: Message, state: FSMContext):
    """Allows testers to reset role between student and driver."""
    await state.clear()
    storage.reset_user_role(message.from_user.id)
    await message.answer(
        "🔄 **Role Reset Successful!**\n\n"
        "You can now choose a fresh role:",
        reply_markup=kb.get_role_selection_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("mock_request", "mockrequest"))
@dp.message(F.text == "🧪 Test Ride Request")
@dp.message(F.text.startswith("/mock request"))
@dp.message(F.text.startswith("/mock_request"))
async def cmd_mock_request(message: Message):
    """Simulates an incoming student ride dispatch directly to the driver."""
    if not check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ You must be in Driver Mode to test incoming requests. Use `/mock_driver` first.")
        return

    profile = storage.get_driver_profile(message.from_user.id)
    if profile and profile.get("current_ride_id"):
        await message.answer("⚠️ You already have an active trip! Please complete or cancel it first.")
        return

    # Create mock ride
    mock_ride = storage.create_ride(
        user_id=999999, # Mock student ID
        pickup="Chapel Shuttle Stand",
        dropoff="CMSS Building",
        passengers=2,
        base_fare=400,
        discount=0,
        final_fare=400,
        is_rush=False
    )
    # Ensure easy PIN for testing
    mock_ride["completion_otp"] = "1234"
    storage.save()

    alert_text = (
        f"🚖 **NEW RIDE DISPATCH ALERT! (TEST SIMULATION)**\n"
        f"🆔 Ref: `{mock_ride['ride_id']}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Pickup:** {mock_ride['pickup']} ({mock_ride['pickup_landmark']})\n"
        f"🏁 **Drop-off:** {mock_ride['dropoff']} ({mock_ride['dropoff_landmark']})\n"
        f"👥 **Passengers:** {mock_ride['passengers']} seat(s)\n"
        f"💵 **Your Payout:** **₦{mock_ride['driver_payout']:,.0f}**\n"
        f"🕒 **Pickup Time:** Immediate\n"
        f"🔑 *[Test Note: Student Completion PIN is `1234`]*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Tap **Accept** to claim this ride:"
    )
    await message.answer(
        alert_text,
        reply_markup=kb.get_dispatch_alert_keyboard(mock_ride['ride_id']),
        parse_mode=ParseMode.MARKDOWN
    )

# =========================================================================
# SECTION 1: DRIVER ONBOARDING & VERIFICATION [FR-08, FR-09, FR-10]
# =========================================================================

@dp.callback_query(DriverRegFlow.accepting_privacy, F.data == "driver_privacy_accept")
async def driver_privacy_accepted(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DriverRegFlow.entering_name)
    await callback.message.edit_text(
        "🚗 **Driver Onboarding — Step 1/7: Legal Name**\n\n"
        "Please enter your **Full Legal Name** (as shown on your driver's license):",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.callback_query(DriverRegFlow.accepting_privacy, F.data == "driver_privacy_decline")
async def driver_privacy_declined(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Driver registration cancelled. You can restart anytime with /start.")
    await callback.answer()

@dp.message(DriverRegFlow.entering_name)
async def process_driver_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("⚠️ Please enter a valid full name.")
        return
    await state.update_data(full_name=name)
    await state.set_state(DriverRegFlow.entering_phone)
    await message.answer(
        "📞 **Step 2/7: Phone Number**\n\n"
        "Enter your active phone number for passenger and dispatch contact (e.g. `08012345678`):",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(DriverRegFlow.entering_phone)
async def process_driver_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 10:
        await message.answer("⚠️ Please enter a valid phone number (at least 10 digits):")
        return
    await state.update_data(phone=phone)
    await state.set_state(DriverRegFlow.entering_id_number)
    await message.answer(
        "🪪 **Step 3/7: Identification Number**\n\n"
        "Enter your National ID (NIN), driver's license number, or Covenant University staff/permit number:",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(DriverRegFlow.entering_id_number)
async def process_driver_id_num(message: Message, state: FSMContext):
    id_num = message.text.strip().upper()
    if len(id_num) < 4:
        await message.answer("⚠️ Please enter a valid identification number:")
        return
    await state.update_data(id_number=id_num)
    await state.set_state(DriverRegFlow.entering_car)
    await message.answer(
        "🚘 **Step 4/7: Vehicle Make, Model & Colour**\n\n"
        "Enter your vehicle details (e.g., `Toyota Sienna (Gold)` or `Toyota Corolla (Silver)`):",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(DriverRegFlow.entering_car)
async def process_driver_car(message: Message, state: FSMContext):
    car = message.text.strip()
    if len(car) < 3:
        await message.answer("⚠️ Please enter valid vehicle details:")
        return
    await state.update_data(car_model=car)
    await state.set_state(DriverRegFlow.entering_plate)
    await message.answer(
        "🔢 **Step 5/7: Vehicle License Plate Number**\n\n"
        "Enter your official plate number (e.g., `ABJ-123-XY`):",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(DriverRegFlow.entering_plate)
async def process_driver_plate(message: Message, state: FSMContext):
    plate = message.text.strip().upper()
    if len(plate) < 4:
        await message.answer("⚠️ Please enter a valid plate number:")
        return
    await state.update_data(plate_number=plate)
    await state.set_state(DriverRegFlow.choosing_capacity)
    await message.answer(
        "👥 **Step 6/7: Maximum Passenger Capacity**\n\n"
        "Select the maximum permitted passenger capacity for your vehicle (1 to 4):",
        reply_markup=kb.get_driver_capacity_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(DriverRegFlow.choosing_capacity, F.data.startswith("driver_cap:"))
async def process_driver_capacity(callback: CallbackQuery, state: FSMContext):
    cap = int(callback.data.split(":", 1)[1])
    await state.update_data(capacity=cap)
    await state.set_state(DriverRegFlow.uploading_license)
    await callback.message.edit_text(
        f"✅ Passenger Capacity: **{cap} Passengers**\n\n"
        f"📄 **Step 7/7: Driver's License & Document Photo**\n\n"
        f"Please send a clear **photo** of your valid Driver's Licence (or roadworthiness/insurance document):",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.message(DriverRegFlow.uploading_license)
async def process_driver_license_upload(message: Message, state: FSMContext):
    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text:
        photo_id = f"text_ref:{message.text.strip()}"
    else:
        await message.answer("⚠️ Please send a photo of your Driver's License or document:")
        return

    data = await state.get_data()
    full_name = data.get("full_name")
    phone = data.get("phone")
    id_number = data.get("id_number")
    car_model = data.get("car_model")
    plate_number = data.get("plate_number")
    capacity = data.get("capacity", 4)

    storage.register_driver(
        user_id=message.from_user.id,
        full_name=full_name,
        phone=phone,
        car_model=car_model,
        plate_number=plate_number,
        capacity=capacity,
        license_photo_id=photo_id,
        id_number=id_number
    )
    await state.clear()

    await message.answer(
        "🎉 **Driver Application Submitted Successfully!**\n\n"
        "Your profile and vehicle documents have been securely uploaded and are now under review by the dot.rider campus administrator.\n\n"
        "You will receive a notification as soon as your account is approved.",
        reply_markup=kb.get_driver_main_menu(is_approved=False, is_online=False),
        parse_mode=ParseMode.MARKDOWN
    )

    # Bridge to Admin for Instant Review if ADMIN_CHAT_ID is set
    if config.ADMIN_CHAT_ID and bot_instance:
        admin_card = (
            f"🚨 **NEW DRIVER APPLICATION RECEIVED**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Name:** {full_name}\n"
            f"📞 **Phone:** `{phone}`\n"
            f"🪪 **ID / NIN:** `{id_number}`\n"
            f"🚘 **Vehicle:** {car_model} (`{plate_number}`)\n"
            f"👥 **Capacity:** {capacity} passenger(s)\n"
            f"🆔 **Driver User ID:** `{message.from_user.id}`\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        try:
            if message.photo:
                await bot_instance.send_photo(
                    chat_id=config.ADMIN_CHAT_ID,
                    photo=photo_id,
                    caption=admin_card,
                    reply_markup=kb.get_admin_driver_review_keyboard(message.from_user.id),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await bot_instance.send_message(
                    chat_id=config.ADMIN_CHAT_ID,
                    text=admin_card,
                    reply_markup=kb.get_admin_driver_review_keyboard(message.from_user.id),
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.error(f"Failed to forward driver application to admin: {e}")

# =========================================================================
# SECTION 2: GOING ONLINE/OFFLINE & DOCUMENT EXPIRY [FR-11, FR-13]
# =========================================================================

@dp.message(F.text == "🟢 Go Online (Ready for Rides)")
async def driver_go_online(message: Message):
    if not check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Only registered drivers can use this feature.")
        return

    success, msg = storage.set_driver_online(message.from_user.id, True)
    if not success:
        profile = storage.get_driver_profile(message.from_user.id) or {}
        reason = profile.get("rejection_reason") or profile.get("suspension_reason") or msg
        await message.answer(
            f"🔒 **Unable to Go Online**\n\n"
            f"Reason: {reason}\n\n"
            f"Please check your approval status or document validity before taking rides.",
            reply_markup=kb.get_driver_main_menu(is_approved=profile.get("is_approved", False), is_online=False),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await message.answer(
        "🟢 **You are now ONLINE & AVAILABLE for ride requests!**\n\n"
        "You will receive incoming dispatch requests matching your vehicle capacity across campus.",
        reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=True),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(F.text == "🔴 Go Offline (End Duty)")
async def driver_go_offline(message: Message):
    if not check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Only registered drivers can use this feature.")
        return

    profile = storage.get_driver_profile(message.from_user.id) or {}
    if profile.get("current_ride_id"):
        await message.answer("⚠️ You cannot go offline during an ongoing trip! Please complete or cancel your active ride first.")
        return

    storage.set_driver_online(message.from_user.id, False)
    await message.answer(
        "🔴 **You are now OFFLINE (Unavailable).**\n\n"
        "You will no longer receive new ride dispatch requests. Rest well!",
        reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=False),
        parse_mode=ParseMode.MARKDOWN
    )

# =========================================================================
# SECTION 3: RECEIVING & ANSWERING RIDE REQUESTS [FR-18, FR-19, FR-23, FR-24, FR-44]
# =========================================================================

@dp.callback_query(F.data.startswith("d_accept:"))
async def on_driver_accept(callback: CallbackQuery):
    ride_id = callback.data.split(":", 1)[1]
    driver_id = callback.from_user.id

    if not check_role(driver_id, "driver"):
        await callback.answer("❌ Only registered drivers can accept rides.", show_alert=True)
        return

    # FR-23 / FR-24: Concurrency control & atomic assignment
    success = storage.assign_driver_to_ride(ride_id, driver_id)
    if not success:
        await callback.answer("⚠️ This ride was already claimed by another driver or cancelled.", show_alert=True)
        await callback.message.edit_text("❌ **Ride Unavailable:** Claimed by another driver or cancelled.")
        return

    ride = storage.get_ride(ride_id)
    driver_profile = storage.get_driver_profile(driver_id)

    # 1. Update Driver UI with Active Trip Control
    card = (
        f"🎉 **RIDE ACCEPTED & ASSIGNED!**\n"
        f"🆔 **Booking Ref:** `{ride_id}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Pickup:** {ride['pickup']} ({ride['pickup_landmark']})\n"
        f"🏁 **Drop-off:** {ride['dropoff']} ({ride['dropoff_landmark']})\n"
        f"👥 **Passengers:** {ride['passengers']}\n"
        f"💵 **Estimated Earnings:** **₦{ride['driver_payout']:,.0f}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Tap **🚗 On the way to pickup** when you head out:"
    )
    await callback.message.edit_text(
        card,
        reply_markup=kb.get_driver_trip_keyboard(ride_id, "confirmed"),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer("Ride accepted!")

    # 2. Push Notification to the Student with Driver Details & OTP (FR-31)
    student_id = ride.get("user_id")
    if student_id:
        student_alert = (
            f"🎉 **DRIVER FOUND & ASSIGNED!**\n"
            f"🆔 **Booking Ref:** `{ride_id}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👨‍✈️ **Driver:** {driver_profile.get('full_name')}\n"
            f"📞 **Phone:** `{driver_profile.get('phone')}`\n"
            f"🚘 **Vehicle:** {driver_profile.get('car_model')}\n"
            f"🔢 **Plate No:** `{driver_profile.get('plate_number')}`\n"
            f"📍 **Designated Meeting Point:** {ride['pickup_landmark']}\n"
            f"🔑 **Completion PIN:** `{ride['completion_otp']}` (Share with driver at drop-off)\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        await send_and_log(
            chat_id=student_id,
            text=student_alert,
            event="driver_assigned",
            reply_markup=kb.get_ride_action_keyboard(ride_id)
        )

@dp.callback_query(F.data.startswith("d_decline:"))
async def on_driver_decline(callback: CallbackQuery):
    ride_id = callback.data.split(":", 1)[1]
    storage.record_driver_decline(ride_id, callback.from_user.id)
    await callback.message.edit_text("❌ Ride request declined.")
    await callback.answer("Declined.")

# =========================================================================
# SECTION 4 & 6: ACTIVE TRIP LIFECYCLE & PIN COMPLETION [FR-25, FR-30, FR-31, NFR-17]
# =========================================================================

@dp.message(F.text == "📋 Current Active Trip")
async def driver_show_current_trip(message: Message):
    if not check_role(message.from_user.id, "driver"):
        return
    profile = storage.get_driver_profile(message.from_user.id) or {}
    ride_id = profile.get("current_ride_id")
    if not ride_id:
        await message.answer("ℹ️ You do not have an active trip right now.")
        return

    ride = storage.get_ride(ride_id)
    if not ride:
        await message.answer("ℹ️ Active trip record not found.")
        return

    status = ride.get("status", "confirmed")
    card = (
        f"🚖 **Active Trip — `{ride_id}`**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Pickup:** {ride['pickup']} ({ride['pickup_landmark']})\n"
        f"🏁 **Drop-off:** {ride['dropoff']} ({ride['dropoff_landmark']})\n"
        f"👥 **Passengers:** {ride['passengers']}\n"
        f"💵 **Your Payout:** ₦{ride['driver_payout']:,.0f}\n"
        f"📊 **Status:** 🟢 {status.replace('_', ' ').title()}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(
        card,
        reply_markup=kb.get_driver_trip_keyboard(ride_id, status),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data.startswith("d_trip_action:"))
async def on_driver_trip_action(callback: CallbackQuery):
    parts = callback.data.split(":")
    ride_id = parts[1]
    new_status = parts[2]
    driver_id = callback.from_user.id

    ride = storage.get_ride(ride_id)
    if not ride or ride.get("driver_id") != driver_id:
        await callback.answer("⚠️ Trip not found or not assigned to you.", show_alert=True)
        return

    driver_profile = storage.get_driver_profile(driver_id)
    success, msg = storage.update_ride_progress(ride_id, new_status)
    if not success:
        await callback.answer(f"⚠️ {msg}", show_alert=True)
        return

    student_id = ride.get("user_id")

    if new_status == "driver_en_route":
        await callback.message.edit_text(
            f"🚗 **On the way to pickup**\n\nHeading to **{ride['pickup']}** ({ride['pickup_landmark']}).\n\nWhen you arrive and complete the ride, tap **Ride Completed** to enter the student's PIN.",
            reply_markup=kb.get_driver_trip_keyboard(ride_id, "driver_en_route"),
            parse_mode=ParseMode.MARKDOWN
        )
        if student_id:
            await send_and_log(
                chat_id=student_id,
                text=f"🚗 **Update:** Your driver ({driver_profile.get('full_name')}) is now **on the way to pickup** at **{ride['pickup']}** ({ride['pickup_landmark']}).",
                event="driver_en_route"
            )
        await callback.answer("Status: On the way to pickup")

# ----------------- Ride Completion with OTP (FR-31) -----------------

@dp.callback_query(F.data.startswith("d_trip_prompt_otp:"))
async def on_prompt_otp(callback: CallbackQuery, state: FSMContext):
    ride_id = callback.data.split(":", 1)[1]
    await state.update_data(completing_ride_id=ride_id)
    await state.set_state(DriverOtpFlow.entering_otp)
    await callback.message.answer(
        f"🔐 **Completion Verification (FR-31)**\n\n"
        f"Please ask the student for their **4-digit Completion PIN** and send it here to finalize the ride:",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.message(DriverOtpFlow.entering_otp)
async def process_otp_verification(message: Message, state: FSMContext):
    entered_pin = message.text.strip()
    data = await state.get_data()
    ride_id = data.get("completing_ride_id")

    if not ride_id:
        await state.clear()
        return

    success, msg = storage.verify_and_complete_ride(ride_id, entered_pin)
    if not success:
        await message.answer(f"⚠️ {msg}\nPlease check with the passenger and enter the 4 digits:")
        return

    await state.clear()
    ride = storage.get_ride(ride_id)
    payout = ride.get("driver_payout", 0.0)

    await message.answer(
        f"🏁 **Trip Successfully Completed & Verified!**\n\n"
        f"🆔 Ref: `{ride_id}`\n"
        f"💵 Payout Earned: **₦{payout:,.0f}**\n"
        f"Your payout balance has been credited.",
        reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=True),
        parse_mode=ParseMode.MARKDOWN
    )

    student_id = ride.get("user_id")
    if student_id:
        await send_and_log(
            chat_id=student_id,
            text=(
                f"🏁 **Trip Completed!**\n\n"
                f"You have arrived safely at **{ride['dropoff']}**.\n"
                f"Total Paid: ₦{ride.get('final_fare', 0):,.0f}.\n\n"
                f"Thank you for choosing dot.rider!"
            ),
            event="ride_completed",
            reply_markup=kb.get_main_menu_keyboard(is_registered=True)
        )

# =========================================================================
# SECTION 5: CANCELLING A RIDE WITH REASONS [FR-27, FR-29]
# =========================================================================

@dp.callback_query(F.data.startswith("d_trip_cancel_prompt:"))
async def on_driver_cancel_prompt(callback: CallbackQuery):
    ride_id = callback.data.split(":", 1)[1]
    await callback.message.edit_text(
        f"⚠️ **Cancel Trip `{ride_id}`**\n\n"
        f"Please select the reason for cancellation (recorded for admin review):",
        reply_markup=kb.get_driver_cancel_reasons_keyboard(ride_id),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("d_cancel_reason:"))
async def on_driver_cancel_confirmed(callback: CallbackQuery):
    parts = callback.data.split(":")
    ride_id = parts[1]
    reason = parts[2]
    driver_id = callback.from_user.id

    ride = storage.get_ride(ride_id)
    if not ride or ride.get("driver_id") != driver_id:
        await callback.answer("Ride not found.")
        return

    storage.update_ride_progress(ride_id, "cancelled", note=f"Driver cancelled: {reason}")
    await callback.message.edit_text(
        f"🚫 **Trip `{ride_id}` Cancelled**\n"
        f"Reason recorded: _{reason}_.\n"
        f"You are now back online for new dispatches.",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.message.answer(
        "👇 Ready for requests:",
        reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=True)
    )

    student_id = ride.get("user_id")
    if student_id:
        await send_and_log(
            chat_id=student_id,
            text=(
                f"⚠️ **Booking `{ride_id}` was cancelled by the driver.**\n"
                f"Reason: _{reason}_\n\n"
                f"You can request another ride immediately using the menu below."
            ),
            event="driver_cancelled_ride",
            reply_markup=kb.get_main_menu_keyboard(is_registered=True)
        )

    # Notify admin of driver cancellation (FR-27)
    if config.ADMIN_CHAT_ID:
        await send_and_log(
            chat_id=int(config.ADMIN_CHAT_ID),
            text=f"🚨 **Cancellation Alert:** Ride `{ride_id}` cancelled by driver `{driver_id}` (Reason: {reason})",
            event="admin_cancel_alert"
        )
    await callback.answer("Trip cancelled.")

@dp.callback_query(F.data.startswith("d_trip_back:"))
async def on_driver_trip_back(callback: CallbackQuery):
    ride_id = callback.data.split(":", 1)[1]
    ride = storage.get_ride(ride_id)
    status = ride.get("status", "confirmed") if ride else "confirmed"
    await callback.message.edit_text(
        f"🚖 **Trip `{ride_id}` Resumed**",
        reply_markup=kb.get_driver_trip_keyboard(ride_id, status)
    )
    await callback.answer()

# =========================================================================
# SECTION 7 & 8: HISTORY, PERFORMANCE, PAYOUTS & DISPUTES [FR-32-35, FR-44]
# =========================================================================

@dp.message(F.text == "📊 My Earnings & Payouts")
async def driver_show_earnings(message: Message):
    if not check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Only registered drivers can view earnings.")
        return

    driver_id = message.from_user.id
    profile = storage.get_driver_profile(driver_id) or {}
    cats = storage.get_driver_ride_categories(driver_id)

    completed_rides = cats["completed"]
    cancelled_rides = cats["cancelled"]
    declined_count = cats["declined_count"]

    total_completed = len(completed_rides)
    total_cancelled = len(cancelled_rides)
    total_trips = total_completed + total_cancelled
    completion_rate = round((total_completed / total_trips * 100), 1) if total_trips > 0 else 100.0

    earnings = profile.get("earnings_balance", 0.0)
    pending_payout = profile.get("pending_payout", 0.0)
    payout_status = profile.get("payout_status", "pending").upper()

    summary_text = (
        f"📊 **Driver Earnings & Performance (FR-34, FR-44)**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏁 **Completed Rides:** {total_completed}\n"
        f"🚫 **Cancelled Rides:** {total_cancelled}\n"
        f"❌ **Declined Requests:** {declined_count}\n"
        f"📈 **Completion Rate:** {completion_rate}%\n"
        f"💵 **Total Earned:** ₦{earnings:,.0f}\n"
        f"💳 **Payout Balance Due:** **₦{pending_payout:,.0f}**\n"
        f"⚖️ **Payout Status:** `{payout_status}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 **Recent Completed Trips:**\n"
    )

    if not completed_rides:
        summary_text += "_No completed trips recorded yet._\n"
    else:
        for r in completed_rides[:5]:
            summary_text += f"• `{r['ride_id']}`: {r['pickup']} ➡️ {r['dropoff']} (+₦{r.get('driver_payout', 0):,.0f})\n"

    if cancelled_rides:
        summary_text += f"\n⚠️ **Recent Cancelled Trips ({len(cancelled_rides)}):**\n"
        for cr in cancelled_rides[:3]:
            summary_text += f"• `{cr['ride_id']}`: _{cr.get('cancellation_reason', 'No reason logged')}_\n"

    await message.answer(
        summary_text,
        reply_markup=kb.get_payout_actions_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data == "driver_raise_dispute")
async def on_prompt_dispute(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DriverDisputeFlow.entering_reason)
    await callback.message.answer(
        "⚖️ **Raise Payout Dispute (FR-44)**\n\n"
        "Please enter the Booking Ref (if applicable) and describe the discrepancy or issue with your payout:",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.message(DriverDisputeFlow.entering_reason)
async def process_dispute_submission(message: Message, state: FSMContext):
    reason = message.text.strip()
    if len(reason) < 5:
        await message.answer("⚠️ Please provide a clear explanation for the dispute:")
        return

    success, disp_id = storage.raise_payout_dispute(message.from_user.id, "GENERAL", reason)
    await state.clear()

    await message.answer(
        f"✅ **Payout Dispute Lodged!**\n\n"
        f"Dispute Ref: `{disp_id}`\n"
        f"The dispatch finance team has been notified and will review your records.",
        parse_mode=ParseMode.MARKDOWN
    )
    if config.ADMIN_CHAT_ID:
        await send_and_log(
            chat_id=int(config.ADMIN_CHAT_ID),
            text=f"🚨 **NEW PAYOUT DISPUTE `{disp_id}`**\nDriver: `{message.from_user.id}`\nDetails: {reason}",
            event="payout_dispute_alert"
        )

# =========================================================================
# SECTION 10 & 11: COMPLAINTS, SUPPORT & PROFILE UPDATES [FR-12, FR-53, FR-66]
# =========================================================================

@dp.message(F.text == "🚗 My Vehicle & Profile")
async def driver_show_profile(message: Message):
    if not check_role(message.from_user.id, "driver"):
        return

    profile = storage.get_driver_profile(message.from_user.id) or {}
    status_label = "✅ Approved" if profile.get("is_approved") else f"🟡 {profile.get('status', 'Pending').title()}"
    duty_label = "🟢 Online" if profile.get("is_online") else "🔴 Offline"

    text = (
        f"🚗 **Driver & Vehicle Profile (FR-12)**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Name:** {profile.get('full_name', 'N/A')}\n"
        f"📞 **Phone:** `{profile.get('phone', 'N/A')}`\n"
        f"🪪 **ID / NIN:** `{profile.get('id_number', 'N/A')}`\n"
        f"🚘 **Vehicle:** {profile.get('car_model', 'N/A')}\n"
        f"🔢 **Plate No:** `{profile.get('plate_number', 'N/A')}`\n"
        f"👥 **Max Capacity:** {profile.get('capacity', 4)} passenger(s)\n"
        f"🛡️ **Status:** {status_label}\n"
        f"📡 **Duty:** {duty_label}\n"
        f"📅 **License Expiry:** `{profile.get('license_expiry')}`\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(
        text,
        reply_markup=kb.get_driver_support_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data == "driver_req_update")
async def on_prompt_vehicle_update(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DriverVehicleUpdateFlow.entering_new_details)
    await callback.message.answer(
        "⚠️ **Vehicle Information Update (FR-12)**\n\n"
        "Notice: Changing your vehicle or license plate requires **administrative re-verification** before you can take rides again.\n\n"
        "Please send your new vehicle details in the format:\n"
        "`<Car Make/Model> | <Plate Number>`\n"
        "Example: `Toyota Camry (Black) | KJA-567-ZZ`",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.message(DriverVehicleUpdateFlow.entering_new_details)
async def process_vehicle_update(message: Message, state: FSMContext):
    text = message.text.strip()
    if "|" not in text:
        await message.answer("⚠️ Please format as: `<Car Make/Model> | <Plate Number>`")
        return
    car, plate = text.split("|", 1)
    storage.request_critical_update(message.from_user.id, car.strip(), plate.strip())
    await state.clear()

    await message.answer(
        "✅ **Vehicle Details Updated & Sent for Re-Verification!**\n\n"
        "Your account is set to `pending_verification` until the campus administrator approves the new vehicle.",
        reply_markup=kb.get_driver_main_menu(is_approved=False, is_online=False)
    )

@dp.callback_query(F.data == "driver_report_issue")
async def on_prompt_complaint(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DriverComplaintFlow.entering_text)
    await callback.message.answer(
        "📝 **Submit Driver Report / Complaint (FR-66)**\n\n"
        "Describe the operational issue, campus security concern, or student misconduct:",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.message(DriverComplaintFlow.entering_text)
async def process_complaint_text(message: Message, state: FSMContext):
    text = message.text.strip()
    cid = storage.submit_complaint(message.from_user.id, "driver", text)
    await state.clear()
    await message.answer(
        f"✅ **Report Filed Successfully!** (Ref: `{cid}`)\nCampus shuttle dispatch will investigate.",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(F.text == "🔄 Check Approval Status")
async def driver_check_status(message: Message):
    if not check_role(message.from_user.id, "driver"):
        return
    profile = storage.get_driver_profile(message.from_user.id) or {}
    status = profile.get("status", "pending_verification")
    if profile.get("is_approved"):
        await message.answer(
            "✅ **Your Driver Account is Approved & Active!**\nTap '🟢 Go Online' to start receiving rides.",
            reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=profile.get("is_online", False))
        )
    elif status == "rejected":
        await message.answer(f"❌ **Application Rejected:** {profile.get('rejection_reason', 'Did not meet requirements')}.")
    elif status == "suspended":
        await message.answer(f"🛑 **Account Suspended:** {profile.get('suspension_reason', 'Policy violation')}.")
    else:
        await message.answer("⏳ **Application Pending:** Your documents are currently under review by campus dispatch.")

# =========================================================================
# SECTION 14 & 16: ADMIN ACTIONS & MANUAL DISPATCH [FR-10, FR-48, FR-50]
# =========================================================================

@dp.callback_query(F.data.startswith("adm_appr:"))
async def on_admin_approve(callback: CallbackQuery):
    target_uid = int(callback.data.split(":", 1)[1])
    storage.approve_driver(target_uid)
    await callback.message.edit_caption(
        caption=f"{callback.message.caption or ''}\n\n✅ **APPROVED by Admin**",
        reply_markup=None,
        parse_mode=ParseMode.MARKDOWN
    )
    await send_and_log(
        chat_id=target_uid,
        text=(
            "🎉 **Congratulations! Your dot.rider Driver Account has been APPROVED!**\n\n"
            "You are authorized to accept passenger rides across Covenant University.\n"
            "Tap **🟢 Go Online** below to start receiving dispatch requests!"
        ),
        event="driver_approved",
        reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=False)
    )
    await callback.answer("Driver Approved!")

@dp.callback_query(F.data.startswith("adm_rej:"))
async def on_admin_reject(callback: CallbackQuery):
    target_uid = int(callback.data.split(":", 1)[1])
    storage.reject_driver(target_uid, reason="Documentation verification failed")
    await callback.message.edit_caption(
        caption=f"{callback.message.caption or ''}\n\n❌ **REJECTED by Admin**",
        reply_markup=None,
        parse_mode=ParseMode.MARKDOWN
    )
    await send_and_log(
        chat_id=target_uid,
        text="❌ **Your Driver Application was rejected.** Reason: Documentation verification failed.",
        event="driver_rejected",
        reply_markup=kb.get_driver_main_menu(is_approved=False, is_online=False)
    )
    await callback.answer("Driver Rejected.")

@dp.message(Command("admin_approve", "approve", "adminapprove"))
@dp.message(F.text.startswith("/admin approve"))
@dp.message(F.text.startswith("/admin_approve"))
async def cmd_admin_approve(message: Message):
    # Support both "/admin_approve 12345" and "/admin approve 12345"
    text = message.text.replace("/admin approve", "/admin_approve")
    parts = text.split(maxsplit=1)
    
    if len(parts) >= 2 and parts[1].strip().isdigit():
        try:
            uid = int(parts[1].strip())
            storage.approve_driver(uid)
            await message.answer(f"✅ Driver `{uid}` approved successfully!", parse_mode=ParseMode.MARKDOWN)
            await send_and_log(
                chat_id=uid,
                text="🎉 **Your Driver Account has been APPROVED!** Tap **🟢 Go Online** to start.",
                event="driver_approved",
                reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=False)
            )
            return
        except Exception as e:
            await message.answer(f"Error: {e}")
            return

    # If called without an ID or with no arguments: Show interactive list of pending drivers
    pending = storage.get_all_pending_drivers()
    if pending:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for uid, dp_info in pending:
            buttons.append([InlineKeyboardButton(text=f"✅ Approve {dp_info.get('full_name')} (`{uid}`)", callback_data=f"adm_appr:{uid}")])
        buttons.append([InlineKeyboardButton(text=f"⚡ Approve My Account (`{message.from_user.id}`)", callback_data=f"adm_appr:{message.from_user.id}")])
        await message.answer(
            "🛡️ **Admin Driver Approval Panel**\n\nSelect a driver application to approve:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        btn = [[InlineKeyboardButton(text="⚡ Approve My Account as Driver", callback_data=f"adm_appr:{message.from_user.id}")]]
        await message.answer(
            "ℹ️ No pending driver applications found.\n\n"
            "To approve yourself for testing, tap below:\n"
            "Or use: `/admin_approve <user_id>`",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=btn),
            parse_mode=ParseMode.MARKDOWN
        )

@dp.message(Command("manual_dispatch", "manualdispatch", "dispatch", "manuel_dispatch", "manueldispatch"))
@dp.message(F.text.startswith("/manual dispatch"))
@dp.message(F.text.startswith("/manuel disptach"))
@dp.message(F.text.startswith("/manuel dispatch"))
@dp.message(F.text.startswith("/manual_dispatch"))
async def cmd_manual_dispatch(message: Message):
    """FR-50: Manual dispatch fallback by administrator"""
    raw_text = message.text
    for prefix in ["/manual dispatch", "/manuel disptach", "/manuel dispatch", "/manuel_dispatch", "/manualdispatch", "/dispatch"]:
        if raw_text.startswith(prefix):
            raw_text = raw_text.replace(prefix, "/manual_dispatch", 1)
            break

    parts = raw_text.split()
    if len(parts) < 3:
        # Show interactive pending rides to dispatch
        pending_rides = [r for r in storage.data["rides"].values() if r.get("status") == "pending_assignment"]
        online_drivers = storage.get_online_drivers()
        
        info = "🛡️ **Manual Dispatch Console (FR-50)**\n\n"
        if not pending_rides:
            info += "• No pending ride requests awaiting dispatch.\n"
        else:
            info += f"• **Pending Rides ({len(pending_rides)}):**\n"
            for pr in pending_rides[:5]:
                info += f"  - Ref: `{pr['ride_id']}` | Route: {pr['pickup']} ➡️ {pr['dropoff']}\n"
                
        if not online_drivers:
            info += "\n• No approved drivers currently online.\n"
        else:
            info += f"\n• **Available Online Drivers ({len(online_drivers)}):**\n"
            for duid, dp_p in online_drivers:
                info += f"  - ID: `{duid}` | {dp_p.get('full_name')} ({dp_p.get('car_model')})\n"
                
        info += "\n👉 **Usage:** `/manual_dispatch <ride_id> <driver_id>`\n"
        info += "Example: `/manual_dispatch DOT-12345678 123456789`"
        await message.answer(info, parse_mode=ParseMode.MARKDOWN)
        return

    ride_id = parts[1].strip().upper()
    try:
        driver_id = int(parts[2].strip())
    except ValueError:
        await message.answer("Driver ID must be an integer number.")
        return

    success, msg = storage.manual_dispatch_by_admin(ride_id, driver_id, message.from_user.id)
    if not success:
        await message.answer(f"❌ Failed: {msg}")
        return

    ride = storage.get_ride(ride_id)
    dp_prof = storage.get_driver_profile(driver_id)
    await message.answer(f"✅ Ride `{ride_id}` manually dispatched to driver `{driver_id}` ({dp_prof.get('full_name')})!")

    # Alert driver
    card = (
        f"🚨 **ADMIN MANUAL DISPATCH ASSIGNMENT!**\n"
        f"🆔 Ref: `{ride_id}`\n"
        f"📍 Pickup: {ride['pickup']} ({ride['pickup_landmark']})\n"
        f"🏁 Drop-off: {ride['dropoff']} ({ride['dropoff_landmark']})\n"
        f"👥 Passengers: {ride['passengers']}\n"
        f"💵 Payout: ₦{ride['driver_payout']:,.0f}"
    )
    await send_and_log(
        chat_id=driver_id,
        text=card,
        event="admin_manual_dispatch",
        reply_markup=kb.get_driver_trip_keyboard(ride_id, "confirmed")
    )

    # Alert student
    student_id = ride.get("user_id")
    if student_id:
        await send_and_log(
            chat_id=student_id,
            text=(
                f"🎉 **Driver Manually Assigned by Dispatch!**\n"
                f"Driver: {dp_prof.get('full_name')} ({dp_prof.get('car_model')}, `{dp_prof.get('plate_number')}`).\n"
                f"Meeting Point: **{ride['pickup_landmark']}**\n"
                f"Completion PIN: `{ride['completion_otp']}`"
            ),
            event="manual_driver_assigned",
            reply_markup=kb.get_ride_action_keyboard(ride_id)
        )


# =========================================================================
# STUDENT POV: REGISTRATION, BOOKING & CANCELLATION
# =========================================================================

@dp.message(F.text == "📝 Register / Sign Up")
async def start_registration(message: Message, state: FSMContext):
    if check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Drivers cannot register as students. Account roles are mutually exclusive.")
        return

    user_data = storage.get_user(message.from_user.id)
    if user_data and user_data.get("is_verified"):
        await message.answer(
            "✅ You are already a verified Covenant University student!\n"
            "You can book rides directly from the menu.",
            reply_markup=kb.get_main_menu_keyboard(is_registered=True)
        )
        return

    storage.set_user_role(message.from_user.id, "student")
    await state.set_state(RegistrationFlow.entering_name)
    await message.answer(
        "📝 **Student Registration — Step 1/3**\n\n"
        "Please enter your **Full Name** (e.g., David Ogunleye):",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(RegistrationFlow.entering_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("⚠️ Please enter a valid full name.")
        return
    await state.update_data(full_name=name)
    await state.set_state(RegistrationFlow.entering_matric)
    await message.answer(
        "🎓 **Step 2/3: Matriculation Number**\n\n"
        "Please enter your Covenant University matric number (e.g. `21CJ028123`):",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(RegistrationFlow.entering_matric)
async def process_matric(message: Message, state: FSMContext):
    matric = message.text.strip().upper()
    if len(matric) < 6:
        await message.answer("⚠️ Invalid matriculation number format. Please check and re-enter:")
        return

    existing = storage.find_user_by_matric(matric, exclude_uid=message.from_user.id)
    if existing:
        await message.answer(
            f"❌ An account has already been registered with matric number `{matric}`.\n"
            "If this belongs to you, please contact support.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await state.update_data(matric_no=matric)
    await state.set_state(RegistrationFlow.entering_email)
    await message.answer(
        "📧 **Step 3/3: Official Student Email**\n\n"
        "Please enter your university email address (`@stu.cu.edu.ng` or `@covenantuniversity.edu.ng`):",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(RegistrationFlow.entering_email)
async def process_email(message: Message, state: FSMContext):
    email = message.text.strip().lower()
    if not (email.endswith("@stu.cu.edu.ng") or email.endswith("@covenantuniversity.edu.ng")):
        await message.answer(
            "⚠️ Ineligible email domain!\n"
            "Must be an official university email ending in `@stu.cu.edu.ng` or `@covenantuniversity.edu.ng`.\n\n"
            "Please enter your valid university email:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    existing = storage.find_user_by_email(email, exclude_uid=message.from_user.id)
    if existing:
        await message.answer(
            f"❌ An account has already been registered with email `{email}`.\n"
            "Please use your own unique credentials or contact support.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    data = await state.get_data()
    full_name = data.get("full_name")
    matric_no = data.get("matric_no")

    storage.update_user(
        message.from_user.id,
        role="student",
        name=full_name,
        matric_no=matric_no,
        email=email,
        is_verified=True
    )
    await state.clear()

    await message.answer(
        f"🎉 **Registration Successful & Verified!**\n\n"
        f"Welcome aboard, **{full_name}** (`{matric_no}`).\n\n"
        f"You can now book rides across campus using the menu below!",
        reply_markup=kb.get_main_menu_keyboard(is_registered=True),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(F.text == "👤 My Student Profile")
async def show_profile(message: Message):
    if check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Drivers access their profile under '🚗 My Vehicle & Profile'.")
        return

    user_data = storage.get_user(message.from_user.id) or {}
    name = user_data.get("name", message.from_user.first_name)
    matric = user_data.get("matric_no", "Not set")
    email = user_data.get("email", "Not set")
    is_verified = user_data.get("is_verified", False)
    status_str = "✅ Verified CU Student" if is_verified else "⚠️ Unregistered / Unverified"
    active_code = user_data.get("active_promo", "None")
    all_rides = storage.get_user_rides(message.from_user.id)

    profile_text = (
        f"👤 **Student Profile**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📛 **Name:** {name}\n"
        f"🎓 **Matric No:** `{matric}`\n"
        f"📧 **CU Email:** `{email}`\n"
        f"🛡️ **Status:** {status_str}\n"
        f"🏷️ **Active Promo:** `{active_code}`\n"
        f"🚗 **Total Rides Taken:** {len(all_rides)}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await message.answer(profile_text, parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text.in_({"🚖 Book a Ride", "🚖 Book a Shuttle"}))
async def start_booking_flow(message: Message, state: FSMContext):
    if check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Drivers cannot book rides. Roles are mutually exclusive.")
        return

    user_data = storage.get_user(message.from_user.id)
    if not user_data or not user_data.get("is_verified"):
        await message.answer(
            "🔒 **Student Verification Required**\n\n"
            "Please click **📝 Register / Sign Up** on the menu to complete verification.",
            reply_markup=kb.get_main_menu_keyboard(is_registered=False),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await state.clear()
    await state.set_state(BookingFlow.choosing_pickup)
    await message.answer(
        "📍 **Step 1/3: Select Pickup Location**\n\nWhere are you departing from on campus?",
        reply_markup=kb.get_campus_locations_keyboard(action_prefix="pickup_loc"),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.callback_query(F.data.startswith("pickup_loc:") | F.data.startswith("pickup_hall:") | F.data.startswith("pickup_dest:"))
async def on_pickup_point_selected(callback: CallbackQuery, state: FSMContext):
    pickup = callback.data.split(":", 1)[1]
    await state.update_data(pickup=pickup)
    await state.set_state(BookingFlow.choosing_dropoff)
    await callback.message.edit_text(
        f"✅ Pickup: **{pickup}** ({config.get_landmark(pickup)})\n\n"
        f"🎯 **Step 2/3: Select Drop-off Destination**:\nWhere are you heading?",
        reply_markup=kb.get_campus_locations_keyboard(action_prefix="dropoff_loc", exclude=pickup),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("dropoff_loc:") | F.data.startswith("dropoff_dest:") | F.data.startswith("dropoff_hall:"))
async def on_dropoff_point_selected(callback: CallbackQuery, state: FSMContext):
    dropoff = callback.data.split(":", 1)[1]
    data = await state.get_data()
    pickup = data.get("pickup", "")

    if pickup and pickup == dropoff:
        await callback.answer("❌ Pickup and drop-off cannot be the same!", show_alert=True)
        return

    await state.update_data(dropoff=dropoff)
    await state.set_state(BookingFlow.choosing_passengers)
    await callback.message.edit_text(
        f"Route: **{pickup}** ➡️ **{dropoff}**\n\n"
        f"👥 **Step 3/3: Number of Passengers** (1 to 4):\n"
        f"💵 Fare: **₦200** per person",
        reply_markup=kb.get_passengers_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("passengers:"))
async def on_passengers_selected(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":", 1)[1])
    if count < 1 or count > 4:
        count = 1

    await state.update_data(passengers=count)
    data = await state.get_data()
    pickup = data.get("pickup")
    dropoff = data.get("dropoff")

    # Flat fare rule: ₦200 per passenger
    base_fare = 200.0 * count
    final_fare = base_fare

    await state.update_data(
        base_fare=base_fare,
        discount=0.0,
        final_fare=final_fare,
        promo_code=None,
        is_rush=False
    )

    summary_text = (
        f"📝 **Trip Summary & Checkout**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Pickup:** {pickup} ({config.get_landmark(pickup)})\n"
        f"🏁 **Drop-off:** {dropoff} ({config.get_landmark(dropoff)})\n"
        f"👥 **Passengers:** {count} passenger(s)\n"
        f"💵 **Total Fare (₦200/seat):** **₦{final_fare:,.0f}**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Dispatch ride request to available drivers?"
    )
    await state.set_state(BookingFlow.confirming)
    await callback.message.edit_text(summary_text, reply_markup=kb.get_confirm_keyboard(), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@dp.callback_query(F.data == "confirm_dispatch")
async def on_confirm_dispatch(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pickup = data.get("pickup", "Campus")
    dropoff = data.get("dropoff", "Destination")
    passengers = data.get("passengers", 1)
    base_fare = data.get("base_fare", 100)
    discount = data.get("discount", 0)
    final_fare = data.get("final_fare", 100)
    promo_code = data.get("promo_code")
    is_rush = data.get("is_rush", False)

    ride = storage.create_ride(
        user_id=callback.from_user.id,
        pickup=pickup,
        dropoff=dropoff,
        passengers=passengers,
        base_fare=base_fare,
        discount=discount,
        final_fare=final_fare,
        promo_code=promo_code,
        is_rush=is_rush
    )
    await state.clear()

    # Find online, approved drivers matching capacity (FR-23)
    online_drivers = storage.get_online_drivers(passenger_count=passengers)
    dispatched_count = 0

    if online_drivers and bot_instance:
        alert_text = (
            f"🚖 **NEW RIDE DISPATCH ALERT!**\n"
            f"🆔 Ref: `{ride['ride_id']}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 **Pickup:** {pickup} ({ride['pickup_landmark']})\n"
            f"🏁 **Drop-off:** {dropoff} ({ride['dropoff_landmark']})\n"
            f"👥 **Passengers:** {passengers} seat(s)\n"
            f"💵 **Your Payout:** **₦{ride['driver_payout']:,.0f}**\n"
            f"🕒 **Pickup Time:** Immediate\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Tap **Accept** to claim this ride:"
        )
        for driver_uid, _ in online_drivers:
            await send_and_log(
                chat_id=driver_uid,
                text=alert_text,
                event="dispatch_alert",
                reply_markup=kb.get_dispatch_alert_keyboard(ride['ride_id'])
            )
            dispatched_count += 1

    dispatch_info = (
        f"📢 Broadcasted to **{dispatched_count}** online driver(s)."
        if dispatched_count > 0 else
        "⏳ No drivers currently online. Your request is queued for incoming drivers."
    )

    dispatch_card = (
        f"🎉 **Shuttle Dispatch Requested!**\n"
        f"🆔 **Booking Ref:** `{ride['ride_id']}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Pickup:** {pickup} ({ride['pickup_landmark']})\n"
        f"🏁 **Drop-off:** {dropoff} ({ride['dropoff_landmark']})\n"
        f"👥 **Passengers:** {passengers}\n"
        f"💵 **Amount Payable:** ₦{final_fare:,.0f}\n"
        f"🔑 **Completion PIN:** `{ride['completion_otp']}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{dispatch_info}\n\n"
        f"You will be notified immediately when a driver accepts."
    )
    await callback.message.edit_text(
        dispatch_card,
        reply_markup=kb.get_ride_action_keyboard(ride['ride_id']),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer("Booking Dispatched!")

@dp.callback_query(F.data == "cancel_booking")
async def on_cancel_booking(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Shuttle booking request was cancelled.")
    user_data = storage.get_user(callback.from_user.id)
    is_reg = bool(user_data and user_data.get("is_verified"))
    await callback.message.answer(
        "👇 Use the menu below to book another ride or explore options.",
        reply_markup=kb.get_main_menu_keyboard(is_registered=is_reg)
    )
    await callback.answer()

@dp.message(F.text.in_({"📋 Previous / Active Rides", "📋 Active Rides / Status"}))
async def show_active_rides(message: Message):
    if check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Drivers view active rides via '📋 Current Active Trip'.")
        return

    active_rides = storage.get_user_rides(message.from_user.id, active_only=True)
    all_rides = storage.get_user_rides(message.from_user.id, active_only=False)

    if not all_rides:
        user_data = storage.get_user(message.from_user.id)
        is_reg = bool(user_data and user_data.get("is_verified"))
        await message.answer(
            "ℹ️ You do not have any rides on record yet.\n\nUse '🚖 Book a Ride' to request one!",
            reply_markup=kb.get_main_menu_keyboard(is_registered=is_reg)
        )
        return

    # 1. Active Rides
    if active_rides:
        for r in active_rides:
            driver_str = "Searching for driver..."
            if r.get("driver_id"):
                dp = storage.get_driver_profile(r["driver_id"])
                if dp:
                    driver_str = f"{dp.get('full_name')} ({dp.get('car_model')}, `{dp.get('plate_number')}`)"

            card = (
                f"🚖 **ACTIVE RIDE — `{r['ride_id']}`**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📍 **Pickup:** {r['pickup']}\n"
                f"🏁 **Drop-off:** {r['dropoff']}\n"
                f"👥 **Passengers:** {r.get('passengers', 1)}\n"
                f"💵 **Fare (₦200/seat):** ₦{r['final_fare']:,.0f}\n"
                f"🔑 **Completion PIN:** `{r.get('completion_otp')}`\n"
                f"👨‍✈️ **Driver:** {driver_str}\n"
                f"📊 **Status:** 🟢 {r['status'].replace('_', ' ').title()}\n"
                f"🕒 **Time:** {r['created_at']}\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            await message.answer(
                card,
                reply_markup=kb.get_ride_action_keyboard(r['ride_id']),
                parse_mode=ParseMode.MARKDOWN
            )

    # 2. Previous Rides
    completed_or_past = [r for r in all_rides if r.get("status") in ["completed", "cancelled"]]
    if completed_or_past:
        history_text = "📋 **Your Previous Rides:**\n━━━━━━━━━━━━━━━━━━\n"
        for r in completed_or_past[:5]:
            status_badge = "🏁 Completed" if r.get("status") == "completed" else "🚫 Cancelled"
            history_text += (
                f"• `{r['ride_id']}`: {r['pickup']} ➡️ {r['dropoff']} "
                f"({status_badge}, ₦{r.get('final_fare', 0):,.0f}) — _{r['created_at']}_\n"
            )
        await message.answer(history_text, parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data.startswith("cancel_ride:"))
async def on_student_cancel_ride(callback: CallbackQuery):
    ride_id = callback.data.split(":", 1)[1]
    ride = storage.get_ride(ride_id)

    storage.update_ride_progress(ride_id, "cancelled", note="Student cancelled booking")
    await callback.message.edit_text(
        f"🚫 **Booking `{ride_id}` has been cancelled.**",
        parse_mode=ParseMode.MARKDOWN
    )

    if ride and ride.get("driver_id"):
        await send_and_log(
            chat_id=ride["driver_id"],
            text=f"⚠️ **Booking `{ride_id}` was cancelled by the student.** You are now free for new dispatches.",
            event="student_cancelled_ride",
            reply_markup=kb.get_driver_main_menu(is_approved=True, is_online=True)
        )

    user_data = storage.get_user(callback.from_user.id)
    is_reg = bool(user_data and user_data.get("is_verified"))
    await callback.message.answer(
        "Need another ride? Use the menu below.",
        reply_markup=kb.get_main_menu_keyboard(is_registered=is_reg)
    )
    await callback.answer("Ride cancelled.")

@dp.message(F.text == "🏷️ Apply Promo / Discount")
async def apply_promo_prompt(message: Message):
    if check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Drivers cannot apply promo codes.")
        return

    await message.answer(
        "🏷️ **Enter Discount / Promo Code:**\n\n"
        "Send the code you want to apply (e.g. `WELCOME10` or `CU2026`):\n"
        "Usage: `/promo <CODE>`",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("promo"))
async def cmd_apply_promo(message: Message):
    if check_role(message.from_user.id, "driver"):
        await message.answer("⚠️ Promo codes are for students only.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Please provide a promo code.\nExample: `/promo WELCOME10`", parse_mode=ParseMode.MARKDOWN)
        return
    code = parts[1].strip().upper()
    if code in config.DISCOUNT_CODES:
        storage.update_user(message.from_user.id, active_promo=code)
        pinfo = config.DISCOUNT_CODES[code]
        desc = f"{pinfo['value']}% discount" if pinfo["type"] == "percentage" else f"₦{pinfo['value']} discount"
        await message.answer(f"🎉 Promo code **{code}** applied! ({desc} on your next ride).", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer("❌ Invalid or expired promo code. Available codes: `WELCOME10`, `CU2026`.", parse_mode=ParseMode.MARKDOWN)

# ----------------- Support & Help -----------------

@dp.message(Command("help"))
@dp.message(F.text.in_({"📞 Support / Help", "📞 Driver Support"}))
async def show_support(message: Message):
    role = storage.get_user_role(message.from_user.id)
    support_text = (
        f"📞 **dot.rider Campus Dispatch Helpdesk & Safety (FR-67)**\n\n"
        f"• **Campus Emergency Security Hotline:** `{config.SUPPORT_PHONE}`\n"
        f"• **Dispatch Control Desk:** {config.DISPATCH_DESK}\n"
        f"• **Operating Hours:** 7:00 AM – 10:00 PM Daily\n\n"
        f"For lost items, vehicle breakdowns, or route assistance, call the dispatch desk directly."
    )
    if role == "driver":
        await message.answer(
            support_text,
            reply_markup=kb.get_driver_support_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.answer(support_text, parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text == "ℹ️ Campus Locations & Fare")
async def show_campus_info(message: Message):
    info_text = (
        f"📍 **Approved Campus Pickup & Drop-off Points**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏛 **Available Locations:**\n"
        f"• Chapel Shuttle Stand\n"
        f"• Lecture Theatres\n"
        f"• CMSS Building\n"
        f"• CEDS\n"
        f"• CST Building\n"
        f"• CUCRID\n"
        f"• Caf 2\n"
        f"• PET Car Park\n"
        f"• Zenith Bank\n"
        f"• Access Bank\n"
        f"• ICT Centre\n"
        f"• Guest House\n"
        f"• Civil / Mech / EIE\n\n"
        f"💵 **Fare Rate:**\n"
        f"• Flat Rate: **₦200** / passenger\n\n"
        f"You can ride from any of these points to any other point."
    )
    await message.answer(info_text, parse_mode=ParseMode.MARKDOWN)

# ----------------- Health Check & Keep-Alive Server (for Render) -----------------

async def health_handler(request):
    return web.Response(text="OK - Bot is active")

async def keep_alive_ping():
    """Background task that pings the Render service URL every 10 minutes to prevent sleep."""
    await asyncio.sleep(30)  # Wait 30s after startup before first ping
    service_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("SERVICE_URL")
    if not service_url:
        logger.info("Keep-alive: No RENDER_EXTERNAL_URL or SERVICE_URL configured. Self-ping skipped.")
        return

    logger.info(f"Keep-alive task started for: {service_url}")
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                target_url = service_url.rstrip("/") + "/health"
                async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    logger.info(f"Self-ping keep-alive status: {resp.status}")
        except Exception as e:
            logger.warning(f"Self-ping keep-alive failed: {e}")
        # Ping every 10 minutes (Render free tier sleeps after 15 mins of inactivity)
        await asyncio.sleep(600)

async def start_health_server():
    """Lightweight HTTP server so Render Web Service stays alive."""
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server running on port {port}")

    # Launch background keep-alive self-ping loop
    asyncio.create_task(keep_alive_ping())

# ----------------- Main Runner -----------------

async def main():
    global bot_instance
    if not config.BOT_TOKEN:
        print("Error: BOT_TOKEN not configured in .env")
        sys.exit(1)

    bot_instance = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    await bot_instance.set_my_commands([
        BotCommand(command="start", description="🏠 Main Menu / Select Role"),
        BotCommand(command="mock_driver", description="🧪 Instantly switch to Mock Driver (Test Mode)"),
        BotCommand(command="mock_request", description="🧪 Send incoming test ride request to driver"),
        BotCommand(command="reset_role", description="🔄 Reset role (Switch between Student & Driver)"),
        BotCommand(command="help", description="📞 Contact campus dispatch / emergency hotline"),
        BotCommand(command="promo", description="🏷️ Apply promo code (Students)"),
        BotCommand(command="admin_approve", description="🛡️ Approve driver (Admin)"),
        BotCommand(command="manual_dispatch", description="🛡️ Manually dispatch ride (Admin)"),
    ])

    # Start health check server for Render
    await start_health_server()

    print("🚀 Covenant University Shuttle Bot is running (Full Student & Driver POV active)...")
    await dp.start_polling(bot_instance)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
