"""
Python-side wrapper around yt-dlp for the ReClip Android app.

Called from Kotlin via Chaquopy. We use yt-dlp's Python API (not the CLI)
because subprocess execution is restricted on Android.
"""

import os
import re
from yt_dlp import YoutubeDL


def _sanitize(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    return cleaned[:max_len].strip()


def fetch_info(url: str) -> dict:
    """Fetch video metadata: title, thumbnail, available formats."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    # Build deduplicated quality list — highest tbr per resolution.
    best_by_height = {}
    audio_by_abr = {}

    for f in info.get("formats", []) or []:
        if f.get("vcodec") == "none":
            abr = f.get("abr")
            if abr:
                abr = int(abr)
                if abr not in audio_by_abr or (f.get("asr", 0) > audio_by_abr[abr].get("asr", 0)):
                    audio_by_abr[abr] = f
            continue

        h = f.get("height")
        if h and f.get("vcodec", "none") != "none":
            tbr = f.get("tbr") or 0
            if h not in best_by_height or tbr > (best_by_height[h].get("tbr") or 0):
                best_by_height[h] = f

    formats = [
        {"id": f["format_id"], "label": f"{h}p", "height": h}
        for h, f in sorted(best_by_height.items(), key=lambda kv: kv[0], reverse=True)
    ]
    audio_formats = [
        {"id": f["format_id"], "label": f"{abr}kbps", "abr": abr}
        for abr, f in sorted(audio_by_abr.items(), key=lambda kv: kv[0], reverse=True)
    ]

    art = info.get("artist")
    artist_str = ", ".join(art) if isinstance(art, list) else str(art or "").strip()

    return {
        "title": info.get("title", ""),
        "thumbnail": info.get("thumbnail", ""),
        "duration": info.get("duration"),
        "uploader": info.get("uploader", ""),
        "artist": artist_str,
        "track": str(info.get("track") or "").strip(),
        "formats": formats,
        "audioFormats": audio_formats,
    }


def download(url, output_dir, format_choice, format_id, audio_codec, video_codec, progress_callback):
    """
    Download a video/audio file to `output_dir`.

    progress_callback: a Java/Kotlin object with a `call(int)` method invoked with percent.
    Returns the absolute file path of the downloaded file.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_template = os.path.join(output_dir, "%(title).80s.%(ext)s")

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                try:
                    progress_callback.call(int(done * 100 / total))
                except Exception:
                    pass
        elif d.get("status") == "finished":
            try:
                progress_callback.call(100)
            except Exception:
                pass

    opts = {
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }

    if format_choice == "audio":
        if format_id:
            opts["format"] = format_id
        codec = audio_codec if audio_codec != "best" else None
        postprocs = [{"key": "FFmpegExtractAudio"}]
        if codec:
            postprocs[0]["preferredcodec"] = codec
        opts["postprocessors"] = postprocs
    elif format_id:
        opts["format"] = f"{format_id}+bestaudio/best"
        opts["merge_output_format"] = video_codec
    else:
        opts["format"] = "bestvideo+bestaudio/best"
        opts["merge_output_format"] = video_codec

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        final_path = ydl.prepare_filename(info)

        # Post-processing may have changed the extension (e.g., m4a -> mp3).
        if format_choice == "audio" and audio_codec != "best":
            base, _ = os.path.splitext(final_path)
            candidate = f"{base}.{audio_codec}"
            if os.path.exists(candidate):
                final_path = candidate

    return final_path
