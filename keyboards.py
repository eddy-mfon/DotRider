"""
Keyboards and menus for the Covenant University Shuttle Bot.
Complies with UI grid layouts, SRS requirements, and strict Student vs Driver role separation.
"""
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from config import CAMPUS_LOCATIONS

# ----------------- Role Selection Gateway -----------------

def get_role_selection_keyboard() -> InlineKeyboardMarkup:
    """Initial role selection keyboard with mock driver quick-test option."""
    buttons = [
        [
            InlineKeyboardButton(text="🎓 I am a Student", callback_data="select_role:student"),
            InlineKeyboardButton(text="🚗 I am a Driver", callback_data="select_role:driver")
        ],
        [
            InlineKeyboardButton(text="🧪 Quick Mock Driver (1-Click Test)", callback_data="select_role:mock_driver")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_privacy_notice_keyboard() -> InlineKeyboardMarkup:
    """NFR-24: Driver Privacy Notice acceptance"""
    buttons = [
        [
            InlineKeyboardButton(text="✅ I Agree & Accept Terms", callback_data="driver_privacy_accept"),
            InlineKeyboardButton(text="❌ Decline & Exit", callback_data="driver_privacy_decline")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ----------------- Student Keyboards -----------------

def get_main_menu_keyboard(is_registered: bool = False) -> ReplyKeyboardMarkup:
    """Simplified student menu: only 'Book a Ride' and 'Previous / Active Rides'"""
    if not is_registered:
        keyboard = [
            [KeyboardButton(text="📝 Register / Sign Up")]
        ]
    else:
        keyboard = [
            [KeyboardButton(text="🚖 Book a Ride")],
            [KeyboardButton(text="📋 Previous / Active Rides")]
        ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True)

def get_campus_locations_keyboard(action_prefix: str = "loc", exclude: str = None) -> InlineKeyboardMarkup:
    """Displays the 6 approved campus points in clean 2-column inline buttons."""
    buttons = []
    row = []
    for loc in CAMPUS_LOCATIONS:
        if exclude and loc == exclude:
            continue
        row.append(InlineKeyboardButton(text=f"📍 {loc}", callback_data=f"{action_prefix}:{loc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_booking")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_halls_keyboard(action_prefix: str = "pickup") -> InlineKeyboardMarkup:
    return get_campus_locations_keyboard(action_prefix=action_prefix)

def get_destinations_keyboard(action_prefix: str = "dropoff", exclude: str = None) -> InlineKeyboardMarkup:
    return get_campus_locations_keyboard(action_prefix=action_prefix, exclude=exclude)

def get_passengers_keyboard() -> InlineKeyboardMarkup:
    """FR-20: Supports 1 to 4 passengers"""
    buttons = [
        [
            InlineKeyboardButton(text="1 Passenger 🧍", callback_data="passengers:1"),
            InlineKeyboardButton(text="2 Passengers 👥", callback_data="passengers:2"),
        ],
        [
            InlineKeyboardButton(text="3 Passengers 👥👤", callback_data="passengers:3"),
            InlineKeyboardButton(text="4 Passengers 👥👥", callback_data="passengers:4"),
        ],
        [
            InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_booking")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="✅ Confirm & Dispatch Ride", callback_data="confirm_dispatch"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_booking")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_ride_action_keyboard(ride_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🚫 Cancel Ride", callback_data=f"cancel_ride:{ride_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ----------------- Driver Keyboards -----------------

def get_driver_main_menu(is_approved: bool, is_online: bool, has_active_trip: bool = False) -> ReplyKeyboardMarkup:
    """
    Main persistent reply keyboard for drivers based on status and duty.
    """
    if not is_approved:
        keyboard = [
            [
                KeyboardButton(text="🔄 Check Approval Status"),
                KeyboardButton(text="🚗 My Vehicle & Profile")
            ],
            [
                KeyboardButton(text="📞 Driver Support")
            ]
        ]
    elif has_active_trip:
        keyboard = [
            [
                KeyboardButton(text="📋 Current Active Trip"),
                KeyboardButton(text="📊 My Earnings & Payouts")
            ],
            [
                KeyboardButton(text="🚗 My Vehicle & Profile"),
                KeyboardButton(text="📞 Driver Support")
            ]
        ]
    elif is_online:
        keyboard = [
            [
                KeyboardButton(text="🔴 Go Offline (End Duty)"),
                KeyboardButton(text="🧪 Test Ride Request")
            ],
            [
                KeyboardButton(text="📊 My Earnings & Payouts"),
                KeyboardButton(text="🚗 My Vehicle & Profile")
            ],
            [
                KeyboardButton(text="📞 Driver Support")
            ]
        ]
    else:
        keyboard = [
            [
                KeyboardButton(text="🟢 Go Online (Ready for Rides)"),
                KeyboardButton(text="🧪 Test Ride Request")
            ],
            [
                KeyboardButton(text="📊 My Earnings & Payouts"),
                KeyboardButton(text="🚗 My Vehicle & Profile")
            ],
            [
                KeyboardButton(text="📞 Driver Support")
            ]
        ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True)

def get_driver_capacity_keyboard() -> InlineKeyboardMarkup:
    """Select vehicle max passenger capacity during registration"""
    buttons = [
        [
            InlineKeyboardButton(text="1 Seat 🧍", callback_data="driver_cap:1"),
            InlineKeyboardButton(text="2 Seats 👥", callback_data="driver_cap:2")
        ],
        [
            InlineKeyboardButton(text="3 Seats 👥👤", callback_data="driver_cap:3"),
            InlineKeyboardButton(text="4 Seats 👥👥", callback_data="driver_cap:4")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_dispatch_alert_keyboard(ride_id: str) -> InlineKeyboardMarkup:
    """FR-24: Alert card sent to online drivers when a ride is requested"""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Accept Ride", callback_data=f"d_accept:{ride_id}"),
            InlineKeyboardButton(text="❌ Decline", callback_data=f"d_decline:{ride_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_driver_trip_keyboard(ride_id: str, status: str) -> InlineKeyboardMarkup:
    """
    Simplified Driver Trip progression:
    1. '🚗 On the way to pickup' (when assigned)
    2. '🏁 Ride Completed' (prompts for PIN verification)
    """
    action_buttons = []
    if status == "confirmed":
        action_buttons.append([InlineKeyboardButton(text="🚗 On the way to pickup", callback_data=f"d_trip_action:{ride_id}:driver_en_route")])
    elif status == "driver_en_route":
        action_buttons.append([InlineKeyboardButton(text="🏁 Ride Completed", callback_data=f"d_trip_prompt_otp:{ride_id}")])

    action_buttons.append([InlineKeyboardButton(text="⚠️ Cancel Ride", callback_data=f"d_trip_cancel_prompt:{ride_id}")])
    return InlineKeyboardMarkup(inline_keyboard=action_buttons)

def get_driver_cancel_reasons_keyboard(ride_id: str) -> InlineKeyboardMarkup:
    """FR-27: Driver cancellation reasons"""
    buttons = [
        [InlineKeyboardButton(text="🚶 Student No-Show (5+ mins)", callback_data=f"d_cancel_reason:{ride_id}:Student no-show")],
        [InlineKeyboardButton(text="🛑 Vehicle Issue / Breakdown", callback_data=f"d_cancel_reason:{ride_id}:Vehicle breakdown")],
        [InlineKeyboardButton(text="🚧 Campus Road Blocked", callback_data=f"d_cancel_reason:{ride_id}:Road blocked")],
        [InlineKeyboardButton(text="❌ Emergency / Personal", callback_data=f"d_cancel_reason:{ride_id}:Emergency")],
        [InlineKeyboardButton(text="🔙 Back to Active Trip", callback_data=f"d_trip_back:{ride_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payout_actions_keyboard() -> InlineKeyboardMarkup:
    """FR-44: Payout dispute & details"""
    buttons = [
        [InlineKeyboardButton(text="⚠️ Raise Payout Dispute", callback_data="driver_raise_dispute")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_driver_support_keyboard() -> InlineKeyboardMarkup:
    """FR-53, FR-66, FR-67: Driver support & complaints"""
    buttons = [
        [InlineKeyboardButton(text="📝 Report Operational Issue / Complaint", callback_data="driver_report_issue")],
        [InlineKeyboardButton(text="🔄 Request Vehicle Details Update", callback_data="driver_req_update")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_driver_review_keyboard(driver_uid: int) -> InlineKeyboardMarkup:
    """FR-10: Admin approval keyboard"""
    buttons = [
        [
            InlineKeyboardButton(text="✅ Approve Driver", callback_data=f"adm_appr:{driver_uid}"),
            InlineKeyboardButton(text="❌ Reject Driver", callback_data=f"adm_rej:{driver_uid}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
