"""
yt-dlp wrapper for the ReClip mobile (BeeWare) app.

Adapted from mobile/android/python_reference/reclip_runner.py. Differences
from the Kotlin/Chaquopy reference:

- progress_callback is a plain Python callable (no JVM bridge needed —
  BeeWare's Android backend uses Chaquopy under the hood, but Toga code
  is pure Python all the way down)
- On Android, ffmpeg is NOT bundled by default, so we prefer single-file
  formats that don't require muxing. Video+audio merging is documented as
  a known limitation in mobile/beeware/README.md.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

from yt_dlp import YoutubeDL


ProgressCallback = Callable[[int], None]


def _sanitize(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    return cleaned[:max_len].strip()


def fetch_info(url: str) -> dict:
    """Fetch metadata for a single URL. No download."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return {
        "title": info.get("title", ""),
        "thumbnail": info.get("thumbnail", ""),
        "duration": info.get("duration"),
        "uploader": info.get("uploader", ""),
    }


def download(
    url: str,
    output_dir: str,
    audio_only: bool,
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    """
    Download `url` into `output_dir`.

    audio_only=True  -> best audio stream, post-processed to MP3
    audio_only=False -> best pre-muxed MP4 (no ffmpeg merging on Android MVP)

    Returns the absolute path of the downloaded file.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_template = os.path.join(output_dir, "%(title).80s.%(ext)s")

    def hook(d: dict) -> None:
        if progress_callback is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                try:
                    progress_callback(int(done * 100 / total))
                except Exception:
                    pass
        elif d.get("status") == "finished":
            try:
                progress_callback(100)
            except Exception:
                pass

    opts: dict = {
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }

    if audio_only:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    else:
        # Prefer single-file MP4 to avoid the ffmpeg merge step (no ffmpeg
        # binary on Android in this MVP build).
        opts["format"] = "best[ext=mp4]/best"

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        final_path = ydl.prepare_filename(info)
        if audio_only:
            base, _ = os.path.splitext(final_path)
            mp3_path = f"{base}.mp3"
            if os.path.exists(mp3_path):
                final_path = mp3_path
    return final_path
