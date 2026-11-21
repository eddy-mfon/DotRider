"""
Cross-bot notifier module.
Allows Student Bot, Driver Bot, Admin Bot, or background workers
to deliver messages reliably using the appropriate bot tokens.
"""
import logging
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import config

logger = logging.getLogger(__name__)

student_bot: Bot | None = None
driver_bot: Bot | None = None
admin_bot: Bot | None = None

def get_student_bot() -> Bot:
    global student_bot
    if student_bot is None:
        token = config.STUDENT_BOT_TOKEN
        if not token:
            raise ValueError("STUDENT_BOT_TOKEN is not configured")
        student_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return student_bot

def get_driver_bot() -> Bot:
    global driver_bot
    if driver_bot is None:
        token = config.DRIVER_BOT_TOKEN
        if not token:
            raise ValueError("DRIVER_BOT_TOKEN is not configured")
        driver_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return driver_bot

def get_admin_bot() -> Bot:
    global admin_bot
    if admin_bot is None:
        token = config.ADMIN_BOT_TOKEN
        if not token:
            raise ValueError("ADMIN_BOT_TOKEN is not configured")
        admin_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return admin_bot

async def notify_student(student_id: int, text: str, reply_markup=None):
    """Sends a message to a student via the Student Bot."""
    try:
        bot = get_student_bot()
        await bot.send_message(chat_id=student_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to notify student {student_id}: {e}")

async def notify_driver(driver_id: int, text: str, reply_markup=None):
    """Sends a message to a driver via the Driver Bot."""
    try:
        bot = get_driver_bot()
        await bot.send_message(chat_id=driver_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to notify driver {driver_id}: {e}")

async def notify_admin(text: str, reply_markup=None):
    """Sends a notification directly through the Admin Bot to the registered admin."""
    if not config.ADMIN_CHAT_ID:
        return
    try:
        bot = get_admin_bot()
        await bot.send_message(chat_id=int(config.ADMIN_CHAT_ID), text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
