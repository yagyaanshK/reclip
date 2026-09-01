# Changes from the Original Repository

This branch is the hosted edition of [yagyaanshK/reclip](https://github.com/yagyaanshK/reclip), forked from [averygan/reclip](https://github.com/averygan/reclip).

Live deployment: https://huggingface.co/spaces/Daddy23/reclip

## Hosted Deployment

- Added Hugging Face Spaces Docker metadata to `README.md`.
- Changed the service port to Hugging Face's required port `7860`.
- Runs the app as the non-root `appuser` (UID 1000).
- Runs Flask through a single Gunicorn worker with four threads so in-memory download jobs remain available while requests are handled concurrently.
- Bundles FFmpeg, Deno, `yt-dlp-ejs`, and `curl_cffi` for current extractor, JavaScript challenge, media-processing, and browser-impersonation support.
- Adds the pinned BgUtils PO-token provider and yt-dlp's `mweb` client for per-video YouTube attestation on hosted datacenter traffic.
- Uses the container's managed DNS configuration instead of replacing `/etc/resolv.conf`.
- Uses bounded IPv4 network retries and socket timeouts so blocked upstream requests fail clearly instead of hanging indefinitely.
- Keeps backend audio trimming disabled on the hosted instance; `/trim` performs trimming in the browser with `ffmpeg.wasm`.

## Download Features

- Generates useful filenames from artist/track or uploader/title metadata.
- Adds MP4 video codec and audio codec controls.
- Adds precise per-item clip downloads for video and audio.
- Accepts clip times as seconds, `MM:SS`, or `HH:MM:SS` with millisecond precision.
- Uses yt-dlp source sections plus FFmpeg keyframe correction, avoiding a full source file before cutting where the upstream site supports ranged delivery.
- Improves filename length handling and codec-specific quality selection.

## Hosted Interface

- Adds a desktop-download menu for Windows, macOS, and Linux builds.
- Adds automatic light/dark mode controls and hosted responsive fixes.
- Adds the browser-based `/trim` audio editor with waveform, duration, loading, and AAC fixes.
- Adds the cross-origin isolation headers required by `ffmpeg.wasm`.
- Adds `robots.txt` and `llms.txt` routes and hosted-only static files.

## Repository Files

- `Dockerfile`: Hugging Face runtime and production server configuration.
- `requirements.txt`: hosted Python and extractor dependencies.
- `templates/index.html`: hosted downloader controls and desktop app links.
- `templates/trim.html`: client-side audio trimming interface.
- `static/robots.txt`: crawler policy for the hosted site.
- `static/llms.txt`: concise public description for AI agents and search tools.
- `.gitignore`: excludes local credentials, deployment notes, downloads, and build output.
- `tests/test_clip_download.py`: clip parsing, validation, command, and API coverage.

The README preview binaries from the original repository are omitted from this branch because they are not required at runtime.
