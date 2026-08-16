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
from core.telegram import send_video
from sources.x import get_x_videos
from utils.downloader import download_url
from utils.probe import probe_video


router = Router()

URL_PATTERN = re.compile(r"https?://\S+")

VIDEO_CACHE: dict[str, list[dict]] = {}
RENAME_CACHE: dict[int, dict] = {}


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

    file_path = None

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
        file_path = await download_url(
            video["url"],
            filename,
            progress_callback=download_progress,
        )

        await update_progress(
            progress,
            "📋 Membaca metadata video...",
        )

        meta = probe_video(file_path)

        print(
            f"VIDEO META: "
            f"duration={meta['duration']}s, "
            f"width={meta['width']}, "
            f"height={meta['height']}"
        )

        await update_progress(
            progress,
            f"📤 Upload {width}x{height}...\n"
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
                eta = format_eta((total - current) / speed) if speed > 0 else "--:--"

                text = (
                    f"📤 Upload {width}x{height}...\n\n"
                    f"Progress:\n{percent:.1f}%\n\n"
                    f"Speed:\n{format_speed(speed)}\n\n"
                    f"ETA:\n{eta}"
                )
            else:
                text = (
                    f"📤 Upload {width}x{height}...\n\n"
                    f"Progress:\n{current / (1024 * 1024):.2f} MB"
                )

            await update_progress(
                progress,
                text,
            )

        await send_video(
            "@Sprdownloader_bot",
            str(file_path),
            caption=caption,
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

