# YouTube Metadata Extraction Findings

This document records the exact JSON metadata structure extracted by `yt-dlp` for different types of YouTube URLs. This data maps to how ReClip intelligently formats filenames for downloaded media.

## 1. Standard YouTube Video
**URL:** `https://youtu.be/EeLG5EY-5z4`
*Type: Typical vlog or standard video.*

```text
  Title:    How I Lived in my Jimny for 20 Days at Temperatures below -25C
  Uploader: Rebo on Wheels
  Artist:   None
  Track:    None
```
**ReClip Behavior:** Since `Artist` and `Track` are null, the app falls back to the uploader logic, yielding: `Rebo on Wheels - How I Lived in my Jimny for 20 Days at Temperatures below -25C`.

---

## 2. YouTube "Art Track" (Music disguised as Video)
**URL:** `https://youtu.be/vNlC41r8g0U`
*Type: Official music track hosted on standard YouTube with a static album cover thumbnail.*

```text
  Title:    Into The Black
  Uploader: Vancouver Sleep Clinic
  Artist:   Vancouver Sleep Clinic
  Track:    Into The Black
```
**ReClip Behavior:** Since `Artist` and `Track` explicitly exist, the app gracefully formats it as a proper audio track: `Vancouver Sleep Clinic - Into The Black`.

---

## 3. YouTube Music URL
**URL:** `https://music.youtube.com/watch?v=Fhs8OSuQ3y8`
*Type: Native YouTube Music URL.*

```text
  Title:    Matsuri
  Uploader: LEO ROJAS - official
  Artist:   Leo Rojas
  Track:    Matsuri
```
**ReClip Behavior:** The exact `Artist` ("Leo Rojas") and `Track` ("Matsuri") are captured correctly, entirely ignoring the often messy `Uploader` ("LEO ROJAS - official"). This yields a pristine, professional audio filename: `Leo Rojas - Matsuri`.
