from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.whitelist import is_allowed

router = Router()


@router.message(Command("start"))
async def start_command(message: Message):
    if not is_allowed(message.from_user.id):
        await message.answer("❌ Access denied.")
        return

    await message.answer(
        "✅ Telegram Downloader Bot is online.\n\n"
        "Send me a supported video URL to start downloading."
    )
