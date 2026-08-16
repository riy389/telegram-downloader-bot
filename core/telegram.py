import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo

from utils.thumbnail import create_thumbnail


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SESSION_PATH = BASE_DIR / "telegram_user"

_client: TelegramClient | None = None


def get_telegram_client() -> TelegramClient:
    global _client

    if _client is None:
        api_id = os.getenv("API_ID")
        api_hash = os.getenv("API_HASH")

        if not api_id or not api_hash:
            raise RuntimeError(
                "API_ID dan API_HASH belum diset di .env"
            )

        try:
            api_id_int = int(api_id)
        except ValueError as exc:
            raise RuntimeError(
                "API_ID harus berupa angka"
            ) from exc

        _client = TelegramClient(
            str(SESSION_PATH),
            api_id_int,
            api_hash,
        )

    return _client


async def connect_telegram_user() -> TelegramClient:
    client = get_telegram_client()

    if not client.is_connected():
        await client.connect()

    return client


async def send_video(
    chat_id: int | str,
    file_path: str,
    caption: str | None = None,
    video_meta: dict | None = None,
    progress_callback=None,
):
    client = await connect_telegram_user()

    attributes = None

    if video_meta is not None:
        attributes = [
            DocumentAttributeVideo(
                duration=float(video_meta["duration"]),
                w=int(video_meta["width"]),
                h=int(video_meta["height"]),
                supports_streaming=True,
            )
        ]

    thumb_path = None

    try:
        try:
            thumb_path = create_thumbnail(file_path)
        except Exception:
            thumb_path = None

        return await client.send_file(
            chat_id,
            file_path,
            caption=caption,
            attributes=attributes,
            supports_streaming=True,
            progress_callback=progress_callback,
            thumb=str(thumb_path) if thumb_path else None,
        )

    finally:
        if thumb_path is not None:
            try:
                thumb_path.unlink(missing_ok=True)
            except Exception:
                pass


async def disconnect_telegram_user():
    global _client

    if _client is not None and _client.is_connected():
        await _client.disconnect()
