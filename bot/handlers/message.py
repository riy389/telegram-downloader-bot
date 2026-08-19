from pathlib import Path
import re
import asyncio

import aiohttp
from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from core.router import detect_source
from core.telegram import send_video, download_telegram_media, get_telegram_user_id
from sources.x import get_x_videos
from utils.downloader import download_url
from utils.probe import probe_video
from utils.splitter import split_video


router = Router()

URL_PATTERN = re.compile(r"https?://\S+")

VIDEO_CACHE: dict[str, list[dict]] = {}
RENAME_CACHE: dict[int, dict] = {}
TELEGRAM_VIDEO_CACHE: dict[str, dict] = {}


async def get_file_size(url: str) -> int | None:
    try:
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.head(
                url,
                allow_redirects=True,
            ) as response:
                content_length = response.headers.get("Content-Length")

                if content_length:
                    return int(content_length)

    except Exception:
        pass

    return None


def format_size(size: int | None) -> str:
    if size is None:
        return "Size ?"

    mb = size / (1024 * 1024)

    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"

    return f"{mb:.2f} MB"


def format_progress(current: int, total: int | None) -> str:
    if total is None or total <= 0:
        return f"{current / (1024 * 1024):.2f} MB"

    percent = current * 100 / total

    return (
        f"{percent:.1f}% "
        f"({current / (1024 * 1024):.2f} / "
        f"{total / (1024 * 1024):.2f} MB)"
    )


def format_speed(speed: float) -> str:
    return f"{speed / (1024 * 1024):.2f} MB/s"


def format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "00:00"

    seconds = int(seconds)

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)

    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


async def update_progress(
    message: Message,
    text: str,
):
    try:
        await message.edit_text(text)
    except Exception:
        pass


@router.message(F.video | F.document)
async def handle_telegram_video(message: Message):
    media = message.video

    if media is None and message.document:
        if not (
            message.document.mime_type
            and message.document.mime_type.startswith("video/")
        ):
            return

        media = message.document

    if media is None:
        return

    # Jangan proses video yang dikirim kembali oleh akun Telethon.
    if message.from_user:
        telegram_user_id = get_telegram_user_id()

        if (
            telegram_user_id is not None
            and message.from_user.id == telegram_user_id
        ):
            return

        if message.from_user.is_bot:
            return

    cache_key = f"telegram:{message.chat.id}:{message.message_id}"

    source_chat_id = None
    source_message_id = None

    if message.forward_origin:
        origin = message.forward_origin

        if hasattr(origin, "chat") and origin.chat:
            source_chat_id = origin.chat.id

        if hasattr(origin, "message_id"):
            source_message_id = origin.message_id

    TELEGRAM_VIDEO_CACHE[cache_key] = {
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "source_chat_id": source_chat_id,
        "source_message_id": source_message_id,
        "file_name": media.file_name,
        "file_size": media.file_size,
    }

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✂️ Split Video",
                    callback_data=f"tgsplit:{message.chat.id}:{message.message_id}",
                )
            ]
        ]
    )

    size_text = format_size(media.file_size)

    await message.answer(
        f"Video diterima ({size_text}). Mau diapakan?",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("tgsplit:"))
async def handle_telegram_split(callback: CallbackQuery):
    if not callback.data:
        await callback.answer("Data tidak valid.", show_alert=True)
        return

    try:
        _, chat_id_str, message_id_str = callback.data.split(":", 2)
        chat_id = int(chat_id_str)
        message_id = int(message_id_str)
    except (ValueError, TypeError):
        await callback.answer(
            "Data video tidak valid.",
            show_alert=True,
        )
        return

    cache_key = f"telegram:{chat_id}:{message_id}"
    video_info = TELEGRAM_VIDEO_CACHE.get(cache_key)

    if not video_info:
        await callback.answer(
            "Data video sudah tidak tersedia. Kirim ulang videonya.",
            show_alert=True,
        )
        return

    source_chat_id = video_info.get("source_chat_id")
    source_message_id = video_info.get("source_message_id")
    original_file_name = video_info.get("file_name")

    if source_chat_id is None or source_message_id is None:
        await callback.answer(
            "Pesan ini bukan forward channel yang bisa diambil ulang.",
            show_alert=True,
        )
        return

    await callback.answer()

    status_message = callback.message

    if status_message:
        await status_message.edit_text(
            "⏬ Mengambil video dari Telegram via Telethon..."
        )

    MAX_SPLIT_SIZE = int(1.95 * 1024 * 1024 * 1024)

    downloaded_path = None
    split_parts = []

    try:
        download_dir = "/tmp/telegram_downloader/telegram_input"

        last_download_update = 0
        download_started = asyncio.get_running_loop().time()

        async def download_progress(
            current: int,
            total: int | None,
        ):
            nonlocal last_download_update

            now = asyncio.get_running_loop().time()

            if now - last_download_update < 2:
                return

            last_download_update = now

            elapsed = max(now - download_started, 0.001)
            speed = current / elapsed

            if total and total > 0:
                percent = current * 100 / total

                eta = (
                    format_eta((total - current) / speed)
                    if speed > 0
                    else "--:--"
                )

                progress_text = (
                    "⏬ Mengambil video dari Telegram...\n\n"
                    f"Progress:\n{percent:.1f}%\n\n"
                    f"Speed:\n{format_speed(speed)}\n\n"
                    f"ETA:\n{eta}"
                )
            else:
                progress_text = (
                    "⏬ Mengambil video dari Telegram...\n\n"
                    "Progress:\n"
                    f"{current / (1024 * 1024):.2f} MB"
                )

            if status_message:
                await update_progress(
                    status_message,
                    progress_text,
                )

        downloaded_path = await download_telegram_media(
            chat_id=source_chat_id,
            message_id=source_message_id,
            output_dir=download_dir,
            progress_callback=download_progress,
        )

        file_size = downloaded_path.stat().st_size

        print(
            f"TELEGRAM VIDEO: "
            f"{downloaded_path.name} "
            f"{format_size(file_size)}"
        )

        if file_size > MAX_SPLIT_SIZE:
            if status_message:
                await status_message.edit_text(
                    "✂️ Video lebih besar dari 1.95 GiB.\n"
                    "Membagi video menjadi beberapa bagian..."
                )

            split_dir = (
                downloaded_path.parent
                / f"{downloaded_path.stem}_parts"
            )

            split_parts = split_video(
                downloaded_path,
                split_dir,
                MAX_SPLIT_SIZE,
            )

            upload_files = split_parts
        else:
            upload_files = [downloaded_path]

        total_parts = len(upload_files)

        base_name = (
            Path(original_file_name).stem
            if original_file_name
            else downloaded_path.stem
        )

        for part_index, upload_file in enumerate(
            upload_files,
            start=1,
        ):
            if total_parts > 1:
                part_label = f" Part {part_index}/{total_parts}"
                upload_caption = (
                    f"{base_name} • "
                    f"Part {part_index}/{total_parts}"
                )
            else:
                part_label = ""
                upload_caption = base_name

            if status_message:
                await status_message.edit_text(
                    f"📋 Membaca metadata video{part_label}..."
                )

            meta = probe_video(upload_file)

            print(
                f"TELEGRAM VIDEO META{part_label}: "
                f"duration={meta['duration']}s, "
                f"width={meta['width']}, "
                f"height={meta['height']}"
            )

            if status_message:
                await status_message.edit_text(
                    f"📤 Upload{part_label}...\n"
                    f"Progress: 0%"
                )

            last_upload_update = 0
            upload_started = asyncio.get_running_loop().time()

            async def upload_progress(
                current: int,
                total: int,
            ):
                nonlocal last_upload_update

                now = asyncio.get_running_loop().time()

                if now - last_upload_update < 1:
                    return

                last_upload_update = now

                elapsed = max(now - upload_started, 0.001)
                speed = current / elapsed

                if total and total > 0:
                    percent = current * 100 / total

                    eta = (
                        format_eta((total - current) / speed)
                        if speed > 0
                        else "--:--"
                    )

                    text = (
                        f"📤 Upload{part_label}...\n\n"
                        f"Progress:\n{percent:.1f}%\n\n"
                        f"Speed:\n{format_speed(speed)}\n\n"
                        f"ETA:\n{eta}"
                    )
                else:
                    text = (
                        f"📤 Upload{part_label}...\n\n"
                        f"Progress:\n"
                        f"{current / (1024 * 1024):.2f} MB"
                    )

                if status_message:
                    await update_progress(
                        status_message,
                        text,
                    )

            await send_video(
                "@Sprdownloader_bot",
                str(upload_file),
                caption=upload_caption,
                video_meta=meta,
                progress_callback=upload_progress,
            )

        if status_message:
            await status_message.edit_text(
                f"✅ Video Telegram selesai diproses.\n\n"
                f"Total part: {total_parts}"
            )

    except Exception as exc:
        if status_message:
            await status_message.edit_text(
                f"❌ Gagal memproses video Telegram.\n\n"
                f"{type(exc).__name__}: {exc}"
            )

        print(
            f"TELEGRAM VIDEO ERROR: "
            f"{type(exc).__name__}: {exc}"
        )

    finally:
        if downloaded_path is not None:
            try:
                downloaded_path.unlink(missing_ok=True)
            except Exception as exc:
                print(
                    f"TELEGRAM CLEANUP ORIGINAL ERROR: {exc}"
                )

        for part in split_parts:
            try:
                part.unlink(missing_ok=True)
            except Exception as exc:
                print(
                    f"TELEGRAM CLEANUP PART ERROR: {exc}"
                )

        if split_parts:
            split_dir = split_parts[0].parent

            try:
                split_dir.rmdir()
            except Exception as exc:
                print(
                    f"TELEGRAM CLEANUP DIR ERROR: {exc}"
                )

        TELEGRAM_VIDEO_CACHE.pop(cache_key, None)


@router.message()
async def handle_message(message: Message):
    text = message.text or ""

    if message.from_user and message.from_user.id in RENAME_CACHE:
        await handle_rename(message)
        return

    match = URL_PATTERN.search(text)

    if not match:
        return

    url = match.group(0)
    source = detect_source(url)

    if source != "x":
        await message.reply(
            f"✅ URL terdeteksi\n\n"
            f"Source: {source}"
        )
        return

    result = await get_x_videos(url)

    if result["error"]:
        await message.reply(
            f"❌ Gagal mengambil data X.\n\n"
            f"Error: {result['error']}"
        )
        return

    videos = result["videos"]

    if not videos:
        await message.reply(
            "❌ Tweet tidak memiliki video MP4 yang tersedia."
        )
        return

    tweet_id = result["tweet_id"]

    for video in videos:
        video["size"] = await get_file_size(video["url"])

    VIDEO_CACHE[tweet_id] = videos

    buttons = []

    for index, video in enumerate(videos):
        width = video.get("width")
        height = video.get("height")
        size = format_size(video.get("size"))

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{width}x{height} • {size}",
                    callback_data=f"xvideo:{tweet_id}:{index}",
                )
            ]
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=buttons
    )

    await message.reply(
        "🎬 Video X ditemukan.\n\n"
        "Pilih resolusi:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("xvideo:"))
async def handle_x_video_choice(callback: CallbackQuery):
    if not callback.data:
        await callback.answer()
        return

    try:
        _, tweet_id, index_text = callback.data.split(":", 2)
        index = int(index_text)

    except (ValueError, AttributeError):
        await callback.answer(
            "Pilihan tidak valid.",
            show_alert=True,
        )
        return

    videos = VIDEO_CACHE.get(tweet_id)

    if not videos or index < 0 or index >= len(videos):
        await callback.answer(
            "Pilihan sudah tidak tersedia.",
            show_alert=True,
        )
        return

    video = videos[index]

    await callback.answer()

    width = video.get("width")
    height = video.get("height")
    size = format_size(video.get("size"))

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Default",
                    callback_data=f"xdefault:{tweet_id}:{index}",
                ),
                InlineKeyboardButton(
                    text="Rename",
                    callback_data=f"xrename:{tweet_id}:{index}",
                ),
            ]
        ]
    )

    await callback.message.edit_text(
        f"🎬 {width}x{height} • {size}\n\n"
        "Pilih nama file:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("xdefault:"))
async def handle_default_choice(callback: CallbackQuery):
    if not callback.data:
        await callback.answer()
        return

    try:
        _, tweet_id, index_text = callback.data.split(":", 2)
        index = int(index_text)

    except (ValueError, AttributeError):
        await callback.answer(
            "Pilihan tidak valid.",
            show_alert=True,
        )
        return

    videos = VIDEO_CACHE.get(tweet_id)

    if not videos or index < 0 or index >= len(videos):
        await callback.answer(
            "Pilihan sudah tidak tersedia.",
            show_alert=True,
        )
        return

    await callback.answer()

    await process_video(
        callback.message,
        tweet_id,
        index,
        None,
    )


@router.callback_query(F.data.startswith("xrename:"))
async def handle_rename_choice(callback: CallbackQuery):
    if not callback.data:
        await callback.answer()
        return

    try:
        _, tweet_id, index_text = callback.data.split(":", 2)
        index = int(index_text)

    except (ValueError, AttributeError):
        await callback.answer(
            "Pilihan tidak valid.",
            show_alert=True,
        )
        return

    videos = VIDEO_CACHE.get(tweet_id)

    if not videos or index < 0 or index >= len(videos):
        await callback.answer(
            "Pilihan sudah tidak tersedia.",
            show_alert=True,
        )
        return

    await callback.answer()

    if callback.from_user:
        RENAME_CACHE[callback.from_user.id] = {
            "tweet_id": tweet_id,
            "index": index,
        }

    await callback.message.edit_text(
        "✏️ Masukkan nama baru untuk video.\n\n"
        "Contoh: video_x"
    )


async def handle_rename(message: Message):
    if not message.from_user:
        return

    user_id = message.from_user.id

    data = RENAME_CACHE.pop(user_id, None)

    if not data:
        return

    name = (message.text or "").strip()

    if not name:
        await message.reply(
            "❌ Nama tidak boleh kosong."
        )
        return

    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = name.strip(" .")

    if not name:
        await message.reply(
            "❌ Nama tidak valid."
        )
        return

    progress = await message.reply(
        "⬇️ Menyiapkan download..."
    )

    await process_video(
        progress,
        data["tweet_id"],
        data["index"],
        name,
    )


async def process_video(
    progress: Message,
    tweet_id: str,
    index: int,
    custom_name: str | None,
):
    videos = VIDEO_CACHE.get(tweet_id)

    if not videos or index < 0 or index >= len(videos):
        await update_progress(
            progress,
            "❌ Video sudah tidak tersedia."
        )
        return

    video = videos[index]

    width = video.get("width")
    height = video.get("height")
    size = format_size(video.get("size"))

    if custom_name:
        filename = f"{custom_name}.mp4"
        caption = custom_name
    else:
        filename = f"x_{tweet_id}_{width}x{height}.mp4"
        caption = f"X video • {width}x{height}"

    MAX_SPLIT_SIZE = int(1.95 * 1024 * 1024 * 1024)
    file_path = None
    split_parts = []

    await update_progress(
        progress,
        f"⬇️ Download {width}x{height}...\n"
        f"Size: {size}\n"
        f"Progress: 0%"
    )

    last_download_update = 0
    download_started = asyncio.get_running_loop().time()

    async def download_progress(
        current: int,
        total: int | None,
    ):
        nonlocal last_download_update

        now = asyncio.get_running_loop().time()

        if now - last_download_update < 10:
            return

        last_download_update = now

        elapsed = max(now - download_started, 0.001)
        speed = current / elapsed

        eta = "--:--"

        if total and speed > 0:
            eta = format_eta((total - current) / speed)

        await update_progress(
            progress,
            f"⬇️ Download {width}x{height}...\n\n"
            f"Size: {size}\n\n"
            f"Progress:\n{format_progress(current, total)}\n\n"
            f"Speed:\n{format_speed(speed)}\n\n"
            f"ETA:\n{eta}",
        )

    try:
        print(f"VIDEO URL: {video['url']}")

        file_path = await download_url(
            video["url"],
            filename,
            progress_callback=download_progress,
        )

        actual_size = file_path.stat().st_size

        if actual_size > MAX_SPLIT_SIZE:
            await update_progress(
                progress,
                "✂️ Video lebih besar dari 1.95 GiB.\n"
                "Membagi video menjadi beberapa bagian...",
            )

            split_dir = file_path.parent / f"{file_path.stem}_parts"

            split_parts = split_video(
                file_path,
                split_dir,
                MAX_SPLIT_SIZE,
            )

            upload_files = split_parts
        else:
            upload_files = [file_path]

        total_parts = len(upload_files)

        for part_index, upload_file in enumerate(upload_files, start=1):
            if total_parts > 1:
                part_label = f" Part {part_index}/{total_parts}"
                upload_caption = f"{caption} • Part {part_index}/{total_parts}"
            else:
                part_label = ""
                upload_caption = caption

            await update_progress(
                progress,
                f"📋 Membaca metadata video{part_label}...",
            )

            meta = probe_video(upload_file)

            print(
                f"VIDEO META{part_label}: "
                f"duration={meta['duration']}s, "
                f"width={meta['width']}, "
                f"height={meta['height']}"
            )

            await update_progress(
                progress,
                f"📤 Upload{part_label} {width}x{height}...\n"
                f"Progress: 0%",
            )

            last_upload_update = 0
            upload_started = asyncio.get_running_loop().time()

            async def upload_progress(
                current: int,
                total: int,
            ):
                nonlocal last_upload_update

                now = asyncio.get_running_loop().time()

                if now - last_upload_update < 1:
                    return

                last_upload_update = now

                elapsed = max(now - upload_started, 0.001)
                speed = current / elapsed

                if total and total > 0:
                    percent = current * 100 / total
                    eta = (
                        format_eta((total - current) / speed)
                        if speed > 0
                        else "--:--"
                    )

                    text = (
                        f"📤 Upload{part_label} {width}x{height}...\n\n"
                        f"Progress:\n{percent:.1f}%\n\n"
                        f"Speed:\n{format_speed(speed)}\n\n"
                        f"ETA:\n{eta}"
                    )
                else:
                    text = (
                        f"📤 Upload{part_label} {width}x{height}...\n\n"
                        f"Progress:\n"
                        f"{current / (1024 * 1024):.2f} MB"
                    )

                await update_progress(
                    progress,
                    text,
                )

            await send_video(
                "@Sprdownloader_bot",
                str(upload_file),
                caption=upload_caption,
                video_meta=meta,
                progress_callback=upload_progress,
            )

        await progress.delete()

    except Exception as e:
        await update_progress(
            progress,
            f"❌ Gagal download/kirim video.\n\n"
            f"Error: {e}",
        )

    finally:
        if file_path is not None:
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

        for part in split_parts:
            try:
                part.unlink(missing_ok=True)
            except Exception:
                pass

        if split_parts:
            try:
                thumbnail = split_parts[0].with_suffix(".jpg")
                thumbnail.unlink(missing_ok=True)
            except Exception:
                pass

            try:
                split_parts[0].parent.rmdir()
            except Exception:
                pass
