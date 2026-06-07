import os
import sys
import uuid
import glob
import json
import shutil
import subprocess
import threading
from flask import Flask, request, jsonify, send_file, render_template

if len(sys.argv) > 1 and sys.argv[1] == '--yt-dlp-worker':
    import yt_dlp
    sys.exit(yt_dlp.main(sys.argv[2:]))

import imageio_ffmpeg
YT_DLP_CMD = [sys.executable, "--yt-dlp-worker"] if getattr(sys, 'frozen', False) else [sys.executable, "-m", "yt_dlp"]
YT_DLP_CMD.extend(["--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe()])
app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}


@app.after_request
def add_security_headers(response):
    # Required for ffmpeg.wasm on /trim — needs SharedArrayBuffer,
    # which is only available in cross-origin isolated contexts.
    # `credentialless` is the most permissive — cross-origin resources
    # (Google Fonts, unpkg) load without credentials and don't need CORP headers.
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
    response.headers.setdefault('Cross-Origin-Embedder-Policy', 'credentialless')
    return response


def run_download(job_id, url, format_choice, format_id, audio_codec="mp3", video_codec="mp4"):
    job = jobs[job_id]
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    cmd = YT_DLP_CMD + ["--no-playlist", "-o", out_template]

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

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            job["status"] = "error"
            job["error"] = result.stderr.strip().split("\n")[-1]
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
            
        if raw_name:
            safe_name = "".join(c for c in raw_name if c not in r'\/:*?"<>|').strip()[:80].strip()
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

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
        "video_codec": video_codec
    }

    thread = threading.Thread(target=run_download, args=(job_id, url, format_choice, format_id, audio_codec, video_codec))
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
        "filename": job.get("filename"),
    })


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

    if mode == "copy":
        # Fast lossless: seek before input, snaps to keyframe boundary.
        cmd = [ffmpeg_path, "-y", "-ss", str(start)]
        if end is not None:
            cmd += ["-to", str(end)]
        cmd += ["-i", src_path, "-c", "copy", out_path]
    else:
        # Precise re-encode: seek after input, exact cuts.
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
    # Create a native OS window rendering the Flask app
    webview.create_window("ReClip", app, width=1000, height=750)
    webview.start()
