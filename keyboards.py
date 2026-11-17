"""
Keyboards and menus for the Covenant University Shuttle Bot.
Complies with UI grid layouts and SRS requirements.
"""
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from config import HALLS, DESTINATIONS

def get_main_menu_keyboard(is_registered: bool = False) -> ReplyKeyboardMarkup:
    """
    Main persistent reply keyboard matching the 2x2 grid layout from reference image.
    If not registered, prioritizes registration.
    """
    if not is_registered:
        keyboard = [
            [
                KeyboardButton(text="📝 Register / Sign Up"),
                KeyboardButton(text="ℹ️ Campus Locations & Fare")
            ],
            [
                KeyboardButton(text="👤 My Student Profile"),
                KeyboardButton(text="📞 Support / Help")
            ]
        ]
    else:
        keyboard = [
            [
                KeyboardButton(text="🚖 Book a Shuttle"),
                KeyboardButton(text="🔄 Return Trip (Back to Hall)")
            ],
            [
                KeyboardButton(text="📋 Active Rides / Status"),
                KeyboardButton(text="🏷️ Apply Promo / Discount")
            ],
            [
                KeyboardButton(text="👤 My Student Profile"),
                KeyboardButton(text="ℹ️ Campus Locations & Fare")
            ]
        ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True)

def get_halls_keyboard(action_prefix: str = "hall") -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for hall in HALLS:
        row.append(InlineKeyboardButton(text=f"🏢 {hall}", callback_data=f"{action_prefix}:{hall}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_booking")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_destinations_keyboard(action_prefix: str = "dest") -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for dest in DESTINATIONS:
        label = dest.split("(")[0].strip()
        row.append(InlineKeyboardButton(text=f"📍 {label}", callback_data=f"{action_prefix}:{dest}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_booking")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_passengers_keyboard() -> InlineKeyboardMarkup:
    """
    FR-20: Supports 1 to 4 passengers
    """
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
            InlineKeyboardButton(text="🚫 Cancel Ride", callback_data=f"cancel_ride:{ride_id}"),
            InlineKeyboardButton(text="🏁 Ride Completed", callback_data=f"complete_ride:{ride_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
