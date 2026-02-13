import os
import asyncio
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

router = Router()

@router.message(Command("ping"))
async def ping(message: Message):
    await message.answer("pong ✅")

@router.message(Command("chatid"))
async def chatid(message: Message):
    await message.answer(f"chat_id: {message.chat.id}")

async def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    print("Bot starting (aiogram)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
