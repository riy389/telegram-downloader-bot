from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.whitelist import is_allowed

router = Router()


@router.message(Command("help"))
async def help_command(message: Message):
    if not is_allowed(message.from_user.id):
        await message.answer("❌ Access denied.")
        return

    await message.answer(
        "📖 Available commands:\n\n"
        "/start - Start the bot\n"
        "/help - Show this message\n"
        "/status - Show bot status"
    )
