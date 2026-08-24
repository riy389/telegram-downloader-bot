import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from telethon.tl.types import DocumentAttributeVideo

from core.telegram import (
    connect_telegram_user,
    _parallel_download_telegram_document,
    send_video,
)

from utils.probe import probe_video


DOWNLOAD_DIR = Path("/tmp/telegram_downloader_step34")

TELEGRAM_MESSAGE_URL_RE = re.compile(
    r"^https?://t\.me/"
    r"(?P<channel>[A-Za-z0-9_]+)/"
    r"(?P<message_id>\d+)/?$"
)

TELEGRAM_PRIVATE_MESSAGE_URL_RE = re.compile(
    r"^https?://t\.me/c/"
    r"(?P<internal_id>\d+)/"
    r"(?P<message_id>\d+)/?$"
)


def parse_source_url(url):
    url = url.strip()

    private_match = TELEGRAM_PRIVATE_MESSAGE_URL_RE.match(
        url
    )

    if private_match:
        internal_id = int(
            private_match.group("internal_id")
        )

        return (
            int(f"-100{internal_id}"),
            int(private_match.group("message_id")),
        )

    match = TELEGRAM_MESSAGE_URL_RE.match(url)

    if not match:
        raise ValueError(
            f"Source URL tidak valid: {url}"
        )

    return (
        match.group("channel"),
        int(match.group("message_id")),
    )


def get_video_filename(message):
    document = message.document

    if document is None:
        return f"telegram_{message.id}"

    for attribute in document.attributes:
        if hasattr(attribute, "file_name") and attribute.file_name:
            return attribute.file_name

    return f"telegram_{message.id}"


def is_video_message(message):
    if not message or not message.document:
        return False

    for attribute in message.document.attributes:
        if isinstance(attribute, DocumentAttributeVideo):
            return True

    mime_type = getattr(
        message.document,
        "mime_type",
        "",
    ) or ""

    return mime_type.startswith("video/")


def normalize_keyword(text):
    return re.sub(
        r"[^a-z0-9]+",
        "",
        text.lower(),
    )


def matches_keyword(message, keyword):
    if not keyword:
        return True

    normalized_keyword = normalize_keyword(
        keyword
    )

    filename = normalize_keyword(
        get_video_filename(message)
    )

    caption = normalize_keyword(
        message.message or ""
    )

    return (
        normalized_keyword in filename
        or normalized_keyword in caption
    )


async def download_message(
    client,
    entity,
    message,
):
    document = message.document

    file_size = int(document.size)

    filename = get_video_filename(message)

    target_path = DOWNLOAD_DIR / filename

    if target_path.exists():
        target_path.unlink()

    print()
    print(
        f"⏬ Download message {message.id}"
    )
    print(
        f"File      : {filename}"
    )
    print(
        f"Size      : "
        f"{file_size / (1024 ** 2):.2f} MB"
    )

    async def progress(current, total):
        percent = (
            current / total * 100
            if total
            else 0
        )

        print(
            f"\rProgress  : {percent:6.2f}% "
            f"({current / (1024 ** 2):.2f} / "
            f"{total / (1024 ** 2):.2f} MB)",
            end="",
            flush=True,
        )

    await _parallel_download_telegram_document(
        client=client,
        document=document,
        target_path=target_path,
        chat_id=entity,
        message_id=message.id,
        progress_callback=progress,
    )

    print()
    print("✅ Download selesai.")

    return target_path


async def upload_file(
    target,
    file_path,
    caption=None,
):
    print()
    print(
        f"⬆️ Upload ke {target}"
    )
    print(
        f"File      : {file_path.name}"
    )

    print("🔎 Membaca metadata video...")

    video_meta = probe_video(
        file_path
    )

    print(
        f"Duration  : {video_meta['duration']} sec"
    )
    print(
        f"Resolution: "
        f"{video_meta['width']}x"
        f"{video_meta['height']}"
    )

    async def progress(current, total):
        percent = (
            current / total * 100
            if total
            else 0
        )

        print(
            f"\rUpload    : {percent:6.2f}% "
            f"({current / (1024 ** 2):.2f} / "
            f"{total / (1024 ** 2):.2f} MB)",
            end="",
            flush=True,
        )

    await send_video(
        chat_id=target,
        file_path=str(file_path),
        caption=caption,
        video_meta=video_meta,
        progress_callback=progress,
    )

    print()
    print("✅ Upload selesai.")


async def process_message(
    client,
    source_entity,
    message,
    target,
):
    file_path = None

    try:
        if not is_video_message(message):
            print(
                f"⏭️ Message {message.id}: "
                "bukan video, dilewati."
            )
            return

        file_path = await download_message(
            client,
            source_entity,
            message,
        )

        await upload_file(
            target,
            file_path,
            caption=message.message or None,
        )

        file_path.unlink(
            missing_ok=True
        )

        print(
            f"🗑️ File VM dihapus: "
            f"{file_path.name}"
        )

    except Exception as exc:
        print(
            f"\n❌ Message {message.id} gagal: "
            f"{type(exc).__name__}: {exc}"
        )

        if file_path is not None:
            print(
                f"⚠️ File dipertahankan untuk retry: "
                f"{file_path}"
            )


async def run_single(
    client,
    source_url,
    target,
    keyword,
):
    channel, message_id = parse_source_url(
        source_url
    )

    print(
        f"Source channel: {channel}"
    )
    print(
        f"Message ID    : {message_id}"
    )

    source_entity = await client.get_entity(
        channel
    )

    message = await client.get_messages(
        source_entity,
        ids=message_id,
    )

    if not message:
        raise RuntimeError(
            f"Message {message_id} tidak ditemukan."
        )

    if not matches_keyword(
        message,
        keyword,
    ):
        print(
            f"⏭️ Message {message.id}: "
            f"tidak cocok keyword '{keyword}'."
        )
        return

    await process_message(
        client,
        source_entity,
        message,
        target,
    )


async def run_range(
    client,
    from_url,
    to_url,
    target,
    keyword,
):
    from_channel, from_id = parse_source_url(
        from_url
    )

    to_channel, to_id = parse_source_url(
        to_url
    )

    if str(from_channel).lower() != str(to_channel).lower():
        raise ValueError(
            "--from dan --to harus berasal "
            "dari channel yang sama."
        )

    if from_id > to_id:
        raise ValueError(
            "--from message ID harus <= --to."
        )

    print(
        f"Source channel: {from_channel}"
    )
    print(
        f"Range         : {from_id} → {to_id}"
    )

    if keyword:
        print(
            f"Keyword       : {keyword}"
        )

    source_entity = await client.get_entity(
        from_channel
    )

    print()
    print("🔎 Scanning messages...")

    messages = await client.get_messages(
        source_entity,
        ids=list(
            range(
                from_id,
                to_id + 1,
            )
        ),
    )

    candidates = []

    for message in messages:
        if not message:
            continue

        if not is_video_message(message):
            continue

        if not matches_keyword(
            message,
            keyword,
        ):
            continue

        candidates.append(message)

    print(
        f"✅ Kandidat video: "
        f"{len(candidates)}"
    )

    if not candidates:
        return

    print()

    for message in sorted(
        candidates,
        key=lambda item: item.id,
    ):
        print(
            f"  {message.id}: "
            f"{get_video_filename(message)}"
        )

    print()

    sorted_candidates = sorted(
        candidates,
        key=lambda item: item.id,
    )

    for index, message in enumerate(
        sorted_candidates
    ):
        await process_message(
            client,
            source_entity,
            message,
            target,
        )

        if index < len(sorted_candidates) - 1:
            print()
            print(
                "⏳ Jeda 5 detik sebelum "
                "video berikutnya..."
            )
            await asyncio.sleep(5)


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Download Telegram media via MTProto "
            "and upload directly to another channel."
        )
    )

    group = parser.add_mutually_exclusive_group(
        required=True
    )

    group.add_argument(
        "url",
        nargs="?",
        help="Single Telegram message URL",
    )

    group.add_argument(
        "--from",
        dest="from_url",
        help="First Telegram message URL",
    )

    parser.add_argument(
        "--to",
        dest="to_url",
        help="Last Telegram message URL",
    )

    parser.add_argument(
        "--keyword",
        help="Filter berdasarkan nama file/caption",
    )

    parser.add_argument(
        "--target",
        required=True,
        help="Destination Telegram channel ID",
    )

    return parser


async def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.from_url and not args.to_url:
        parser.error(
            "--from harus disertai --to"
        )

    if args.url and args.to_url:
        parser.error(
            "--to hanya digunakan bersama --from"
        )

    target = args.target

    try:
        target = int(target)
    except ValueError:
        pass

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    client = await connect_telegram_user()

    print("Telethon: connected")
    print(
        f"Target  : {target}"
    )

    if args.url:
        await run_single(
            client,
            args.url,
            target,
            args.keyword,
        )
    else:
        await run_range(
            client,
            args.from_url,
            args.to_url,
            target,
            args.keyword,
        )


if __name__ == "__main__":
    asyncio.run(main())
