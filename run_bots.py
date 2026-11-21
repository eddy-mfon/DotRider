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
from db import db
from timer_worker import run_timer_worker_loop

import student_bot
import driver_bot
import admin_bot
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("runner")

async def run_all():
    db.init_schema()

    tasks = []

    # 1. Timer Worker
    tasks.append(asyncio.create_task(run_timer_worker_loop()))

    # 2. Student Bot
    if config.STUDENT_BOT_TOKEN:
        s_bot = student_bot.Bot(token=config.STUDENT_BOT_TOKEN, default=student_bot.DefaultBotProperties(parse_mode=student_bot.ParseMode.HTML))
        tasks.append(asyncio.create_task(student_bot.dp.start_polling(s_bot)))
        logger.info("Student Bot initialized.")

    # 3. Driver Bot
    if config.DRIVER_BOT_TOKEN:
        d_bot = driver_bot.Bot(token=config.DRIVER_BOT_TOKEN, default=driver_bot.DefaultBotProperties(parse_mode=driver_bot.ParseMode.HTML))
        tasks.append(asyncio.create_task(driver_bot.dp.start_polling(d_bot)))
        logger.info("Driver Bot initialized.")

    # 4. Admin Bot
    if config.ADMIN_BOT_TOKEN:
        a_bot = admin_bot.Bot(token=config.ADMIN_BOT_TOKEN, default=admin_bot.DefaultBotProperties(parse_mode=admin_bot.ParseMode.HTML))
        tasks.append(asyncio.create_task(admin_bot.dp.start_polling(a_bot)))
        logger.info("Admin Bot initialized.")

    logger.info("All services running.")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(run_all())
    except (KeyboardInterrupt, SystemExit):
        logger.info("All bots shut down gracefully.")
