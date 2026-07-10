import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
BOT_MODE = os.getenv("BOT_MODE", "development").lower()
