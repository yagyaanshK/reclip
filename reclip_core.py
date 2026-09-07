import glob
import ipaddress
import json
import math
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import imageio_ffmpeg


class ReClipError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def get_yt_dlp_command():
    command = (
        [sys.executable, "--yt-dlp-worker"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "yt_dlp"]
    )
    return command + ["--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe()]


def validate_source_url(value):
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Source must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("Source URLs cannot contain credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Local network URLs are not supported")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("Local network URLs are not supported")
    return text


def parse_clip_time(value):
    """Parse SS, MM:SS, or HH:MM:SS timestamps with optional decimals."""
    if value is None:
        raise ValueError("Clip start and end times are required")

    text = str(value).strip()
    if not text:
        raise ValueError("Clip start and end times are required")

    parts = text.split(":")
    if len(parts) > 3 or any(not part for part in parts):
        raise ValueError("Use SS, MM:SS, or HH:MM:SS")
    if any(not part.replace(".", "", 1).isdigit() for part in parts):
        raise ValueError("Use SS, MM:SS, or HH:MM:SS")

    numbers = [float(part) for part in parts]
    if any(not math.isfinite(number) or number < 0 for number in numbers):
        raise ValueError("Clip times cannot be negative")
    if len(parts) >= 2 and numbers[-1] >= 60:
        raise ValueError("Seconds must be less than 60")
    if len(parts) == 3 and numbers[-2] >= 60:
        raise ValueError("Minutes must be less than 60")

    total = 0.0
    for number in numbers:
        total = total * 60 + number
    return total


def validate_clip_range(start_value, end_value, duration=None):
    start_missing = start_value is None or str(start_value).strip() == ""
    end_missing = end_value is None or str(end_value).strip() == ""
    if start_missing and end_missing:
        return None, None
    if start_missing or end_missing:
        raise ValueError("Enter both clip start and end times")

    start = parse_clip_time(start_value)
    end = parse_clip_time(end_value)
    if end <= start:
        raise ValueError("Clip end must be after clip start")

    if duration not in (None, ""):
        try:
            source_duration = float(duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid source duration") from exc
        if not math.isfinite(source_duration):
            raise ValueError("Invalid source duration")
        if source_duration > 0 and end > source_duration + 0.001:
            raise ValueError("Clip end is beyond the source duration")
    return start, end


def format_section_time(seconds):
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def format_filename_time(seconds):
    total_milliseconds = round(seconds * 1000)
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, whole_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}-{minutes:02d}-{whole_seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}-{whole_seconds:02d}.{milliseconds:03d}"


def build_download_command(
    out_template,
    url,
    format_choice,
    format_id=None,
    audio_codec="mp3",
    video_codec="mp4",
    clip_start=None,
    clip_end=None,
    base_command=None,
):
    command = list(base_command or get_yt_dlp_command())
    command += ["--no-playlist", "-o", os.fspath(out_template)]

    if format_choice == "audio":
        if format_id:
            command += ["-f", format_id]
        if audio_codec == "best":
            command += ["-x"]
        else:
            command += ["-x", "--audio-format", audio_codec]
    elif format_id:
        command += ["-f", f"{format_id}+bestaudio/best", "--merge-output-format", video_codec]
    else:
        command += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", video_codec]

    if clip_start is not None and clip_end is not None:
        section = f"*{format_section_time(clip_start)}-{format_section_time(clip_end)}"
        command += ["--download-sections", section, "--force-keyframes-at-cuts"]
    command.append(url)
    return command


def extractor_error(output, fallback="yt-dlp failed"):
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("ERROR:"):
            return line.removeprefix("ERROR:").strip()
    return lines[-1] if lines else fallback


def _run(command, timeout):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ReClipError("timeout", f"Operation timed out after {timeout} seconds") from exc
    if result.returncode != 0:
        raise ReClipError("extractor_error", extractor_error(result.stderr))
    return result


def _normalized_formats(info):
    video = {}
    audio = {}
    for item in info.get("formats") or []:
        if item.get("vcodec") == "none":
            abr = item.get("abr")
            if abr:
                rounded = int(abr)
                current = audio.get(rounded)
                if current is None or (item.get("asr") or 0) > (current.get("asr") or 0):
                    audio[rounded] = item
            continue
        height = item.get("height")
        if height:
            current = video.get(height)
            if current is None or (item.get("tbr") or 0) > (current.get("tbr") or 0):
                video[height] = item

    return {
        "video": [
            {"format_id": item["format_id"], "label": f"{height}p", "height": height}
            for height, item in sorted(video.items(), reverse=True)
        ],
        "audio": [
            {"format_id": item["format_id"], "label": f"{abr}kbps", "abr": abr}
            for abr, item in sorted(audio.items(), reverse=True)
        ],
    }


def inspect_media(url, timeout=60, base_command=None):
    source_url = validate_source_url(url)
    command = list(base_command or get_yt_dlp_command())
    result = _run(command + ["--no-playlist", "--dump-single-json", source_url], timeout)
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReClipError("invalid_extractor_response", "yt-dlp returned invalid metadata") from exc

    artist = info.get("artist")
    if isinstance(artist, list):
        artist = ", ".join(str(value) for value in artist)
    formats = _normalized_formats(info)
    return {
        "id": str(info.get("id") or ""),
        "title": str(info.get("title") or ""),
        "uploader": str(info.get("uploader") or ""),
        "artist": str(artist or ""),
        "track": str(info.get("track") or ""),
        "duration": info.get("duration"),
        "webpage_url": str(info.get("webpage_url") or source_url),
        "thumbnail": str(info.get("thumbnail") or ""),
        "formats": formats,
    }


def quality_selector(quality, media_format):
    if not quality or quality == "best":
        return None
    text = str(quality).strip().lower()
    suffix = "p" if media_format == "mp4" else "k"
    if text.endswith(suffix):
        text = text[:-1]
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("Quality must be 'best', a video height such as 1080p, or audio bitrate such as 192k")
    value = int(text)
    if media_format == "mp4":
        return f"bestvideo[height<={value}]"
    return f"bestaudio[abr<={value}]"


def download_media(
    url,
    output_directory="downloads",
    media_format="mp4",
    quality="best",
    clip_start=None,
    clip_end=None,
    timeout=1800,
    base_command=None,
):
    source_url = validate_source_url(url)
    if media_format not in {"mp3", "mp4"}:
        raise ValueError("Format must be mp3 or mp4")
    start, end = validate_clip_range(clip_start, clip_end)
    selector = quality_selector(quality, media_format)

    output_dir = Path(output_directory).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    operation_id = uuid.uuid4().hex[:12]
    prefix = f".reclip-{operation_id}-"
    template = output_dir / f"{prefix}%(title).180B [%(id)s].%(ext)s"
    command = build_download_command(
        template,
        source_url,
        "audio" if media_format == "mp3" else "video",
        selector,
        audio_codec="mp3",
        video_codec="mp4",
        clip_start=start,
        clip_end=end,
        base_command=base_command,
    )
    _run(command, timeout)

    candidates = [Path(path) for path in glob.glob(str(output_dir / f"{prefix}*"))]
    if not candidates:
        raise ReClipError("missing_output", "Download completed but no output file was found")
    output_path = max(candidates, key=lambda path: path.stat().st_size)
    final_name = output_path.stem.removeprefix(prefix) or f"reclip-{operation_id}"
    if start is not None and end is not None:
        final_name += f"-clip-{format_filename_time(start)}-to-{format_filename_time(end)}"
    destination = output_dir / f"{final_name}{output_path.suffix}"
    collision = 1
    while destination.exists() and destination != output_path:
        destination = output_dir / f"{final_name}-{collision}{output_path.suffix}"
        collision += 1
    output_path.replace(destination)
    for candidate in candidates:
        if candidate.exists() and candidate != destination:
            candidate.unlink()

    return {
        "path": str(destination),
        "filename": destination.name,
        "size_bytes": destination.stat().st_size,
        "media_format": media_format,
        "clip": None if start is None else {"start_seconds": start, "end_seconds": end},
        "source_url": source_url,
    }


def list_supported_sites(timeout=60, base_command=None):
    command = list(base_command or get_yt_dlp_command())
    result = _run(command + ["--list-extractors"], timeout)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
