import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _upload_sync(path: str, title: str) -> str:
    client_id = os.getenv("YT_CLIENT_ID")
    client_secret = os.getenv("YT_CLIENT_SECRET")
    refresh_token = os.getenv("YT_REFRESH_TOKEN")

    if not all((client_id, client_secret, refresh_token)):
        raise RuntimeError(
            "Kredensial YouTube belum lengkap di .env "
            "(YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN)."
        )

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    media = MediaFileUpload(
        path,
        mimetype="video/*",
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],
                "description": "Uploaded via Telegram Downloader Bot.",
            },
            "status": {
                "privacyStatus": "private",
            },
        },
        media_body=media,
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube tidak mengembalikan video ID.")

    return f"https://www.youtube.com/watch?v={video_id}"


async def upload_video(path: Path, title: str) -> str:
    return await asyncio.to_thread(_upload_sync, str(path), title)
