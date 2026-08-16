import subprocess
from pathlib import Path


def create_thumbnail(video_path: str | Path) -> Path:
    video_path = Path(video_path)
    thumb_path = video_path.with_suffix(".jpg")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "3",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(thumb_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    return thumb_path
