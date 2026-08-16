import re
from typing import Any

import aiohttp


FXTWITTER_API = "https://api.fxtwitter.com/2/status"


def extract_tweet_id(url: str) -> str | None:
    match = re.search(
        r"(?:x\.com|twitter\.com)/(?:[^/]+)/(?:status|statuses)/(\d+)",
        url,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def is_x_url(url: str) -> bool:
    return extract_tweet_id(url) is not None


async def fetch_fxtwitter(tweet_id: str) -> dict[str, Any]:
    api_url = f"{FXTWITTER_API}/{tweet_id}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(api_url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()


def extract_mp4_variants(data: dict[str, Any]) -> list[dict[str, Any]]:
    status = data.get("status") or {}
    media = status.get("media") or {}
    videos = media.get("videos") or []

    variants: list[dict[str, Any]] = []

    for video in videos:
        formats = video.get("formats") or []

        for fmt in formats:
            url = fmt.get("url")
            container = str(fmt.get("container") or "").lower()

            if not url:
                continue

            if container != "mp4":
                continue

            # Example:
            # /vid/avc1/854x480/file.mp4
            resolution_match = re.search(r"/(\d+)x(\d+)/", url)

            if resolution_match:
                width = int(resolution_match.group(1))
                height = int(resolution_match.group(2))
            else:
                width = video.get("width")
                height = video.get("height")

            variants.append(
                {
                    "url": url,
                    "width": width,
                    "height": height,
                    "bitrate": fmt.get("bitrate"),
                    "format": "mp4",
                    "codec": fmt.get("codec"),
                    "duration": video.get("duration"),
                }
            )

    # Remove duplicate URLs.
    unique = {}
    for variant in variants:
        unique[variant["url"]] = variant

    variants = list(unique.values())

    # Highest resolution first.
    variants.sort(
        key=lambda v: (
            int(v.get("height") or 0),
            int(v.get("width") or 0),
            int(v.get("bitrate") or 0),
        ),
        reverse=True,
    )

    return variants


async def get_x_videos(url: str) -> dict[str, Any]:
    tweet_id = extract_tweet_id(url)

    if not tweet_id:
        return {
            "tweet_id": None,
            "has_video": False,
            "videos": [],
            "error": "Invalid X/Twitter URL",
        }

    try:
        data = await fetch_fxtwitter(tweet_id)

        videos = extract_mp4_variants(data)

        return {
            "tweet_id": tweet_id,
            "has_video": bool(videos),
            "videos": videos,
            "error": None,
        }

    except aiohttp.ClientResponseError as e:
        return {
            "tweet_id": tweet_id,
            "has_video": False,
            "videos": [],
            "error": f"FxTwitter HTTP {e.status}",
        }

    except Exception as e:
        return {
            "tweet_id": tweet_id,
            "has_video": False,
            "videos": [],
            "error": str(e),
        }


async def extract_x_video(url: str) -> dict[str, Any]:
    return await get_x_videos(url)
