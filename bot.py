"""
Legacy bot.py wrapper.
Delegates execution to run_bots.py so services configured to run `python bot.py`
will start the full 3-bot architecture and timer worker seamlessly.
"""
import sys
import os

if __name__ == "__main__":
    import run_bots
    import asyncio
    asyncio.run(run_bots.run_all())
