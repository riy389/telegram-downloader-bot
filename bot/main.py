import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers.start import router as start_router
from bot.handlers.help import router as help_router
from bot.handlers.status import router as status_router

from utils.config import BOT_TOKEN
from utils.logger import logger

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()

# Register routers
dp.include_router(start_router)
dp.include_router(help_router)
dp.include_router(status_router)


async def main():
    logger.info("Starting Telegram Downloader Bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
