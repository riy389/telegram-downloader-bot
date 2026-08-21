import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, errors
from telethon.tl import functions, types
from telethon.tl.types import DocumentAttributeVideo

from utils.thumbnail import create_thumbnail


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SESSION_PATH = BASE_DIR / "telegram_user"

_client: TelegramClient | None = None
_telegram_user_id: int | None = None


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
    global _telegram_user_id

    client = get_telegram_client()

    if not client.is_connected():
        await client.connect()

    if _telegram_user_id is None:
        me = await client.get_me()

        if me is None:
            raise RuntimeError(
                "Tidak dapat mengetahui akun Telegram Telethon."
            )

        _telegram_user_id = me.id

    return client


def get_telegram_user_id() -> int | None:
    return _telegram_user_id


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



async def _parallel_download_telegram_document(
    client: TelegramClient,
    document,
    target_path: Path,
    chat_id: int,
    message_id: int,
    progress_callback=None,
) -> Path:
    """
    Download Telegram document using 4 parallel MTProto workers.

    Each worker uses an exported sender for the document's DC and downloads
    independent byte ranges directly into the final file.
    """

    file_size = int(document.size)

    REQUEST_SIZE = 512 * 1024
    WORKERS = 4

    REQUEST_SIZE -= REQUEST_SIZE % 4096

    location = types.InputDocumentFileLocation(
        id=document.id,
        access_hash=document.access_hash,
        file_reference=document.file_reference,
        thumb_size="",
    )

    # Pre-allocate the destination file.
    with open(target_path, "wb") as f:
        f.truncate(file_size)

    downloaded = 0
    progress_lock = asyncio.Lock()

    async def report_progress():
        if progress_callback is None:
            return

        async with progress_lock:
            current = downloaded

        result = progress_callback(
            current,
            file_size,
        )

        if asyncio.iscoroutine(result):
            await result

    async def worker(worker_id: int):
        nonlocal downloaded

        sender = None
        borrowed_sender = False

        try:
            if document.dc_id == client.session.dc_id:
                sender = client._sender
            else:
                sender = await client._borrow_exported_sender(
                    document.dc_id
                )
                borrowed_sender = True

            offset = worker_id * REQUEST_SIZE

            with open(target_path, "r+b", buffering=0) as f:
                while offset < file_size:
                    request_limit = REQUEST_SIZE

                    request = functions.upload.GetFileRequest(
                        location,
                        offset=offset,
                        limit=request_limit,
                    )

                    while True:
                        try:
                            result = await client._call(
                                sender,
                                request,
                            )

                            data = result.bytes
                            break

                        except (
                            errors.FilerefUpgradeNeededError,
                            errors.FileReferenceExpiredError,
                        ):
                            fresh = await client.get_messages(
                                chat_id,
                                ids=message_id,
                            )

                            if (
                                not fresh
                                or not fresh.document
                                or fresh.document.id != document.id
                            ):
                                raise

                            location.file_reference = (
                                fresh.document.file_reference
                            )

                    if not data:
                        raise RuntimeError(
                            f"Worker {worker_id} menerima chunk kosong "
                            f"pada offset {offset}."
                        )

                    f.seek(offset)
                    f.write(data)

                    async with progress_lock:
                        downloaded += len(data)

                    await report_progress()

                    offset += WORKERS * REQUEST_SIZE

        finally:
            if borrowed_sender and sender is not None:
                await client._return_exported_sender(sender)

    await asyncio.gather(
        *(worker(i) for i in range(WORKERS))
    )

    if not target_path.exists():
        raise RuntimeError(
            "Parallel downloader gagal membuat file."
        )

    actual_size = target_path.stat().st_size

    if actual_size != file_size:
        raise RuntimeError(
            f"Ukuran file tidak sesuai: "
            f"{actual_size} != {file_size}"
        )

    if progress_callback is not None:
        result = progress_callback(
            file_size,
            file_size,
        )

        if asyncio.iscoroutine(result):
            await result

    return target_path


async def download_telegram_media(
    chat_id: int,
    message_id: int,
    output_dir: str | Path,
    progress_callback=None,
) -> Path:
    """
    Download media from the original Telegram message using Telethon.

    This bypasses the Bot API file-download path and allows large Telegram
    media to be downloaded directly by the MTProto user session.
    """

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    client = await connect_telegram_user()

    message = await client.get_messages(
        chat_id,
        ids=message_id,
    )

    if not message:
        raise RuntimeError(
            "Pesan Telegram asli tidak ditemukan melalui Telethon."
        )

    if not message.media:
        raise RuntimeError(
            "Pesan Telegram asli tidak memiliki media."
        )

    if not message.document:
        raise RuntimeError(
            "Media Telegram bukan document yang dapat diunduh."
        )

    document = message.document

    file_name = None

    for attribute in document.attributes:
        if hasattr(attribute, "file_name") and attribute.file_name:
            file_name = attribute.file_name
            break

    if not file_name:
        file_name = f"telegram_{message_id}.bin"

    target_path = output_path / file_name

    await _parallel_download_telegram_document(
        client=client,
        document=document,
        target_path=target_path,
        chat_id=chat_id,
        message_id=message_id,
        progress_callback=progress_callback,
    )

    if not target_path.exists():
        raise RuntimeError(
            "Telethon gagal mengunduh media Telegram."
        )

    return target_path
