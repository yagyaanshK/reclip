# ReClip

<!-- mcp-name: io.github.yagyaanshK/reclip -->

A self-hosted, open-source video and audio downloader with a clean web UI. Paste links from YouTube, TikTok, Instagram, Twitter/X, and 1000+ other sites — download as MP4 or MP3.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

https://github.com/user-attachments/assets/419d3e50-c933-444b-8cab-a9724986ba05

![ReClip MP3 Mode](assets/preview-mp3.png)

## Features

- Download videos from 1000+ supported sites (via [yt-dlp](https://github.com/yt-dlp/yt-dlp))
- MP4 video or MP3 audio extraction
- Quality/resolution picker
- Download precise clips by start/end time without first storing the full source
- Bulk downloads — paste multiple URLs at once
- Automatic URL deduplication
- Clean, responsive UI — no frameworks, no build step
- Native Desktop Apps — zero-install standalone executables for Windows, macOS, and Linux.
- Intelligent Filename Generation — extracts and formats metadata gracefully (`Artist - Track.mp3` or `Channel - Title.mp4`).
- Local-first operation — downloads run on the user's own machine and network connection.
- Automated Build Pipeline — GitHub Actions automatically compiles and publishes new executables upon every version tag push.

## 🚀 Download ReClip App

You don't need to install Python or use the terminal. Download the pre-built standalone executable for your operating system:

- 🪟 **Windows:** [ReClip.exe](https://github.com/yagyaanshK/reclip/releases/latest/download/ReClip.exe)
- 🍎 **macOS:** [ReClip-macos.dmg](https://github.com/yagyaanshK/reclip/releases/latest/download/ReClip-macos.dmg)
- 🐧 **Linux:** [ReClip](https://github.com/yagyaanshK/reclip/releases/latest/download/ReClip)

*Note: The native apps contain a bundled server and PyWebView browser. Simply open the app and it will launch right in its own native window!*

## 🛠️ Run from Source (Terminal)

```bash
git clone https://github.com/yagyaanshK/reclip.git
cd reclip
```

**On Windows:**
Double-click `start_windows.bat`.

**On Mac / Linux:**
```bash
./reclip.sh
```

Open **http://localhost:8899** in your browser.

### Build Executables Locally
To manually compile ReClip into a standalone executable:
- **Windows:** Run `build_windows.bat` -> Output in `dist/`
- **Mac / Linux:** Run `./build_unix.sh` -> Output in `dist/`

Or with Docker:

```bash
docker build -t reclip . && docker run -p 8899:8899 reclip
```

## Usage

1. Paste one or more video URLs into the input box
2. Choose **MP4** (video) or **MP3** (audio)
3. Click **Fetch** to load video info and thumbnails
4. Select quality/resolution if available
5. Optionally enable **Clip** and enter start/end times as `SS`, `MM:SS`, or `HH:MM:SS.000`
6. Click **Download** on individual videos, or **Download All**

## Command-Line Interface

ReClip also exposes a structured local CLI for shell scripts and AI agents. Install the project in a Python 3.10+ environment, then run:

```bash
reclip inspect "https://example.com/media" --json
reclip download "https://example.com/media" --format mp4 --quality 1080p --output downloads --json
reclip clip "https://example.com/media" --start 01:20:15.500 --end 01:25:00 --format mp3 --output downloads --json
reclip sites --json
```

All JSON responses contain an `ok` field. Failures include a stable machine-readable error `code` and a human-readable `message`. Downloads occur locally and return the absolute output path, filename, byte size, format, source URL, and clip range.

## AI Agent Integration (MCP)

Install the local MCP server and CLI from a checkout:

```bash
python -m pip install .
```

After the first package release, agents can launch it without cloning the repository using `uvx reclip-mcp`.

Configure an MCP host to start ReClip over stdio. Use absolute paths because desktop hosts start servers from their own working directory:

```json
{
  "mcpServers": {
    "reclip": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "reclip_mcp"],
      "env": {
        "RECLIP_MCP_DOWNLOAD_DIR": "/absolute/path/to/downloads"
      }
    }
  }
}
```

The server exposes `inspect_media`, `download_media`, `download_clip`, and `list_supported_sites`. Download tools require explicit user authorization and can write only to `RECLIP_MCP_DOWNLOAD_DIR`, which defaults to `~/Downloads/ReClip`.

## Supported Sites

Anything [yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), including:

YouTube, TikTok, Instagram, Twitter/X, Reddit, Facebook, Vimeo, Twitch, Dailymotion, SoundCloud, Loom, Streamable, Pinterest, Tumblr, Threads, LinkedIn, and many more.

## Stack

- **Backend:** Python + Flask
- **Frontend:** Vanilla HTML/CSS/JS (single file, no build step)
- **Download engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) + [ffmpeg](https://ffmpeg.org/)
- **Dependencies:** `flask`, `yt-dlp`, `yt-dlp-ejs`, `pycryptodomex`, `pywebview`, `pyinstaller`, `imageio-ffmpeg`

## Disclaimer

This tool is intended for personal use only. Please respect copyright laws and the terms of service of the platforms you download from. The developers are not responsible for any misuse of this tool.

## License

[MIT](LICENSE)
