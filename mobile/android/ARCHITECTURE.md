# ReClip Android — Architecture (ARCHIVED REFERENCE)

> **⚠️ This document describes a path we did NOT take.**
>
> An earlier plan was to build the Android app natively in Kotlin + Compose with Chaquopy for yt-dlp. After evaluating iOS implications (see [../FRAMEWORK_DECISION.md](../FRAMEWORK_DECISION.md)), we switched to **BeeWare** for cross-platform Python on both Android and iOS.
>
> This file is preserved as reference material for:
> - The technical analysis of running yt-dlp on Android (still accurate — BeeWare uses Chaquopy internally for the same purpose)
> - APK size estimates and dependency choices
> - The Python `reclip_runner.py` logic in `python_reference/`, which can be adapted for BeeWare with minor changes
>
> **For the actual mobile app, see the BeeWare project (to be scaffolded under `mobile/beeware/`).**

---

Native Android app that mirrors the desktop ReClip experience.

## Tech Stack

| Concern | Choice | Why |
|---|---|---|
| Language | Kotlin | Modern, Google-recommended |
| UI | Jetpack Compose | Declarative, easier theming |
| Min SDK | 21 (Android 5.0) | 99.5% device coverage |
| Target SDK | 34 (Android 14) | Latest, required by Play (even though we're sideloading) |
| Build | Gradle 8.x with Kotlin DSL | Standard |
| Python runtime | Chaquopy 16.x | Embeds CPython, lets us run yt-dlp directly |
| Media processing | ffmpeg-kit-full-gpl | Android-native ffmpeg port for merging |
| Background work | WorkManager | Survives process death, official Android API |
| Notifications | NotificationCompat | Download progress |
| File storage | MediaStore API | Saves to public Downloads/ReClip/ folder |
| Architecture | MVVM + Repository | Standard Android pattern |

## Module Layout

```
mobile/android/
├── app/
│   ├── build.gradle.kts          App module config (Compose, Chaquopy)
│   ├── proguard-rules.pro
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/reclip/app/
│       │   ├── ReClipApplication.kt
│       │   ├── MainActivity.kt
│       │   ├── ui/
│       │   │   ├── theme/         Colors, typography, shapes
│       │   │   ├── screens/       MainScreen, DownloadsScreen
│       │   │   └── components/    UrlInput, VideoCard, QualityChips
│       │   ├── data/
│       │   │   ├── YtDlpRepository.kt   Bridges to Python via Chaquopy
│       │   │   ├── DownloadRepository.kt
│       │   │   └── models/
│       │   ├── domain/
│       │   │   ├── FetchInfoUseCase.kt
│       │   │   └── DownloadVideoUseCase.kt
│       │   └── work/
│       │       └── DownloadWorker.kt    WorkManager job
│       ├── python/
│       │   ├── reclip_runner.py    Wrapper around yt-dlp Python API
│       │   └── requirements.txt    yt-dlp, etc.
│       └── res/                     Resources, themes, fonts
├── build.gradle.kts                 Root project
├── settings.gradle.kts
├── gradle.properties
└── gradle/libs.versions.toml        Version catalog
```

## How yt-dlp runs on Android

1. **Chaquopy** Gradle plugin bundles CPython interpreter + selected packages into the APK.
2. App reads `python/requirements.txt` (just `yt-dlp` + `pycryptodomex`).
3. At runtime, Kotlin calls Python via `Python.getInstance().getModule("reclip_runner")`.
4. `reclip_runner.py` uses `yt_dlp.YoutubeDL` directly (not subprocess — that doesn't work on Android).
5. Downloaded files go to app cache, then we move them to public `Downloads/ReClip/` via MediaStore.

## APK Size Estimate

| Component | Size |
|---|---|
| CPython runtime | ~10 MB |
| yt-dlp + deps | ~5 MB |
| ffmpeg-kit-full-gpl | ~15 MB |
| App code + resources | ~2 MB |
| **Total APK** | **~30-35 MB** |

## Build & Distribution

- Built via Android Studio or `./gradlew assembleRelease`
- Output: `app/build/outputs/apk/release/app-release.apk`
- Signed APK distributable from your own website (no Play Store)
- Updates: in-app update check pointing to a JSON manifest on your site, then prompt to download new APK

## Permissions

- `INTERNET` — yt-dlp needs network
- `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_DATA_SYNC` — for background downloads (Android 14+)
- `POST_NOTIFICATIONS` — Android 13+ runtime permission
- `WRITE_EXTERNAL_STORAGE` (Android 9 and below only) — for saving to Downloads
- No storage permission needed on Android 10+ when using MediaStore Downloads collection
