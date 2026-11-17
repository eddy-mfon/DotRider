"""
Covenant University Shuttle Bot Implementation
Complies with SRS requirements:
- FR-01 to FR-03: Verification and registration (Matric & University Email)
- FR-06: Duplicate account prevention
- FR-14 & FR-16: Approved locations including CEDS (Engineering front disabled)
- FR-17: Route validation (prevent same pickup & drop-off)
- FR-20: 1 to 4 passenger enforcement
- FR-21: Rush-hour pricing (7:50 - 10:30 AM)
- FR-22: Trip summary & checkout (clean branding)
- FR-37 to FR-40: Promo code application
"""
import asyncio
import logging
import sys

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

# FSM States
class RegistrationFlow(StatesGroup):
    entering_name = State()
    entering_matric = State()
    entering_email = State()

class BookingFlow(StatesGroup):
    choosing_hall = State()
    choosing_destination = State()
    choosing_passengers = State()
    confirming = State()

dp = Dispatcher(storage=MemoryStorage())

# ----------------- Start & Welcome -----------------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    user_name = user.first_name if user else "Student"

    user_data = storage.get_user(user.id)
    is_registered = bool(user_data and user_data.get("is_verified"))

    if not user_data:
        storage.update_user(user.id, name=user_name, username=user.username, is_verified=False)

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
            f"🎓 *Covenant University Campus Shuttle Dispatch*\n\n"
            f"Order rides between your Hall of Residence and Lecture halls, "
            f"CUCRID, Caf 2, CMSS, CEDS, CST, PET, Banks, and Engineering departments.\n\n"
            f"Choose an option below to get started:"
        )

    await message.answer(
        welcome_text,
        reply_markup=kb.get_main_menu_keyboard(is_registered=is_registered),
        parse_mode=ParseMode.MARKDOWN
    )

# ----------------- Student Registration & Authentication (FR-01 to FR-06) -----------------

@dp.message(F.text == "📝 Register / Sign Up")
async def start_registration(message: Message, state: FSMContext):
    user_data = storage.get_user(message.from_user.id)
    if user_data and user_data.get("is_verified"):
        await message.answer(
            "✅ You are already a verified Covenant University student!\n"
            "You can book rides directly from the menu.",
            reply_markup=kb.get_main_menu_keyboard(is_registered=True)
        )
        return

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
        await message.answer("⚠️ Invalid matriculation number format. Please check and re-enter (e.g., `21CJ028123`):")
        return

    # FR-06: Duplicate account prevention
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
    # FR-02: University-only access verification
    if not (email.endswith("@stu.cu.edu.ng") or email.endswith("@covenantuniversity.edu.ng")):
        await message.answer(
            "⚠️ Ineligible email domain!\n"
            "Student registration strictly requires an official university email ending in `@stu.cu.edu.ng` or `@covenantuniversity.edu.ng`.\n\n"
            "Please enter your valid university email:",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # FR-06: Duplicate email prevention
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
        name=full_name,
        matric_no=matric_no,
        email=email,
        is_verified=True
    )
    await state.clear()

    await message.answer(
        f"🎉 **Registration Successful & Verified!**\n\n"
        f"Welcome aboard, **{full_name}** (`{matric_no}`).\n"
        f"Your student credentials have been validated.\n\n"
        f"You can now book rides across campus using the menu below!",
        reply_markup=kb.get_main_menu_keyboard(is_registered=True),
        parse_mode=ParseMode.MARKDOWN
    )

# ----------------- Student Profile & Info -----------------

@dp.message(F.text == "👤 My Student Profile")
async def show_profile(message: Message):
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
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    if not is_verified:
        profile_text += "\n👉 Click **📝 Register / Sign Up** to verify your account."
    else:
        profile_text += "\nTo update your matric: `/setmatric 21CJ028123`\nTo update your email: `/setemail name@stu.cu.edu.ng`"

    await message.answer(profile_text, parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("setmatric"))
async def cmd_set_matric(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Please provide your matric number.\nExample: `/setmatric 21CJ028123`", parse_mode=ParseMode.MARKDOWN)
        return
    matric = parts[1].strip().upper()
    existing = storage.find_user_by_matric(matric, exclude_uid=message.from_user.id)
    if existing:
        await message.answer(f"❌ Matric `{matric}` is already in use by another student.", parse_mode=ParseMode.MARKDOWN)
        return
    storage.update_user(message.from_user.id, matric_no=matric, is_verified=True)
    await message.answer(f"✅ Matriculation number updated: **{matric}**!", parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("setemail"))
async def cmd_set_email(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Please provide your university email.\nExample: `/setemail david.o@stu.cu.edu.ng`", parse_mode=ParseMode.MARKDOWN)
        return
    email = parts[1].strip().lower()
    if not (email.endswith("@stu.cu.edu.ng") or email.endswith("@covenantuniversity.edu.ng")):
        await message.answer("⚠️ Ineligible domain! Must be an official Covenant University email (`@stu.cu.edu.ng` or `@covenantuniversity.edu.ng`).", parse_mode=ParseMode.MARKDOWN)
        return
    existing = storage.find_user_by_email(email, exclude_uid=message.from_user.id)
    if existing:
        await message.answer(f"❌ Email `{email}` is already registered.", parse_mode=ParseMode.MARKDOWN)
        return
    storage.update_user(message.from_user.id, email=email, is_verified=True)
    await message.answer(f"✅ University email updated and verified: **{email}**!", parse_mode=ParseMode.MARKDOWN)

# ----------------- Booking: Verification Guard & Outward -----------------

@dp.message(F.text == "🚖 Book a Shuttle")
async def start_booking_outward(message: Message, state: FSMContext):
    # FR-02: Require student verification before booking
    user_data = storage.get_user(message.from_user.id)
    if not user_data or not user_data.get("is_verified"):
        await message.answer(
            "🔒 **Student Verification Required**\n\n"
            "Only verified Covenant University students may book shuttle rides.\n"
            "Please click **📝 Register / Sign Up** on the menu to complete your one-time verification.",
            reply_markup=kb.get_main_menu_keyboard(is_registered=False),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await state.clear()
    await state.update_data(direction="hall_to_dest")
    await state.set_state(BookingFlow.choosing_hall)

    text = (
        "📍 **Step 1/3: Select Pickup Hall**\n\n"
        "Where should the shuttle pick you up?"
    )
    await message.answer(text, reply_markup=kb.get_halls_keyboard(action_prefix="pickup_hall"), parse_mode=ParseMode.MARKDOWN)

# ----------------- Booking: Return Trip -----------------

@dp.message(F.text == "🔄 Return Trip (Back to Hall)")
async def start_booking_return(message: Message, state: FSMContext):
    user_data = storage.get_user(message.from_user.id)
    if not user_data or not user_data.get("is_verified"):
        await message.answer(
            "🔒 **Student Verification Required**\n\n"
            "Only verified Covenant University students may book shuttle rides.\n"
            "Please click **📝 Register / Sign Up** on the menu to complete your one-time verification.",
            reply_markup=kb.get_main_menu_keyboard(is_registered=False),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await state.clear()
    await state.update_data(direction="dest_to_hall")
    await state.set_state(BookingFlow.choosing_destination)

    text = (
        "📍 **Step 1/3: Return Trip - Campus Pickup**\n\n"
        "Where are you waiting on campus?"
    )
    await message.answer(text, reply_markup=kb.get_destinations_keyboard(action_prefix="pickup_dest"), parse_mode=ParseMode.MARKDOWN)

# ----------------- Inline Button Handlers -----------------

@dp.callback_query(F.data.startswith("pickup_hall:"))
async def on_pickup_hall_selected(callback: CallbackQuery, state: FSMContext):
    hall = callback.data.split(":", 1)[1]
    await state.update_data(pickup=hall)
    await state.set_state(BookingFlow.choosing_destination)

    text = (
        f"✅ Pickup: **{hall}**\n\n"
        f"🎯 **Step 2/3: Select Drop-off Destination**\n"
        f"Choose your academic or campus destination:"
    )
    await callback.message.edit_text(text, reply_markup=kb.get_destinations_keyboard(action_prefix="dropoff_dest"), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@dp.callback_query(F.data.startswith("pickup_dest:"))
async def on_pickup_dest_selected(callback: CallbackQuery, state: FSMContext):
    dest = callback.data.split(":", 1)[1]
    await state.update_data(pickup=dest)
    await state.set_state(BookingFlow.choosing_hall)

    text = (
        f"✅ Pickup: **{dest}**\n\n"
        f"🏠 **Step 2/3: Select Return Hall**\n"
        f"Which hall of residence are you heading back to?"
    )
    await callback.message.edit_text(text, reply_markup=kb.get_halls_keyboard(action_prefix="dropoff_hall"), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@dp.callback_query(F.data.startswith("dropoff_dest:") | F.data.startswith("dropoff_hall:"))
async def on_dropoff_selected(callback: CallbackQuery, state: FSMContext):
    dropoff = callback.data.split(":", 1)[1]
    data = await state.get_data()
    pickup = data.get("pickup", "")

    # FR-17: Invalid route prevention (identical pickup and drop-off)
    if pickup and pickup == dropoff:
        await callback.answer("❌ Pickup and drop-off cannot be the same!", show_alert=True)
        return

    await state.update_data(dropoff=dropoff)
    await state.set_state(BookingFlow.choosing_passengers)

    text = (
        f"Route: **{pickup}** ➡️ **{dropoff}**\n\n"
        f"👥 **Step 3/3: Number of Passengers** (1 to 4 max):\n"
        f"How many seats are you booking?"
    )
    await callback.message.edit_text(text, reply_markup=kb.get_passengers_keyboard(), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@dp.callback_query(F.data.startswith("passengers:"))
async def on_passengers_selected(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":", 1)[1])
    # FR-20: 1 to 4 passengers check
    if count < 1 or count > 4:
        count = 1

    await state.update_data(passengers=count)
    data = await state.get_data()
    pickup = data.get("pickup")
    dropoff = data.get("dropoff")

    # Pricing & Rush Hour Calculation (FR-21)
    is_rush = config.is_rush_hour()
    rate = config.RUSH_FARE if is_rush else config.BASE_FARE
    base_fare = rate * count

    # Active promo check (FR-37 to FR-40)
    user_data = storage.get_user(callback.from_user.id) or {}
    active_promo = user_data.get("active_promo")
    discount = 0.0

    if active_promo and active_promo in config.DISCOUNT_CODES:
        pinfo = config.DISCOUNT_CODES[active_promo]
        if pinfo["type"] == "percentage":
            discount = base_fare * (pinfo["value"] / 100.0)
        else:
            discount = min(base_fare, float(pinfo["value"]))

    final_fare = max(0.0, base_fare - discount)

    await state.update_data(
        base_fare=base_fare,
        discount=discount,
        final_fare=final_fare,
        promo_code=active_promo,
        is_rush=is_rush
    )

    rush_badge = "⚡ **RUSH HOUR RATE ACTIVE** (7:50 - 10:30 AM)\n" if is_rush else ""
    discount_line = f"🏷️ **Discount ({active_promo}):** -₦{discount:,.0f}\n" if discount > 0 else ""

    # Clean Trip Summary and Checkout
    summary_text = (
        f"📝 **Trip Summary & Checkout**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{rush_badge}"
        f"📍 **From:** {pickup}\n"
        f"🏁 **To:** {dropoff}\n"
        f"👥 **Passengers:** {count}\n"
        f"💵 **Base Fare:** ₦{base_fare:,.0f}\n"
        f"{discount_line}"
        f"💳 **Total Payable:** **₦{final_fare:,.0f}**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Dispatch shuttle request now?"
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

    dispatch_card = (
        f"🎉 **Shuttle Dispatch Requested!**\n"
        f"🆔 **Booking Ref:** `{ride['ride_id']}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Pickup:** {pickup}\n"
        f"🏁 **Dropoff:** {dropoff}\n"
        f"👥 **Passengers:** {passengers}\n"
        f"💵 **Amount Payable:** ₦{final_fare:,.0f}\n"
        f"⏳ **Est. Shuttle Arrival:** 3 - 7 mins\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"You can monitor live status under '📋 Active Rides / Status'."
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

# ----------------- Promo / Discount Application (FR-37 to FR-40) -----------------

@dp.message(F.text == "🏷️ Apply Promo / Discount")
async def apply_promo_prompt(message: Message):
    await message.answer(
        "🏷️ **Enter Discount / Promo Code:**\n\n"
        "Send the code you want to apply (e.g. `WELCOME10` or `CU2026`):\n"
        "Usage: `/promo <CODE>`",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("promo"))
async def cmd_apply_promo(message: Message):
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

# ----------------- Active Rides & Status Tracking -----------------

@dp.message(F.text == "📋 Active Rides / Status")
async def show_active_rides(message: Message):
    rides = storage.get_user_rides(message.from_user.id, active_only=True)
    if not rides:
        user_data = storage.get_user(message.from_user.id)
        is_reg = bool(user_data and user_data.get("is_verified"))
        await message.answer(
            "ℹ️ You do not have any active shuttle bookings right now.\n\n"
            "Use '🚖 Book a Shuttle' or '🔄 Return Trip' to request one!",
            reply_markup=kb.get_main_menu_keyboard(is_registered=is_reg)
        )
        return

    for r in rides:
        status_label = "🟡 Dispatched / Pending" if r['status'] == "pending_assignment" else f"🟢 {r['status'].replace('_', ' ').title()}"
        card = (
            f"🚖 **Booking {r['ride_id']}**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 **Pickup:** {r['pickup']}\n"
            f"🏁 **Dropoff:** {r['dropoff']}\n"
            f"👥 **Passengers:** {r.get('passengers', 1)}\n"
            f"💵 **Fare:** ₦{r['final_fare']:,.0f}\n"
            f"📊 **Status:** {status_label}\n"
            f"🕒 **Time:** {r['created_at']}\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        await message.answer(
            card,
            reply_markup=kb.get_ride_action_keyboard(r['ride_id']),
            parse_mode=ParseMode.MARKDOWN
        )

@dp.callback_query(F.data.startswith("cancel_ride:"))
async def on_cancel_ride(callback: CallbackQuery):
    ride_id = callback.data.split(":", 1)[1]
    storage.update_ride_status(ride_id, "cancelled")
    await callback.message.edit_text(
        f"🚫 **Booking {ride_id} has been cancelled.**",
        parse_mode=ParseMode.MARKDOWN
    )
    user_data = storage.get_user(callback.from_user.id)
    is_reg = bool(user_data and user_data.get("is_verified"))
    await callback.message.answer(
        "Need another ride? Use the menu below.",
        reply_markup=kb.get_main_menu_keyboard(is_registered=is_reg)
    )
    await callback.answer("Ride cancelled.")

@dp.callback_query(F.data.startswith("complete_ride:"))
async def on_complete_ride(callback: CallbackQuery):
    ride_id = callback.data.split(":", 1)[1]
    storage.update_ride_status(ride_id, "completed")
    await callback.message.edit_text(
        f"🏁 **Booking {ride_id} marked as completed!**\n\nThank you for riding with us!",
        parse_mode=ParseMode.MARKDOWN
    )
    user_data = storage.get_user(callback.from_user.id)
    is_reg = bool(user_data and user_data.get("is_verified"))
    await callback.message.answer(
        "🎉 Ride complete! What would you like to do next?",
        reply_markup=kb.get_main_menu_keyboard(is_registered=is_reg)
    )
    await callback.answer("Ride completed!")


# ----------------- Campus Locations & Info -----------------

@dp.message(F.text == "ℹ️ Campus Locations & Fare")
async def show_campus_info(message: Message):
    is_rush = config.is_rush_hour()
    rush_status = "⚡ **Active Now (₦150/seat)**" if is_rush else "⚪ Inactive (Normal rate ₦100/seat)"

    info_text = (
        f"📍 **Approved Campus Routes & Fare Rules**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏢 **Student Halls:**\n"
        f"Peter, Paul, John, Joseph, Daniel, Joshua, Mary, Lydia, Dorcas, Deborah\n\n"
        f"🏛 **Approved Campus Destinations (FR-14):**\n"
        f"• LT1 / LT2 Lecture Theatres\n"
        f"• CMSS & CEDS Buildings\n"
        f"• CST & CUCRID Centers\n"
        f"• Cafeteria 2 (Caf 2)\n"
        f"• PET Car Park, Zenith Bank & Access Bank\n"
        f"• ICT Centre & Guest House\n\n"
        f"💵 **Fare Rates (FR-21):**\n"
        f"• Standard Rate: **₦100** / seat\n"
        f"• Rush Hour (7:50 - 10:30 AM): **₦150** / seat\n"
        f"• Current Status: {rush_status}\n\n"
        f"⚠️ Note: Areas directly in front of Engineering buildings remain disabled as pickup/dropoff per university pilot guidelines."
    )
    await message.answer(info_text, parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text == "📞 Support / Help")
async def show_support(message: Message):
    support_text = (
        f"📞 **Student Shuttle Helpdesk**\n\n"
        f"• For ride delays, safety concerns, or lost items, contact Campus Shuttle Dispatch.\n"
        f"• Emergency Campus Security Line: 0800-CAMPUS-SAFE\n\n"
        f"Safe travels!"
    )
    await message.answer(support_text, parse_mode=ParseMode.MARKDOWN)

# ----------------- Main Runner -----------------

async def main():
    if not config.BOT_TOKEN:
        print("Error: BOT_TOKEN not configured in .env")
        sys.exit(1)

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # Register slash commands so they appear when users type "/" in Telegram
    await bot.set_my_commands([
        BotCommand(command="start",    description="🏠 Open main menu / restart the bot"),
        BotCommand(command="promo",    description="🏷️ Apply a promo/discount code"),
        BotCommand(command="setmatric",description="🎓 Update your matriculation number"),
        BotCommand(command="setemail", description="📧 Update your university email"),
    ])

    print("🚀 Covenant University Shuttle Bot is running and polling updates...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
