import asyncio
from pathlib import Path
from urllib.parse import urlparse


DOWNLOAD_DIR = Path("/tmp/telegram_downloader")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def extract_info(url: str):
    process = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "--js-runtimes",
        "node",
        "--dump-single-json",
        "--no-playlist",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(stderr.decode().strip())

    import json

    return json.loads(stdout.decode())


async def download_url(
    url: str,
    filename: str,
    progress_callback=None,
) -> Path:
    """
    Download a direct HTTP/HTTPS file to DOWNLOAD_DIR.

    If progress_callback is provided, it is called as:

        await progress_callback(downloaded_bytes, total_bytes)

    total_bytes can be None when the server does not provide
    Content-Length.
    """
    import aiohttp

    output = DOWNLOAD_DIR / filename

    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=30,
        sock_read=300,
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            url,
            headers=headers,
            allow_redirects=True,
        ) as response:

            response.raise_for_status()

            content_length = response.headers.get("Content-Length")

            try:
                total_bytes = int(content_length) if content_length else None
            except ValueError:
                total_bytes = None

            downloaded_bytes = 0
            callback_bytes = 0
            callback_threshold = 5 * 1024 * 1024

            with output.open("wb") as f:
                async for chunk in response.content.iter_chunked(
                    1024 * 1024
                ):
                    f.write(chunk)
                    downloaded_bytes += len(chunk)
                    callback_bytes += len(chunk)

                    if (
                        progress_callback is not None
                        and callback_bytes >= callback_threshold
                    ):
                        await progress_callback(
                            downloaded_bytes,
                            total_bytes,
                        )
                        callback_bytes = 0

            if progress_callback is not None and callback_bytes > 0:
                await progress_callback(
                    downloaded_bytes,
                    total_bytes,
                )

    return output
