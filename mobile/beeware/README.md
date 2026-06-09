# ReClip Mobile (BeeWare)

BeeWare / Briefcase scaffold for the ReClip mobile apps. See
[../FRAMEWORK_DECISION.md](../FRAMEWORK_DECISION.md) for why BeeWare.

> **Status:** v0.1.0 scaffold — Android MVP. iOS is planned but deferred.

## What this is

A single Python codebase that ships as a native Android (and later iOS) app:

- **UI:** [Toga](https://toga.readthedocs.io/) (real native widgets)
- **Packaging:** [Briefcase](https://briefcase.readthedocs.io/)
- **Download engine:** `yt-dlp` embedded on-device via Chaquopy (Android) /
  Python-Apple-support (iOS, later)
- **No backend.** Everything runs on the phone.

## MVP scope (v0.1.0)

What's wired up in this commit:

- Paste a single video URL
- Toggle MP3 (audio only) vs MP4 (video)
- **Fetch** → show title + uploader
- **Download** → progress bar → "Saved → <path>"

What's deliberately **not** here yet (deferred):

- Bulk URL list / pasted-list dedup
- Quality / resolution picker
- Trim audio page (see [`/trim`](../../templates/trim.html) on web/desktop)
- Recent-downloads list
- Sharing the downloaded file via Android share sheet
- Pixel-perfect editorial-design styling (custom serif font, paper-cream
  background — applied at the palette level only for now)
- iOS target (placeholder block in `pyproject.toml`, not exercised)

## Known limitations

### No ffmpeg on Android in this build

Briefcase's Android template doesn't include an `ffmpeg` binary, and bundling
one requires either a prebuilt static binary (e.g. from Termux) or building
from source for `arm64-v8a` / `armeabi-v7a`. Until we do that:

- **MP4:** `yt_runner.download(..., audio_only=False)` requests a single-file
  pre-muxed MP4 (`format="best[ext=mp4]/best"`). Works for most sites; on
  YouTube the available pre-muxed qualities top out around 720p.
- **MP3:** `FFmpegExtractAudio` is requested as the post-processor. yt-dlp
  will skip post-processing if it can't find ffmpeg, in which case the
  file lands as whatever the source audio container was (`.m4a`, `.webm`,
  etc.). The download still completes; the rename to `.mp3` just doesn't
  happen. Tracking proper ffmpeg bundling as a follow-up.

### Files are saved to app-private storage

`self.paths.data/downloads/` on Android resolves to the app's internal
files dir. The user can't see these from the Files app yet. A follow-up
will move saved files to `/sdcard/Download/ReClip/` via the MediaStore
API (Toga doesn't expose this yet; we'll bridge to Java if needed).

## Build & run

### Prerequisites

- Python 3.11+
- Java 17 (Android Studio installs this; otherwise install Temurin)
- Android SDK + platform-tools (Briefcase will download what it needs on
  first `create android` if you don't already have them)
- A real Android device with USB debugging on, **or** the Android emulator

### Set up the dev environment

```bash
cd mobile/beeware
python -m venv venv
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# bash:
# source venv/bin/activate

pip install --upgrade pip
pip install briefcase
```

### Iterate on the UI locally (desktop preview)

```bash
briefcase dev
```

This installs `toga-winforms` (Win) / `toga-gtk` (Linux) / `toga-cocoa` (mac)
into the venv and runs the app on the host — useful for laying out widgets
and catching obvious bugs without rebuilding for Android every time.

### Build for Android

```bash
briefcase create android   # one-time: scaffolds gradle project, pulls deps
briefcase build android
briefcase run android      # installs and launches on device/emulator
```

### Produce a shippable APK

```bash
briefcase package android --packaging-format apk
# Output: build/reclip/android/gradle/app/build/outputs/apk/release/*.apk
```

The APK is sideload-ready (we are not targeting the Play Store — YouTube
downloaders get pulled there). Upload to the GitHub release page alongside
the desktop binaries.

## Project layout

```
mobile/beeware/
├── pyproject.toml          # Briefcase config (Android + iOS placeholder + desktop)
├── README.md               # this file
└── src/reclip/
    ├── __init__.py
    ├── __main__.py         # entrypoint
    ├── app.py              # Toga UI + handlers
    └── yt_runner.py        # yt-dlp wrapper (adapted from python_reference/)
```

## Roadmap

1. **v0.1.0** (this commit): scaffold + MVP UI, single-URL MP4/MP3 download
2. **v0.2.0**: bundle `ffmpeg` binary for `arm64-v8a` so MP3 post-processing
   and video+audio merging work
3. **v0.3.0**: save to user-visible `/sdcard/Download/ReClip/` via MediaStore
4. **v0.4.0**: bulk paste + quality picker (parity with desktop)
5. **v0.5.0**: trim audio page (port from `/trim`)
6. **v0.6.0**: iOS target — bring the Briefcase iOS template online

When (1)–(4) feel polished on Android, that's also when the iOS port is
worth the effort, per [FRAMEWORK_DECISION.md](../FRAMEWORK_DECISION.md).
