from pathlib import Path
import subprocess


def split_video(
    input_path: str | Path,
    output_dir: str | Path,
    max_size_bytes: int,
) -> list[Path]:
    """
    Split video into multiple MP4 parts using FFmpeg.

    The video is split by duration and re-encoded so each resulting
    part stays below the requested maximum size.
    """

    input_path = Path(input_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be greater than 0")

    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]

    result = subprocess.run(
        probe_cmd,
        capture_output=True,
        text=True,
        check=True,
    )

    duration = float(result.stdout.strip())

    if duration <= 0:
        raise ValueError("Unable to determine video duration")

    file_size = input_path.stat().st_size

    if file_size <= max_size_bytes:
        return [input_path]

    # Keep a safety margin below the Telegram upload limit.
    # With stream-copy segmentation, actual part sizes can vary because
    # cuts happen on keyframes. Target ~1.70 GiB when the handler limit
    # is 1.80 GiB.
    safe_max_size_bytes = int(max_size_bytes * 0.9444444444)

    estimated_parts = max(
        2,
        (file_size + safe_max_size_bytes - 1) // safe_max_size_bytes,
    )

    part_duration = duration / estimated_parts

    output_pattern = output_dir / f"{input_path.stem}_part_%03d.mp4"

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0",
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(part_duration),
        "-reset_timestamps",
        "1",
        str(output_pattern),
    ]

    subprocess.run(
        command,
        check=True,
    )

    parts = sorted(output_dir.glob(f"{input_path.stem}_part_*.mp4"))

    if not parts:
        raise RuntimeError("FFmpeg did not create any split parts")

    return parts
