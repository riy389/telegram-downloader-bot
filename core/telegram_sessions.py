import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SESSIONS_DIR = BASE_DIR / "telegram_sessions"

_clients: dict[int, TelegramClient] = {}


def _get_api_credentials() -> tuple[int, str]:
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

    return api_id_int, api_hash


def _get_session_path(user_id: int) -> Path:
    if user_id <= 0:
        raise ValueError(
            "Telegram user ID tidak valid."
        )

    user_dir = SESSIONS_DIR / str(user_id)
    user_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return user_dir / "telegram"


def get_telegram_client(user_id: int) -> TelegramClient:
    client = _clients.get(user_id)

    if client is not None:
        return client

    api_id, api_hash = _get_api_credentials()
    session_path = _get_session_path(user_id)

    client = TelegramClient(
        str(session_path),
        api_id,
        api_hash,
    )

    _clients[user_id] = client

    return client


async def connect_telegram_user(
    user_id: int,
) -> TelegramClient:
    client = get_telegram_client(user_id)

    if not client.is_connected():
        await client.connect()

    me = await client.get_me()

    if me is None:
        raise RuntimeError(
            f"Session Telegram untuk user {user_id} "
            "belum login."
        )

    if me.id != user_id:
        raise RuntimeError(
            f"Session Telegram tidak cocok dengan requester. "
            f"Requester={user_id}, session={me.id}."
        )

    return client


async def disconnect_telegram_user(
    user_id: int,
) -> None:
    client = _clients.get(user_id)

    if client is not None and client.is_connected():
        await client.disconnect()


async def disconnect_all_telegram_users() -> None:
    for client in _clients.values():
        if client.is_connected():
            await client.disconnect()
