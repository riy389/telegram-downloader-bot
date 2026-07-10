from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import asyncio

from utils.config import BOT_TOKEN
from utils.logger import logger

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()


async def main():
    logger.info("Starting Telegram Downloader Bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
