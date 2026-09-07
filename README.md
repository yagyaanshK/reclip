---
title: ReClip
emoji: 🎬
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Download permitted media and precise clips
---

# ReClip

A local-first, open-source interface for downloading permitted video and audio with yt-dlp. Select a quality, extract MP3 audio, or save only a precise time range.

> **Hosted-service limitation:** YouTube rejects requests from this Hugging Face datacenter. Use the [local ReClip app](https://github.com/yagyaanshK/reclip) for YouTube. Availability for every source site can change as sites and yt-dlp extractors change.

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

https://github.com/user-attachments/assets/419d3e50-c933-444b-8cab-a9724986ba05

![ReClip MP3 Mode](assets/preview-mp3.png)

## Features

- Download from sites supported by the installed [yt-dlp](https://github.com/yt-dlp/yt-dlp) version
- MP4 video or MP3 audio extraction
- Quality/resolution picker
- Download precise clips by start/end time without first storing the full source
- Bulk downloads — paste multiple URLs at once
- Automatic URL deduplication
- Clean, responsive UI — no frameworks, no build step
- Intelligent Filename Generation — extracts and formats metadata gracefully (`Artist - Track.mp3` or `Channel - Title.mp4`).
- Local-first operation — local installations use the user's own machine and network connection.

## Quick Start

```bash
git clone https://github.com/yagyaanshK/reclip.git
cd reclip
./reclip.sh
```

Open **http://localhost:8899**.

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

## Supported Sites

ReClip follows [yt-dlp's current extractor support](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), including:

YouTube, TikTok, Instagram, Twitter/X, Reddit, Facebook, Vimeo, Twitch, Dailymotion, SoundCloud, Loom, Streamable, Pinterest, Tumblr, Threads, LinkedIn, and many more.

## Stack

- **Backend:** Python + Flask
- **Frontend:** Vanilla HTML/CSS/JS (single file, no build step)
- **Download engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) + [ffmpeg](https://ffmpeg.org/)
- **Dependencies:** `flask`, `yt-dlp`, `yt-dlp-ejs`, `pycryptodomex`, `curl_cffi`

## Agent Documentation

- [`llms.txt`](https://daddy23-reclip.hf.space/llms.txt) provides a concise capability and limitation summary.
- [`llms-full.txt`](https://daddy23-reclip.hf.space/llms-full.txt) provides detailed usage, reliability, and security guidance.
- Automated crawlers must not invoke the download API. The hosted interface is intended for explicit, user-directed downloads.

## Disclaimer

This tool is intended for personal use only. Please respect copyright laws and the terms of service of the platforms you download from. The developers are not responsible for any misuse of this tool.

## License

[MIT](LICENSE)
