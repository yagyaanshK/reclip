# Archived: Kotlin Android Reference

This folder contains reference material from an early Android-first plan that was superseded.

**Active mobile development uses BeeWare** — see [../FRAMEWORK_DECISION.md](../FRAMEWORK_DECISION.md) for the rationale.

## What's here

| File | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Original architecture analysis for the Kotlin path. The yt-dlp-on-Android reasoning still applies (BeeWare uses Chaquopy internally for the same purpose). |
| [python_reference/reclip_runner.py](python_reference/reclip_runner.py) | Python wrapper around yt-dlp. Logic transfers directly to the BeeWare project with minimal changes. |
| [python_reference/requirements.txt](python_reference/requirements.txt) | Python dependencies (yt-dlp, pycryptodomex) |

## What was removed

The full Kotlin/Gradle/Compose scaffold (Gradle build files, Manifest, Kotlin source, Compose theme, resources) was deleted. If we ever need to look at it again, it lives in the git history of the `main` branch.
