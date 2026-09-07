import os
import sys
import uuid
import glob
import json
import math
import re
import ipaddress
import socket
import subprocess
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

YT_DLP_CMD = [
    sys.executable,
    "-m",
    "yt_dlp",
    "--verbose",
    "--force-ipv4",
    "--impersonate",
    "chrome",
    "--socket-timeout",
    "20",
    "--retries",
    "2",
    "--fragment-retries",
    "2",
    "--extractor-retries",
    "2",
    "--js-runtimes",
    "deno",
    "--extractor-args",
    "youtube:player_client=android_vr;player_skip=webpage,configs",
]

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("RECLIP_MAX_REQUEST_BYTES", 16 * 1024 * 1024))
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}
jobs_lock = threading.Lock()
rate_events = defaultdict(deque)
rate_lock = threading.Lock()
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
JOB_TTL_SECONDS = int(os.environ.get("RECLIP_JOB_TTL_SECONDS", "3600"))
MAX_ACTIVE_JOBS = int(os.environ.get("RECLIP_MAX_ACTIVE_JOBS", "4"))
MAX_ACTIVE_JOBS_PER_CLIENT = int(os.environ.get("RECLIP_MAX_ACTIVE_JOBS_PER_CLIENT", "2"))
MAX_DOWNLOAD_SIZE = os.environ.get("RECLIP_MAX_DOWNLOAD_SIZE", "1G")


def _client_id():
    return request.remote_addr or "unknown"


def _validate_public_url(value):
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Source must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("Source URLs cannot contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Source URL contains an invalid port") from exc
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Local network URLs are not supported")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(
                    hostname,
                    port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except socket.gaierror as exc:
            raise ValueError("Source hostname could not be resolved") from exc
    else:
        addresses = {address}
    if any(not address.is_global for address in addresses):
        raise ValueError("Local network URLs are not supported")
    return text


def _rate_limited(limit, window_seconds):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            now = time.monotonic()
            key = (_client_id(), request.endpoint)
            with rate_lock:
                events = rate_events[key]
                while events and events[0] <= now - window_seconds:
                    events.popleft()
                if len(events) >= limit:
                    retry_after = max(1, math.ceil(events[0] + window_seconds - now))
                    response = jsonify({"error": "Rate limit exceeded", "retry_after": retry_after})
                    response.status_code = 429
                    response.headers["Retry-After"] = str(retry_after)
                    return response
                events.append(now)
            return function(*args, **kwargs)

        return wrapped
    return decorator


def _delete_job_files(job_id, job):
    paths = set(glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*")))
    if job.get("file"):
        paths.add(job["file"])
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def _cleanup_expired_jobs():
    now = time.time()
    expired = []
    with jobs_lock:
        for job_id, job in list(jobs.items()):
            if now - job.get("created_at", now) > JOB_TTL_SECONDS:
                expired.append((job_id, jobs.pop(job_id)))
    for job_id, job in expired:
        _delete_job_files(job_id, job)

    with rate_lock:
        for key, events in list(rate_events.items()):
            if not events or events[-1] <= time.monotonic() - 3600:
                rate_events.pop(key, None)


@app.before_request
def maintain_public_service():
    _cleanup_expired_jobs()
    if request.path in {"/api/info", "/api/download"} and request.content_length:
        if request.content_length > 16 * 1024:
            return jsonify({"error": "JSON request is too large"}), 413


def _yt_dlp_error_message(output, fallback="yt-dlp failed"):
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    lines = [ANSI_ESCAPE.sub("", line).strip() for line in (output or "").splitlines()]
    for line in reversed(lines):
        if line.startswith("ERROR:"):
            return line.removeprefix("ERROR:").strip()
    return next((line for line in reversed(lines) if line), fallback)


def _log_yt_dlp_failure(operation, output):
    """Log bounded extractor diagnostics without retaining full commands or responses."""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    diagnostic_terms = (
        "[pot]", "provider", "impersonat", "player client", "token",
        "script", "deno", "runtime",
    )
    selected = [line for line in lines if any(term in line.lower() for term in diagnostic_terms)]
    selected.extend(lines[-8:])
    lines = list(dict.fromkeys(selected))[-20:]
    sanitized = [re.sub(r"https?://\S+", "[url]", line) for line in lines]
    detail = " | ".join(sanitized) or "no extractor progress was emitted"
    print(f"yt-dlp {operation} failed: {detail}", flush=True)


def _log_yt_dlp_timeout(operation, exc):
    output = exc.stderr or exc.stdout or ""
    _log_yt_dlp_failure(f"{operation} (timeout)", output)


def _parse_clip_time(value):
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


def _validate_clip_range(start_value, end_value, duration=None):
    """Return validated clip bounds in seconds, or (None, None) when unused."""
    start_missing = start_value is None or str(start_value).strip() == ""
    end_missing = end_value is None or str(end_value).strip() == ""
    if start_missing and end_missing:
        return None, None
    if start_missing or end_missing:
        raise ValueError("Enter both clip start and end times")

    start = _parse_clip_time(start_value)
    end = _parse_clip_time(end_value)
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


def _format_section_time(seconds):
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def _format_filename_time(seconds):
    total_milliseconds = round(seconds * 1000)
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, whole_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}-{minutes:02d}-{whole_seconds:02d}.{milliseconds:03d}"
    return f"{minutes:02d}-{whole_seconds:02d}.{milliseconds:03d}"


def _build_download_command(
    out_template,
    url,
    format_choice,
    format_id,
    audio_codec="mp3",
    video_codec="mp4",
    clip_start=None,
    clip_end=None,
):
    cmd = YT_DLP_CMD + [
        "--no-playlist",
        "--max-filesize",
        MAX_DOWNLOAD_SIZE,
        "-o",
        out_template,
    ]

    if format_choice == "audio":
        if format_id:
            cmd += ["-f", format_id]
        if audio_codec == "best":
            cmd += ["-x"]
        else:
            cmd += ["-x", "--audio-format", audio_codec]
    elif format_id:
        cmd += ["-f", f"{format_id}+bestaudio/best", "--merge-output-format", video_codec]
    else:
        cmd += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", video_codec]

    if clip_start is not None and clip_end is not None:
        section = f"*{_format_section_time(clip_start)}-{_format_section_time(clip_end)}"
        cmd += ["--download-sections", section, "--force-keyframes-at-cuts"]

    cmd.append(url)
    return cmd


@app.after_request
def add_security_headers(response):
    # Required for ffmpeg.wasm on /trim — needs SharedArrayBuffer,
    # which is only available in cross-origin isolated contexts.
    # `credentialless` is the most permissive — cross-origin resources
    # (Google Fonts, unpkg) load without credentials and don't need CORP headers.
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
    response.headers.setdefault('Cross-Origin-Embedder-Policy', 'credentialless')
    return response


def run_download(
    job_id,
    url,
    format_choice,
    format_id,
    audio_codec="mp3",
    video_codec="mp4",
    clip_start=None,
    clip_end=None,
):
    job = jobs[job_id]
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    cmd = _build_download_command(
        out_template,
        url,
        format_choice,
        format_id,
        audio_codec,
        video_codec,
        clip_start,
        clip_end,
    )

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            _log_yt_dlp_failure("download", result.stderr)
            job["status"] = "error"
            job["error"] = _yt_dlp_error_message(result.stderr)
            return

        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
        if not files:
            job["status"] = "error"
            job["error"] = "Download completed but no file was found"
            return

        if format_choice == "audio":
            if audio_codec != "best":
                target = [f for f in files if f.endswith(f".{audio_codec}")]
            else:
                target = [f for f in files if not f.endswith(".mp4") and not f.endswith(".webm")]
            chosen = target[0] if target else files[0]
        else:
            target = [f for f in files if f.endswith(f".{video_codec}")]
            chosen = target[0] if target else files[0]

        for f in files:
            if f != chosen:
                try:
                    os.remove(f)
                except OSError:
                    pass

        job["status"] = "done"
        job["file"] = chosen
        ext = os.path.splitext(chosen)[1]
        
        is_audio = job.get("format_choice") == "audio"
        artist = job.get("artist", "")
        track = job.get("track", "")
        uploader = job.get("uploader", "")
        title = job.get("title", "")
        
        if is_audio and artist and track:
            raw_name = f"{artist} - {track}"
        elif uploader and title:
            raw_name = f"{uploader} - {title}"
        else:
            raw_name = title.strip()
            
        if raw_name or (clip_start is not None and clip_end is not None):
            safe_base = "".join(c for c in raw_name if c not in r'\/:*?"<>|').strip() or "download"
            clip_suffix = ""
            if clip_start is not None and clip_end is not None:
                clip_suffix = (
                    f" - clip {_format_filename_time(clip_start)}"
                    f" to {_format_filename_time(clip_end)}"
                )
            base_limit = max(1, 100 - len(clip_suffix))
            safe_name = f"{safe_base[:base_limit].strip()}{clip_suffix}"
            job["filename"] = f"{safe_name}{ext}" if safe_name else os.path.basename(chosen)
        else:
            job["filename"] = os.path.basename(chosen)
    except subprocess.TimeoutExpired as exc:
        _log_yt_dlp_timeout("download", exc)
        job["status"] = "error"
        job["error"] = "Download timed out (5 min limit)"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/robots.txt")
def robots():
    return send_file(os.path.join(app.static_folder, "robots.txt"), mimetype="text/plain")


@app.route("/llms.txt")
def llms():
    return send_file(os.path.join(app.static_folder, "llms.txt"), mimetype="text/plain")


@app.route("/llms-full.txt")
def llms_full():
    return send_file(os.path.join(app.static_folder, "llms-full.txt"), mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    return send_file(os.path.join(app.static_folder, "sitemap.xml"), mimetype="application/xml")


@app.route("/openapi.json")
def openapi_spec():
    return send_file(os.path.join(app.static_folder, "openapi.json"), mimetype="application/json")


@app.route("/api-docs")
def api_docs():
    return render_template("api-docs.html")


@app.route("/api/info", methods=["POST"])
@_rate_limited(limit=20, window_seconds=300)
def get_info():
    data = request.get_json(silent=True) or {}
    try:
        url = _validate_public_url(data.get("url"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    cmd = YT_DLP_CMD + ["--no-playlist", "-j", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            _log_yt_dlp_failure("metadata fetch", result.stderr)
            return jsonify({"error": _yt_dlp_error_message(result.stderr)}), 400

        info = json.loads(result.stdout)

        # Build quality options — keep best format per resolution
        best_by_height = {}
        audio_by_abr = {}
        for f in info.get("formats", []):
            if f.get("vcodec") == "none":
                abr = f.get("abr")
                if abr:
                    abr = int(abr)
                    if abr not in audio_by_abr or (f.get("asr", 0) > audio_by_abr[abr].get("asr", 0)):
                        audio_by_abr[abr] = f
                continue

            height = f.get("height")
            if height and f.get("vcodec", "none") != "none":
                tbr = f.get("tbr") or 0
                if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
                    best_by_height[height] = f

        formats = []
        for height, f in best_by_height.items():
            formats.append({
                "id": f["format_id"],
                "label": f"{height}p",
                "height": height,
            })
        formats.sort(key=lambda x: x["height"], reverse=True)

        audio_formats = []
        for abr, f in audio_by_abr.items():
            audio_formats.append({
                "id": f["format_id"],
                "label": f"{abr}kbps",
                "abr": abr,
            })
        audio_formats.sort(key=lambda x: x["abr"], reverse=True)

        art = info.get("artist")
        artist_str = ", ".join(art) if isinstance(art, list) else str(art or "").strip()

        return jsonify({
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "uploader": info.get("uploader", ""),
            "artist": artist_str,
            "track": str(info.get("track") or "").strip(),
            "formats": formats,
            "audioFormats": audio_formats,
        })
    except subprocess.TimeoutExpired as exc:
        _log_yt_dlp_timeout("metadata fetch", exc)
        return jsonify({"error": "Timed out fetching video info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
@_rate_limited(limit=6, window_seconds=3600)
def start_download():
    data = request.get_json(silent=True) or {}
    try:
        url = _validate_public_url(data.get("url"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    audio_codec = data.get("audio_codec", "mp3")
    video_codec = data.get("video_codec", "mp4")
    title = data.get("title", "")
    artist = data.get("artist", "")
    track = data.get("track", "")
    uploader = data.get("uploader", "")

    if format_choice not in {"video", "audio"}:
        return jsonify({"error": "Format must be video or audio"}), 400
    if audio_codec not in {"mp3", "m4a", "flac", "wav", "best"}:
        return jsonify({"error": "Unsupported audio codec"}), 400
    if video_codec not in {"mp4", "mkv", "webm"}:
        return jsonify({"error": "Unsupported video codec"}), 400

    try:
        clip_start, clip_end = _validate_clip_range(
            data.get("clip_start"),
            data.get("clip_end"),
            data.get("duration"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    client_id = _client_id()
    with jobs_lock:
        active_jobs = [job for job in jobs.values() if job.get("status") == "downloading"]
        client_jobs = [job for job in active_jobs if job.get("client_id") == client_id]
        if len(active_jobs) >= MAX_ACTIVE_JOBS:
            return jsonify({"error": "The public service is busy; try again later"}), 503
        if len(client_jobs) >= MAX_ACTIVE_JOBS_PER_CLIENT:
            return jsonify({"error": "Wait for your current downloads to finish"}), 429

        job_id = uuid.uuid4().hex[:20]
        jobs[job_id] = {
            "status": "downloading",
            "url": url,
            "title": str(title)[:300],
            "artist": str(artist)[:200],
            "track": str(track)[:300],
            "uploader": str(uploader)[:200],
            "format_choice": format_choice,
            "audio_codec": audio_codec,
            "video_codec": video_codec,
            "clip_start": clip_start,
            "clip_end": clip_end,
            "client_id": client_id,
            "created_at": time.time(),
        }

    thread = threading.Thread(
        target=run_download,
        args=(
            job_id,
            url,
            format_choice,
            format_id,
            audio_codec,
            video_codec,
            clip_start,
            clip_end,
        ),
    )
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
@_rate_limited(limit=120, window_seconds=300)
def check_status(job_id):
    job = jobs.get(job_id)
    if not job or job.get("client_id") != _client_id():
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
        "filename": job.get("filename"),
    })


@app.route("/api/file/<job_id>")
@app.route("/api/file/<job_id>/<path:filename>")
@_rate_limited(limit=20, window_seconds=3600)
def download_file(job_id, filename=None):
    job = jobs.get(job_id)
    if not job or job.get("client_id") != _client_id() or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=job["filename"])


TRIM_BACKEND_ENABLED = os.environ.get("RECLIP_TRIM_BACKEND", "enabled").lower() != "disabled"


@app.route("/trim")
def trim_page():
    return render_template("trim.html")


@app.route("/api/capabilities")
def capabilities():
    return jsonify({"trimBackend": TRIM_BACKEND_ENABLED})


@app.route("/api/recent-downloads")
def recent_downloads():
    """Audio downloads completed in this session, surfaced on the trim page."""
    audio = []
    for jid, job in jobs.items():
        if (
            job.get("status") == "done"
            and job.get("format_choice") == "audio"
            and job.get("client_id") == _client_id()
        ):
            audio.append({
                "id": jid,
                "filename": job.get("filename", ""),
                "title": job.get("title", ""),
            })
    return jsonify(audio)


def _parse_time(value, fallback=None):
    if value is None or value == "":
        return fallback
    s = str(value).strip()
    if ":" in s:
        parts = s.split(":")
        total = 0.0
        for p in parts:
            total = total * 60 + float(p)
        return total
    return float(s)


@app.route("/api/trim", methods=["POST"])
def trim_audio():
    if not TRIM_BACKEND_ENABLED:
        return jsonify({"error": "Trim backend disabled on this instance"}), 503

    file_obj = request.files.get("file")
    job_id = request.form.get("job_id")
    try:
        start = _parse_time(request.form.get("start"), 0.0)
        end = _parse_time(request.form.get("end"))
    except ValueError:
        return jsonify({"error": "Invalid start/end time"}), 400

    mode = (request.form.get("mode") or "copy").lower()
    if mode not in ("copy", "encode"):
        mode = "copy"

    trim_id = uuid.uuid4().hex[:10]
    cleanup_src = False

    if file_obj and file_obj.filename:
        ext = os.path.splitext(file_obj.filename)[1].lower() or ".aac"
        src_path = os.path.join(DOWNLOAD_DIR, f"trim_src_{trim_id}{ext}")
        file_obj.save(src_path)
        cleanup_src = True
        original_name = os.path.splitext(file_obj.filename)[0]
    elif job_id:
        job = jobs.get(job_id)
        if not job or job.get("status") != "done":
            return jsonify({"error": "Source download not found or not complete"}), 404
        src_path = job["file"]
        ext = os.path.splitext(src_path)[1].lower()
        original_name = os.path.splitext(job.get("filename", "audio"))[0]
    else:
        return jsonify({"error": "No source file or job_id provided"}), 400

    out_ext = ext if ext else ".aac"
    out_path = os.path.join(DOWNLOAD_DIR, f"trim_out_{trim_id}{out_ext}")

    # Raw .aac has no timestamps → `-c copy` with -ss/-to silently produces a
    # 0-byte file. Force re-encode for .aac regardless of mode.
    must_reencode = ext == ".aac"
    use_copy = mode == "copy" and not must_reencode

    if use_copy:
        cmd = ["ffmpeg", "-y", "-ss", str(start)]
        if end is not None:
            cmd += ["-to", str(end)]
        cmd += ["-i", src_path, "-c", "copy", out_path]
    else:
        cmd = ["ffmpeg", "-y", "-i", src_path, "-ss", str(start)]
        if end is not None:
            cmd += ["-to", str(end)]
        cmd += ["-c:a", "aac", "-b:a", "192k", out_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip()[-400:] or "ffmpeg failed"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Trim timed out (3 min limit)"}), 500
    finally:
        if cleanup_src and os.path.exists(src_path):
            try:
                os.remove(src_path)
            except OSError:
                pass

    download_name = f"{original_name}_trimmed{out_ext}"
    return send_file(out_path, as_attachment=True, download_name=download_name)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
