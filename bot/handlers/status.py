from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.whitelist import is_allowed

router = Router()


@router.message(Command("status"))
async def status_command(message: Message):
    if not is_allowed(message.from_user.id):
        await message.answer("❌ Access denied.")
        return

    await message.answer(
        "🟢 Bot Status\n\n"
        "Status : Online\n"
        "Mode   : Development\n"
        "Source : X (coming soon)"
    )
