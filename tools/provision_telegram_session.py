import getpass
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, errors


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SESSIONS_DIR = BASE_DIR / "telegram_sessions"
TEMP_DIR = SESSIONS_DIR / ".provisioning"


def get_api_credentials() -> tuple[int, str]:
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


def secure_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def secure_file(path: Path) -> None:
    if path.exists():
        os.chmod(path, 0o600)


async def provision() -> None:
    api_id, api_hash = get_api_credentials()

    secure_mkdir(SESSIONS_DIR)
    secure_mkdir(TEMP_DIR)

    phone = input(
        "Nomor Telegram (+62...): "
    ).strip()

    if not phone:
        raise RuntimeError(
            "Nomor Telegram tidak boleh kosong."
        )

    temp_session_dir = TEMP_DIR / phone.replace("+", "plus_")
    secure_mkdir(temp_session_dir)

    temp_session = temp_session_dir / "telegram"

    client = TelegramClient(
        str(temp_session),
        api_id,
        api_hash,
    )

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
        else:
            sent = await client.send_code_request(phone)

            code = input(
                "Kode OTP Telegram: "
            ).strip()

            if not code:
                raise RuntimeError(
                    "Kode OTP tidak boleh kosong."
                )

            try:
                await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=sent.phone_code_hash,
                )

            except errors.SessionPasswordNeededError:
                password = getpass.getpass(
                    "Password 2FA Telegram: "
                )

                if not password:
                    raise RuntimeError(
                        "Password 2FA tidak boleh kosong."
                    )

                await client.sign_in(
                    password=password,
                )

            me = await client.get_me()

        if me is None:
            raise RuntimeError(
                "Login berhasil tetapi akun Telegram "
                "tidak dapat diidentifikasi."
            )

        user_id = int(me.id)

        target_dir = SESSIONS_DIR / str(user_id)
        target_session = target_dir / "telegram.session"

        secure_mkdir(target_dir)

        if target_session.exists():
            raise RuntimeError(
                f"Session untuk user {user_id} sudah ada: "
                f"{target_session}"
            )

        await client.disconnect()

        source_session = temp_session.with_suffix(".session")

        if not source_session.exists():
            raise RuntimeError(
                f"File session tidak ditemukan: {source_session}"
            )

        shutil.move(
            str(source_session),
            str(target_session),
        )

        secure_file(target_session)

        print()
        print("Login berhasil.")
        print(f"Telegram user ID : {user_id}")
        print(f"Session          : {target_session}")
        print()
        print(
            "OTP dan password 2FA tidak disimpan "
            "oleh script."
        )

    finally:
        if client.is_connected():
            await client.disconnect()

        if temp_session_dir.exists():
            shutil.rmtree(
                temp_session_dir,
                ignore_errors=True,
            )


if __name__ == "__main__":
    import asyncio

    asyncio.run(provision())
