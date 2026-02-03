# -*- coding: utf-8 -*-
import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot

async def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("ERROR: env TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set")
        return
    # корректное закрытие HTTP-сессии, чтобы не было Event loop is closed
    async with Bot(token=token) as bot:
        await bot.send_message(chat_id=chat_id, text="SenseiTrader: test_notify OK")
    print("OK: message sent")

if __name__ == "__main__":
    asyncio.run(main())
