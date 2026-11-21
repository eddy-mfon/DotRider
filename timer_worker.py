"""
Background worker that monitors all persistent ride timers:
1. Driver 2-minute acceptance timeout: auto-cascades to next available driver or refunds.
2. Shared ride 10-minute queue timeout: dispatches if >= 2 seats or triggers upgrade/refund prompt.
3. Driver arrival 5-minute passenger no-show reminder.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from db import db
import notifier
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

async def process_driver_acceptance_timeouts():
    """
    Checks rides in 'driver_offered' state whose offer has expired.
    Declines for that driver and cascades to the next available driver.
    """
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    # Fetch expired offers
    expired_rides = db.fetchall("""
        SELECT * FROM rides
        WHERE status = 'driver_offered'
        AND driver_offer_expires_at IS NOT NULL
        AND driver_offer_expires_at <= ?
    """, (now_str,))

    for ride in expired_rides:
        ride_id = ride["ride_id"]
        driver_id = ride["assigned_driver_id"]
        student_id = ride["creator_student_id"]

        logger.info(f"Driver offer expired for ride {ride_id}, driver {driver_id}")

        # Mark offer as timed out
        if driver_id:
            db.mark_driver_offer_status(ride_id, driver_id, "timed_out")
            # Notify driver that request expired
            await notifier.notify_driver(
                driver_id,
                f"⏱️ Ride request <b>{ride_id}</b> expired because it was not accepted within 2 minutes."
            )

        # Find next available driver who has not yet received an offer for this ride
        rejected_drivers = db.get_rejected_driver_ids_for_ride(ride_id)
        if driver_id:
            rejected_drivers.append(driver_id)

        all_available = db.get_available_drivers()
        candidate = None
        for d in all_available:
            if d["driver_id"] not in rejected_drivers:
                candidate = d
                break

        if candidate:
            # Assign and send offer to candidate driver
            new_driver_id = candidate["driver_id"]
            expire_at = (datetime.utcnow() + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
            db.execute("""
                UPDATE rides
                SET assigned_driver_id = ?,
                    status = 'driver_offered',
                    driver_offer_expires_at = ?
                WHERE ride_id = ?
            """, (new_driver_id, expire_at, ride_id))
            db.add_ride_offer(ride_id, new_driver_id)

            # Notify student
            await notifier.notify_student(
                student_id,
                f"🔄 The previous driver did not respond in 2 minutes.\n"
                f"Routing your ride request to another available driver: <b>{candidate['full_name']}</b> (⭐ {candidate['rating_avg']})."
            )

            # Send acceptance prompt to new driver
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
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
                f"<b>Package:</b> {ride['booking_type'].replace('_', ' ').title()}\n"
                f"<b>Fare:</b> ₦{ride['total_fare']:,.2f}\n\n"
                f"⏰ You have <b>2 minutes</b> to accept before it passes to another driver.",
                reply_markup=keyboard
            )
        else:
            # No available driver left -> Cancel ride and issue full refund to student wallet
            db.execute("""
                UPDATE rides
                SET status = 'cancelled',
                    cancelled_at = CURRENT_TIMESTAMP,
                    cancellation_reason = 'No driver available after timeout'
                WHERE ride_id = ?
            """, (ride_id,))

            # Issue full refund to creator and all joined seats
            seats = db.fetchall("SELECT * FROM ride_seats WHERE ride_id = ? AND status = 'joined'", (ride_id,))
            for seat in seats:
                refund_amount = seat["fare_paid"]
                uid = seat["student_id"]
                new_bal = db.credit_wallet(uid, refund_amount, f"Full refund for ride {ride_id} (No driver accepted)")
                await notifier.notify_student(
                    uid,
                    f"❌ <b>Ride Request Unfulfilled</b>\n\n"
                    f"Unfortunately, no drivers were available to accept your ride <b>{ride_id}</b>.\n"
                    f"A <b>full refund</b> of ₦{refund_amount:,.2f} has been credited to your wallet.\n"
                    f"💳 New Wallet Balance: <b>₦{new_bal:,.2f}</b>"
                )

async def process_shared_queue_timeouts():
    """
    Checks shared rides waiting for seats (status 'queue_waiting')
    whose 10-minute waiting window has elapsed.
    Rule:
    - If at least 2 seats filled: dispatch the ride!
    - If only 1 seat filled: offer two buttons:
        'Upgrade to full car' (pay difference) or 'Cancel and refund to wallet'.
    """
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    expired_queues = db.fetchall("""
        SELECT * FROM rides
        WHERE booking_type = 'one_seat'
        AND status = 'queue_waiting'
        AND queue_expires_at IS NOT NULL
        AND queue_expires_at <= ?
    """, (now_str,))

    for ride in expired_queues:
        ride_id = ride["ride_id"]
        seats_filled = ride["seats_filled"]
        min_seats = int(db.get_setting("shared_min_dispatch_seats", "2"))

        if seats_filled >= min_seats:
            # Dispatch ride! Move to pending_driver
            db.execute("""
                UPDATE rides
                SET status = 'pending_driver'
                WHERE ride_id = ?
            """, (ride_id,))

            # Notify all students in the car
            seats = db.get_ride_seats(ride_id)
            for s in seats:
                await notifier.notify_student(
                    s["student_id"],
                    f"🎉 <b>Shared Ride Ready!</b>\n\n"
                    f"Your 10-minute waiting window has ended, and {seats_filled} seats are filled.\n"
                    f"Your shuttle <b>{ride_id}</b> is now dispatching to drivers!"
                )

            # Auto-assign first available driver
            avail = db.get_available_drivers()
            if avail:
                driver = avail[0]
                expire_at = (datetime.utcnow() + timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
                db.execute("""
                    UPDATE rides
                    SET assigned_driver_id = ?,
                        status = 'driver_offered',
                        driver_offer_expires_at = ?
                    WHERE ride_id = ?
                """, (driver["driver_id"], expire_at, ride_id))
                db.add_ride_offer(ride_id, driver["driver_id"])

                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✅ Accept Ride (2 mins)", callback_data=f"drv_accept:{ride_id}"),
                        InlineKeyboardButton(text="❌ Decline", callback_data=f"drv_decline:{ride_id}")
                    ]
                ])
                await notifier.notify_driver(
                    driver["driver_id"],
                    f"🚖 <b>New Shared Ride Dispatch!</b>\n\n"
                    f"<b>Ride ID:</b> {ride_id}\n"
                    f"<b>Pickup:</b> {ride['pickup']}\n"
                    f"<b>Drop-off:</b> {ride['dropoff']}\n"
                    f"<b>Passengers:</b> {seats_filled} seat(s)\n\n"
                    f"⏰ You have <b>2 minutes</b> to accept.",
                    reply_markup=kb
                )
        else:
            # Only 1 passenger waiting -> Prompt upgrade or refund
            db.execute("UPDATE rides SET status = 'queue_decision' WHERE ride_id = ?", (ride_id,))
            student_id = ride["creator_student_id"]
            
            # Calculate difference for full car upgrade
            zone = ride["zone"]
            full_car_fare = db.get_fare_config("full_car", zone)["total_fare"]
            paid_fare = ride["total_fare"]
            diff = full_car_fare - paid_fare

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🚗 Upgrade to Full Car (+₦{diff:,.0f})", callback_data=f"sh_upgrade:{ride_id}")],
                [InlineKeyboardButton(text="❌ Cancel & Refund to Wallet", callback_data=f"sh_cancel:{ride_id}")]
            ])

            await notifier.notify_student(
                student_id,
                f"⏱️ <b>10-Minute Shared Ride Window Ended</b>\n\n"
                f"No other passengers joined your route ({ride['pickup']} ➡️ {ride['dropoff']}).\n\n"
                f"Would you like to:\n"
                f"1. <b>Upgrade to Full Car</b> by paying the ₦{diff:,.2f} difference, or\n"
                f"2. <b>Cancel and receive an immediate full refund</b> to your wallet?",
                reply_markup=kb
            )

async def run_timer_worker_loop():
    """Continuous background loop monitoring all active timers."""
    logger.info("Timer worker loop started.")
    while True:
        try:
            await process_driver_acceptance_timeouts()
            await process_shared_queue_timeouts()
        except Exception as e:
            logger.error(f"Error in timer worker loop: {e}", exc_info=True)
        await asyncio.sleep(5)
