import json
import subprocess
from pathlib import Path


def probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)

    video = next(
        s for s in data["streams"]
        if s["codec_type"] == "video"
    )

    return {
        "duration": int(float(data["format"]["duration"])),
        "width": video["width"],
        "height": video["height"],
    }
