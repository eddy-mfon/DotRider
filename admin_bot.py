"""
Admin Telegram Bot (@dotrideradmin_bot).
Dedicated control panel for system owners and campus dispatchers:
- View and approve/reject student bank transfer top-ups
- Issue manual refunds or wallet adjustments
- View and resolve stuck rides
- View driver performance and fleet status
- Manage system settings and pricing
"""
import asyncio
import logging
from datetime import datetime

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("admin_bot")

dp = Dispatcher(storage=MemoryStorage())
bot_instance: Bot | None = None

# ----------------- FSM States -----------------

class ManualCreditFlow(StatesGroup):
    entering_user_id = State()
    entering_amount = State()
    entering_note = State()

class ManualRefundFlow(StatesGroup):
    entering_ride_id = State()
    entering_amount = State()

# ----------------- Keyboards -----------------

def main_admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏳ Pending Bank Payments"), KeyboardButton(text="⚠️ Stuck Rides Inspector")],
            [KeyboardButton(text="💳 Credit Student Wallet"), KeyboardButton(text="↩️ Issue Manual Refund")],
            [KeyboardButton(text="🚗 Fleet & Online Drivers"), KeyboardButton(text="📊 System Summary")]
        ],
        resize_keyboard=True
    )

def is_authorized(user_id: int) -> bool:
    if not config.ADMIN_CHAT_ID:
        return True
    return str(user_id) == str(config.ADMIN_CHAT_ID)

# ----------------- Start & Menu -----------------

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if not is_authorized(uid):
        await message.answer("⛔ Access denied. You are not an authorized administrator.")
        return

    await message.answer(
        "👋 <b>Welcome to DotRider Admin Bot</b>\n\n"
        "Here you can manage bank transfer approvals, wallet refunds, driver fleets, and stuck rides.",
        reply_markup=main_admin_menu(),
        parse_mode=ParseMode.HTML
    )

# ----------------- Bank Payments Management -----------------

@dp.message(F.text == "⏳ Pending Bank Payments")
@dp.message(Command("payments", "pending"))
async def show_pending_payments(message: Message):
    if not is_authorized(message.from_user.id):
        return

    payments = db.fetchall("SELECT * FROM payments WHERE status = 'pending_admin' ORDER BY created_at ASC LIMIT 10")
    if not payments:
        await message.answer("✅ No pending bank transfer top-ups at this time.")
        return

    buttons = []
    for p in payments:
        buttons.append([InlineKeyboardButton(text=f"₦{p['amount']:,.0f} - {p['reference'][:18]}", callback_data=f"adm_pay:{p['payment_id']}")])

    await message.answer(
        f"⏳ <b>Pending Bank Top-Up Requests ({len(payments)}):</b>\n\nTap any request to approve or reject:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("adm_pay:"))
async def view_payment_details(call: CallbackQuery):
    pid = call.data[8:]
    p = db.fetchone("SELECT * FROM payments WHERE payment_id = ?", (pid,))
    if not p:
        await call.answer("Payment request not found.")
        return

    u = db.get_user(p["user_id"])
    student_name = u["full_name"] if u else "Unknown Student"
    matric = u["matric_no"] if u else "N/A"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve & Credit", callback_data=f"adm_appr_pay:{pid}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rej_pay:{pid}")
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="adm_back_pay")]
    ])

    await call.message.edit_text(
        f"💳 <b>Payment Verification Details</b>\n\n"
        f"<b>Payment ID:</b> <code>{p['payment_id']}</code>\n"
        f"<b>Student:</b> {student_name} (<code>{matric}</code>)\n"
        f"<b>Student ID:</b> <code>{p['user_id']}</code>\n"
        f"<b>Amount:</b> <b>₦{p['amount']:,.2f}</b>\n"
        f"<b>Reference / Note:</b> <i>{p['reference']}</i>\n"
        f"<b>Submitted:</b> {p['created_at']}\n"
        f"<b>Status:</b> <code>{p['status']}</code>",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await call.answer()

@dp.callback_query(F.data.startswith("adm_appr_pay:"))
async def approve_payment_cb(call: CallbackQuery):
    pid = call.data[13:]
    p = db.fetchone("SELECT * FROM payments WHERE payment_id = ?", (pid,))
    if not p or p["status"] != "pending_admin":
        await call.answer("Payment already processed.")
        return

    db.execute("UPDATE payments SET status = 'approved', reviewed_by = ? WHERE payment_id = ?", (call.from_user.id, pid))
    new_bal = db.credit_wallet(p["user_id"], p["amount"], f"Bank top-up approved ({pid})")

    # Notify student via Student Bot
    await notifier.notify_student(
        p["user_id"],
        f"🎉 <b>Bank Top-Up Approved!</b>\n\n"
        f"Amount: <b>₦{p['amount']:,.2f}</b> has been credited to your wallet.\n"
        f"💳 Available Balance: <b>₦{new_bal:,.2f}</b>"
    )

    await call.message.edit_text(
        f"✅ <b>Approved!</b>\n\n"
        f"Payment <code>{pid}</code> approved.\n"
        f"<b>₦{p['amount']:,.2f}</b> added to student's wallet (New balance: ₦{new_bal:,.2f}).",
        reply_markup=None,
        parse_mode=ParseMode.HTML
    )
    await call.answer()

@dp.callback_query(F.data.startswith("adm_rej_pay:"))
async def reject_payment_cb(call: CallbackQuery):
    pid = call.data[12:]
    p = db.fetchone("SELECT * FROM payments WHERE payment_id = ?", (pid,))
    if not p or p["status"] != "pending_admin":
        await call.answer("Payment already processed.")
        return

    db.execute("UPDATE payments SET status = 'rejected', reviewed_by = ? WHERE payment_id = ?", (call.from_user.id, pid))

    # Notify student
    await notifier.notify_student(
        p["user_id"],
        f"❌ <b>Bank Top-Up Declined</b>\n\n"
        f"Your top-up of ₦{p['amount']:,.2f} (Ref: {p['reference']}) could not be confirmed by admin.\n"
        f"Please check your transaction details or contact support."
    )

    await call.message.edit_text(f"❌ Payment <code>{pid}</code> was marked as rejected.", reply_markup=None)
    await call.answer()

@dp.callback_query(F.data == "adm_back_pay")
async def back_to_pay_list(call: CallbackQuery):
    payments = db.fetchall("SELECT * FROM payments WHERE status = 'pending_admin' ORDER BY created_at ASC LIMIT 10")
    if not payments:
        await call.message.edit_text("✅ No pending bank transfer top-ups at this time.")
        return
    buttons = []
    for p in payments:
        buttons.append([InlineKeyboardButton(text=f"₦{p['amount']:,.0f} - {p['reference'][:18]}", callback_data=f"adm_pay:{p['payment_id']}")])

    await call.message.edit_text(
        f"⏳ <b>Pending Bank Top-Up Requests ({len(payments)}):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )

# ----------------- Stuck Rides Inspector -----------------

@dp.message(F.text == "⚠️ Stuck Rides Inspector")
@dp.message(Command("stuck", "rides"))
async def inspect_stuck_rides(message: Message):
    if not is_authorized(message.from_user.id):
        return

    stuck = db.fetchall("""
        SELECT * FROM rides
        WHERE status IN ('pending_driver', 'driver_offered', 'queue_waiting', 'departed', 'arrived')
        ORDER BY created_at ASC LIMIT 10
    """)

    if not stuck:
        await message.answer("✅ <b>No stuck rides found!</b> All rides are proceeding normally.")
        return

    text = f"⚠️ <b>Active / Potential Stuck Rides ({len(stuck)}):</b>\n\n"
    for r in stuck:
        text += (
            f"• <b>{r['ride_id']}</b> (<code>{r['status']}</code>)\n"
            f"  Route: {r['pickup']} ➡️ {r['dropoff']}\n"
            f"  Student: <code>{r['creator_student_id']}</code> | Fare: ₦{r['total_fare']:,.2f}\n"
            f"  Assigned Driver: <code>{r['assigned_driver_id'] or 'None'}</code>\n"
            f"  Created: {r['created_at']}\n\n"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)

# ----------------- Manual Wallet Credit Flow -----------------

@dp.message(F.text == "💳 Credit Student Wallet")
@dp.message(Command("credit"))
async def start_manual_credit(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        return
    await message.answer(
        "💳 <b>Manual Wallet Adjustment</b>\n\n"
        "Please enter the <b>Telegram User ID</b> of the student to credit (e.g. <code>7918080983</code>):",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(ManualCreditFlow.entering_user_id)

@dp.message(ManualCreditFlow.entering_user_id)
async def process_credit_uid(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("Please enter a valid numeric Telegram ID:")
        return

    user = db.get_user(uid)
    if not user:
        await message.answer("User not found in system. Please verify the ID:")
        return

    await state.update_data(target_uid=uid, user_name=user["full_name"])
    await message.answer(
        f"Student: <b>{user['full_name']}</b> (Current Balance: ₦{user['wallet_balance']:,.2f})\n\n"
        f"Enter the amount to credit (in Naira, e.g. <code>2500</code>):",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(ManualCreditFlow.entering_amount)

@dp.message(ManualCreditFlow.entering_amount)
async def process_credit_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text.strip().replace(",", "").replace("₦", ""))
        if amt <= 0:
            await message.answer("Please enter a positive amount:")
            return
    except ValueError:
        await message.answer("Please enter numbers only:")
        return

    await state.update_data(amount=amt)
    await message.answer("Enter a brief description / reason for this credit (or type 'Admin adjustment'):")
    await state.set_state(ManualCreditFlow.entering_note)

@dp.message(ManualCreditFlow.entering_note)
async def process_credit_note(message: Message, state: FSMContext):
    note = message.text.strip()
    data = await state.get_data()
    uid = data["target_uid"]
    amt = data["amount"]

    new_bal = db.credit_wallet(uid, amt, f"Admin credit: {note}")
    await state.clear()

    # Notify student
    await notifier.notify_student(
        uid,
        f"💳 <b>Wallet Credit Notification</b>\n\n"
        f"An admin credit of <b>₦{amt:,.2f}</b> has been applied to your wallet.\n"
        f"Reason: {note}\n"
        f"Available Balance: <b>₦{new_bal:,.2f}</b>"
    )

    await message.answer(
        f"✅ <b>Successfully Credited!</b>\n\n"
        f"Student: <b>{data['user_name']}</b> (<code>{uid}</code>)\n"
        f"Amount: <b>₦{amt:,.2f}</b>\n"
        f"New Balance: <b>₦{new_bal:,.2f}</b>",
        reply_markup=main_admin_menu(),
        parse_mode=ParseMode.HTML
    )

# ----------------- Manual Refund Flow -----------------

@dp.message(F.text == "↩️ Issue Manual Refund")
@dp.message(Command("refund"))
async def start_manual_refund(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        return
    await message.answer(
        "↩️ <b>Manual Ride Refund</b>\n\n"
        "Enter the <b>Ride ID</b> to refund (e.g. <code>RIDE-XXXXXXXX</code>):",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(ManualRefundFlow.entering_ride_id)

@dp.message(ManualRefundFlow.entering_ride_id)
async def process_refund_ride_id(message: Message, state: FSMContext):
    ride_id = message.text.strip()
    ride = db.get_ride(ride_id)
    if not ride:
        await message.answer("Ride not found. Please check the Ride ID:")
        return

    await state.update_data(ride_id=ride_id, student_id=ride["creator_student_id"], default_fare=ride["total_fare"])
    await message.answer(
        f"Ride: <code>{ride_id}</code>\n"
        f"Student ID: <code>{ride['creator_student_id']}</code>\n"
        f"Route: {ride['pickup']} ➡️ {ride['dropoff']}\n"
        f"Total Fare: <b>₦{ride['total_fare']:,.2f}</b>\n\n"
        f"Enter the refund amount (or enter <code>{ride['total_fare']}</code> for full refund):",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(ManualRefundFlow.entering_amount)

@dp.message(ManualRefundFlow.entering_amount)
async def process_refund_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text.strip().replace(",", "").replace("₦", ""))
    except ValueError:
        await message.answer("Please enter numbers only:")
        return

    data = await state.get_data()
    ride_id = data["ride_id"]
    uid = data["student_id"]

    db.execute("""
        UPDATE rides
        SET status = 'cancelled',
            cancelled_at = CURRENT_TIMESTAMP,
            cancellation_reason = 'Admin manual refund'
        WHERE ride_id = ?
    """, (ride_id,))

    new_bal = db.credit_wallet(uid, amt, f"Admin manual refund for ride {ride_id}")
    await state.clear()

    await notifier.notify_student(
        uid,
        f"↩️ <b>Admin Refund Issued</b>\n\n"
        f"A refund of <b>₦{amt:,.2f}</b> has been credited to your wallet for ride <code>{ride_id}</code>.\n"
        f"💳 Available Balance: <b>₦{new_bal:,.2f}</b>"
    )

    await message.answer(
        f"✅ <b>Refund Processed!</b>\n\n"
        f"Ride <code>{ride_id}</code> cancelled and <b>₦{amt:,.2f}</b> credited to student <code>{uid}</code>.\n"
        f"New Balance: <b>₦{new_bal:,.2f}</b>",
        reply_markup=main_admin_menu(),
        parse_mode=ParseMode.HTML
    )

# ----------------- Fleet & System Summary -----------------

@dp.message(F.text == "🚗 Fleet & Online Drivers")
@dp.message(Command("fleet", "drivers"))
async def fleet_status(message: Message):
    if not is_authorized(message.from_user.id):
        return

    drivers = db.fetchall("SELECT * FROM drivers ORDER BY is_online DESC, rating_avg DESC")
    if not drivers:
        await message.answer("No drivers registered in the system yet.")
        return

    text = f"🚗 <b>Campus Fleet Status ({len(drivers)} drivers):</b>\n\n"
    for d in drivers:
        status_tag = "🟢 Online" if d["is_online"] else "🔴 Offline"
        busy_tag = f" (On trip <code>{d['current_ride_id']}</code>)" if d["current_ride_id"] else " (Available)" if d["is_online"] else ""
        text += (
            f"• <b>{d['full_name']}</b> - {status_tag}{busy_tag}\n"
            f"  Car: {d['car_model']} (<code>{d['plate_number']}</code>)\n"
            f"  Rating: ⭐ {d['rating_avg']:.1f} ({d['rating_count']} reviews) | Phone: {d['phone']}\n\n"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "📊 System Summary")
@dp.message(Command("summary", "stats"))
async def system_summary(message: Message):
    if not is_authorized(message.from_user.id):
        return

    users_count = db.fetchone("SELECT COUNT(*) as c FROM users")["c"]
    drivers_count = db.fetchone("SELECT COUNT(*) as c FROM drivers")["c"]
    online_count = db.fetchone("SELECT COUNT(*) as c FROM drivers WHERE is_online = 1")["c"]
    completed_rides = db.fetchone("SELECT COUNT(*) as c FROM rides WHERE status = 'completed'")["c"]
    pending_payments = db.fetchone("SELECT COUNT(*) as c FROM payments WHERE status = 'pending_admin'")["c"]

    await message.answer(
        f"📊 <b>System Performance Summary</b>\n\n"
        f"👥 Total Students: <b>{users_count}</b>\n"
        f"🚗 Total Drivers: <b>{drivers_count}</b> (🟢 {online_count} currently online)\n"
        f"🏁 Completed Rides: <b>{completed_rides}</b>\n"
        f"⏳ Pending Top-Ups: <b>{pending_payments}</b>",
        parse_mode=ParseMode.HTML
    )

async def main():
    db.init_schema()
    token = config.ADMIN_BOT_TOKEN
    if not token:
        logger.error("ADMIN_BOT_TOKEN is not configured.")
        return

    global bot_instance
    bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    logger.info("Admin Bot starting polling...")
    await dp.start_polling(bot_instance)

if __name__ == "__main__":
    asyncio.run(main())
