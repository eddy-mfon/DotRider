"""
Master Runner for Campus Shuttle ecosystem.
Launches:
1. Student Bot (@dotriderbot)
2. Driver Bot (@dotdrivers_bot)
3. Admin Bot (@dotrideradmin_bot)
4. Background Timer Worker
"""
import asyncio
import logging
import os
import aiohttp
from aiohttp import web
from aiogram.types import BotCommand
from db import db
from timer_worker import run_timer_worker_loop

import student_bot
import driver_bot
import admin_bot
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("runner")

async def health_check_handler(request):
    return web.Response(text="DotRider Shuttle Bots are healthy and running 24/7!", status=200)

async def keep_alive_ping_loop():
    """
    Self-ping background task:
    Sends an HTTP GET request to its own Render public URL every 10 minutes
    to prevent Render free tier web service from going to sleep.
    """
    await asyncio.sleep(60)  # wait 1 min for server to be fully online
    render_external_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    port = int(os.getenv("PORT", 10000))
    ping_url = render_external_url if render_external_url else f"http://127.0.0.1:{port}"

    logger.info(f"Keep-alive self-ping task started targeting: {ping_url}")
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{ping_url}/health", timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    logger.info(f"Keep-alive ping sent to {ping_url} - Status: {resp.status}")
        except Exception as e:
            logger.warning(f"Keep-alive self-ping warning (normal during initial startup): {e}")
        # Ping every 10 minutes (600 seconds)
        await asyncio.sleep(600)

async def start_web_health_server():
    """Binds to PORT for Render Web Service compatibility and health checks."""
    port = int(os.getenv("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server listening on port {port} for Render Web Service.")

async def run_all():
    db.init_schema()

    tasks = []

    # 1. Health server to satisfy Render Web Service port checks
    tasks.append(asyncio.create_task(start_web_health_server()))

    # 2. Keep-alive self-ping loop to prevent Render sleep
    tasks.append(asyncio.create_task(keep_alive_ping_loop()))

    # 3. Timer Worker
    tasks.append(asyncio.create_task(run_timer_worker_loop()))

    # 3. Student Bot
    if config.STUDENT_BOT_TOKEN:
        s_bot = student_bot.Bot(token=config.STUDENT_BOT_TOKEN, default=student_bot.DefaultBotProperties(parse_mode=student_bot.ParseMode.HTML))
        await s_bot.set_my_commands([
            BotCommand(command="start", description="Restart / Open Main Menu"),
            BotCommand(command="book", description="Book a Campus Shuttle"),
            BotCommand(command="wallet", description="View Balance & Top-Up Wallet"),
            BotCommand(command="ride", description="Check Current Active Ride Status"),
            BotCommand(command="history", description="View Past Ride History"),
            BotCommand(command="fares", description="Campus Locations & Fare Rates"),
            BotCommand(command="help", description="Dispatch Support & Contact Info")
        ])
        tasks.append(asyncio.create_task(student_bot.dp.start_polling(s_bot)))
        logger.info("Student Bot initialized with commands menu.")

    # 4. Driver Bot
    if config.DRIVER_BOT_TOKEN:
        d_bot = driver_bot.Bot(token=config.DRIVER_BOT_TOKEN, default=driver_bot.DefaultBotProperties(parse_mode=driver_bot.ParseMode.HTML))
        await d_bot.set_my_commands([
            BotCommand(command="start", description="Driver Dashboard / Profile"),
            BotCommand(command="online", description="🟢 Go Online (Ready for Rides)"),
            BotCommand(command="offline", description="🔴 Go Offline (End Duty)"),
            BotCommand(command="trip", description="📋 Current Active Trip & Controls"),
            BotCommand(command="profile", description="📊 My Vehicle & Star Ratings"),
            BotCommand(command="help", description="ℹ️ Driver Rules & Help")
        ])
        tasks.append(asyncio.create_task(driver_bot.dp.start_polling(d_bot)))
        logger.info("Driver Bot initialized with commands menu.")

    # 5. Admin Bot
    if config.ADMIN_BOT_TOKEN:
        a_bot = admin_bot.Bot(token=config.ADMIN_BOT_TOKEN, default=admin_bot.DefaultBotProperties(parse_mode=admin_bot.ParseMode.HTML))
        await a_bot.set_my_commands([
            BotCommand(command="start", description="Open Admin Dashboard"),
            BotCommand(command="payments", description="⏳ View & Approve Bank Top-Ups"),
            BotCommand(command="credit", description="💳 Credit Student Wallet"),
            BotCommand(command="refund", description="↩️ Issue Manual Refund"),
            BotCommand(command="stuck", description="⚠️ Inspect Active / Stuck Rides"),
            BotCommand(command="fleet", description="🚗 View Online Drivers & Fleet"),
            BotCommand(command="summary", description="📊 System Performance Summary")
        ])
        tasks.append(asyncio.create_task(admin_bot.dp.start_polling(a_bot)))
        logger.info("Admin Bot initialized with commands menu.")

    logger.info("All services and health server running.")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(run_all())
    except (KeyboardInterrupt, SystemExit):
        logger.info("All bots shut down gracefully.")
