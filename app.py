import os
import sys

if len(sys.argv) > 1 and sys.argv[1] == '--yt-dlp-worker':
    # Runs yt-dlp inside the frozen executable. Kept above the heavy imports so
    # every download does not pay for Flask start-up. ytdlp_runtime swaps in a
    # newer yt-dlp downloaded at runtime when one is installed.
    import ytdlp_runtime
    ytdlp_runtime.activate()
    import yt_dlp
    sys.exit(yt_dlp.main(sys.argv[2:]))

import uuid
import glob
import json
import shutil
import subprocess
import threading
from flask import Flask, request, jsonify, send_file, render_template

import ytdlp_runtime
from reclip_core import (
    build_download_command as _core_build_download_command,
    describe_error as _describe_error,
    format_filename_time as _format_filename_time,
    parse_clip_time as _parse_clip_time,
    validate_clip_range as _validate_clip_range,
)

import imageio_ffmpeg
if getattr(sys, 'frozen', False):
    YT_DLP_CMD = [sys.executable, "--yt-dlp-worker"]
else:
    YT_DLP_CMD = [sys.executable, os.path.abspath(__file__), "--yt-dlp-worker"]
YT_DLP_CMD.extend(["--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe()])
app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}


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
    return _core_build_download_command(
        out_template,
        url,
        format_choice,
        format_id,
        audio_codec,
        video_codec,
        clip_start,
        clip_end,
        base_command=YT_DLP_CMD,
    )


def _last_stderr_line(result):
    lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("ERROR:"):
            return line
    return lines[-1] if lines else ""


def _run_ytdlp(cmd, timeout):
    """Run yt-dlp; on a failure that smells like a stale extractor, update it and retry once.

    Returns ``(result, error)``; ``error`` is ``None`` on success, otherwise a dict
    with ``message``, ``code``, ``detail`` and ``ytdlp`` (the version in use).
    """
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode == 0:
        return result, None

    error = _describe_error(_last_stderr_line(result))
    hint = ""
    if error["maybe_outdated"] and ytdlp_runtime.enabled():
        outcome = ytdlp_runtime.ensure_latest(min_interval=ytdlp_runtime.FAILURE_CHECK_INTERVAL)
        if outcome.get("updated"):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                return result, None
            error = _describe_error(_last_stderr_line(result))
            hint = (
                f" ReClip updated its downloader to yt-dlp {outcome['version']} and retried,"
                " but the platform still refused. Try again later."
            )
        elif outcome.get("error"):
            hint = " ReClip could not check for a downloader update. Are you online?"
        elif outcome.get("skipped") == "recently-checked":
            hint = " The downloader was checked for updates recently. Try again in a few minutes."
        else:
            hint = (
                f" Your downloader (yt-dlp {outcome.get('version') or 'unknown'}) is already the newest"
                " release. The platform may have changed again; try later or update ReClip."
            )
    return result, {
        "message": error["message"] + hint,
        "code": error["code"],
        "detail": error["detail"],
        "ytdlp": ytdlp_runtime.effective_version(),
    }


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
        result, error = _run_ytdlp(cmd, timeout=300)
        if error:
            job["status"] = "error"
            job["error"] = error["message"]
            job["error_code"] = error["code"]
            job["error_detail"] = error["detail"]
            job["ytdlp"] = error["ytdlp"]
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
    except subprocess.TimeoutExpired:
        job["status"] = "error"
        job["error"] = "Download timed out (5 min limit)"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    cmd = YT_DLP_CMD + ["--no-playlist", "-j", url]
    try:
        result, error = _run_ytdlp(cmd, timeout=60)
        if error:
            return jsonify({"error": error["message"], "code": error["code"],
                            "detail": error["detail"], "ytdlp": error["ytdlp"]}), 400

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
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching video info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json
    url = data.get("url", "").strip()
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    audio_codec = data.get("audio_codec", "mp3")
    video_codec = data.get("video_codec", "mp4")
    title = data.get("title", "")
    artist = data.get("artist", "")
    track = data.get("track", "")
    uploader = data.get("uploader", "")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        clip_start, clip_end = _validate_clip_range(
            data.get("clip_start"),
            data.get("clip_end"),
            data.get("duration"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {
        "status": "downloading", 
        "url": url, 
        "title": title,
        "artist": artist,
        "track": track,
        "uploader": uploader,
        "format_choice": format_choice,
        "audio_codec": audio_codec,
        "video_codec": video_codec,
        "clip_start": clip_start,
        "clip_end": clip_end,
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
def check_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
        "code": job.get("error_code"),
        "detail": job.get("error_detail"),
        "ytdlp": job.get("ytdlp"),
        "filename": job.get("filename"),
    })


@app.route("/api/ytdlp")
def ytdlp_status():
    return jsonify(ytdlp_runtime.status())


@app.route("/api/ytdlp/update", methods=["POST"])
def ytdlp_update():
    """Manual 'check for downloader updates' from the UI."""
    if not ytdlp_runtime.enabled():
        return jsonify({"updated": False, "version": ytdlp_runtime.effective_version(),
                        "message": "Runtime updates only apply to the packaged desktop app."})
    try:
        outcome = ytdlp_runtime.update()
    except Exception as exc:
        return jsonify({"updated": False, "version": ytdlp_runtime.effective_version(),
                        "error": str(exc)}), 502
    if outcome["updated"]:
        message = f"Downloader updated to yt-dlp {outcome['version']}."
    else:
        message = f"yt-dlp {outcome['version']} is already the newest release."
    return jsonify({**outcome, "message": message})


@app.route("/api/file/<job_id>")
@app.route("/api/file/<job_id>/<path:filename>")
def download_file(job_id, filename=None):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=job["filename"])


@app.route("/api/save/<job_id>", methods=["POST"])
def save_file_native(job_id):
    """Desktop-only: copy the downloaded file to a user-chosen location via native Save dialog."""
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404

    src = job["file"]
    suggested = job.get("filename", os.path.basename(src))
    ext = os.path.splitext(suggested)[1] or ".mp4"

    try:
        import webview
        # Get the active pywebview window for the native dialog
        window = webview.windows[0] if webview.windows else None
        if not window:
            return jsonify({"error": "No active window"}), 500

        result = window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=suggested,
            file_types=(f'Media files (*{ext})',)
        )
        if result:
            dest = result if isinstance(result, str) else result[0]
            shutil.copy2(src, dest)
            return jsonify({"ok": True, "path": dest})
        else:
            return jsonify({"ok": False, "error": "Cancelled"})
    except ImportError:
        return jsonify({"error": "Not running in desktop mode"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        if job.get("status") == "done" and job.get("format_choice") == "audio":
            audio.append({
                "id": jid,
                "filename": job.get("filename", ""),
                "title": job.get("title", ""),
            })
    return jsonify(audio)


def _parse_time(value, fallback=None):
    """Accept '90', '90.5', or '00:01:30.5' formats; return seconds as float."""
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
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

    # Raw .aac has no timestamps → `-c copy` with -ss/-to silently produces a
    # 0-byte file. Force re-encode for .aac regardless of mode.
    must_reencode = ext == ".aac"
    use_copy = mode == "copy" and not must_reencode

    if use_copy:
        # Fast lossless: seek before input, snaps to keyframe boundary.
        cmd = [ffmpeg_path, "-y", "-ss", str(start)]
        if end is not None:
            cmd += ["-to", str(end)]
        cmd += ["-i", src_path, "-c", "copy", out_path]
    else:
        # Re-encode for exact cuts (or because the format needs it).
        cmd = [ffmpeg_path, "-y", "-i", src_path, "-ss", str(start)]
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
    import webview
    # Keep the frozen yt-dlp fresh: a throttled daily check that never blocks start-up.
    threading.Thread(target=ytdlp_runtime.ensure_latest, daemon=True).start()
    # Create a native OS window rendering the Flask app
    webview.create_window("ReClip", app, width=1000, height=750)
    webview.start()
