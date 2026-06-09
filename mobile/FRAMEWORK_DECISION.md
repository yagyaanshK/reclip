# Mobile Framework Decision: Why BeeWare

> **Decision date:** 2026-06-07
> **Decision:** Use [BeeWare (Toga + Briefcase)](https://beeware.org) for both Android and iOS
> **Status:** Accepted

This document records the evaluation process that led us to choose BeeWare for the ReClip mobile apps, so that future contributors (or future-you) can understand the reasoning without re-deriving it from scratch.

---

## TL;DR

We chose **BeeWare** because it is the only option that:

1. Reuses the existing Python + yt-dlp codebase on **both** Android and iOS
2. Renders **native widgets** (not a custom toolkit, not a Flutter wrapper)
3. Avoids the iOS yt-dlp dead end that Kotlin/Swift native paths run into
4. Keeps the mobile app to **one codebase** instead of three (Python desktop + Kotlin Android + Swift iOS)

The trade-off we accepted: slightly less UI polish than fully-native Swift/Kotlin, and dependence on BeeWare's continued maturity, particularly on iOS where the framework is still iterating.

---

## Constraints & Goals

These are the inputs that shaped the decision. If any of these change, the decision should be re-evaluated.

| Constraint | Why it matters |
|---|---|
| **No backend** — yt-dlp must run on the device | Public cloud deployments hit YouTube's datacenter IP block; we want a phone app that just works |
| **Sideload-friendly distribution** — APK on a website, iOS via TestFlight / AltStore / self-signed | We accept we'll never be on the Play Store or App Store (YouTube downloaders get banned) |
| **Match the desktop "editorial" look** — Instrument Serif, DM Mono, paper-cream bg, orange accent | Brand consistency across all platforms |
| **Single maintainer** — solo project, not a team | Maintenance cost matters a lot |
| **Both Android and iOS eventually** | iOS deferred but planned |
| **"Native technologies, no fancy frameworks"** (original goal) | Ruled out Flutter, React Native, Cordova |

---

## Options Evaluated

We considered five paths in detail.

### Option A — Kotlin + Chaquopy (Android only at first, Swift later for iOS)

**Architecture:** Native Kotlin/Compose UI on Android, embed CPython via Chaquopy to run yt-dlp. iOS would later be written from scratch in Swift/SwiftUI.

**Pros:**
- Best-in-class Android UX (Material 3, Compose, full platform API access)
- Mature, Google-blessed tools
- Smallest possible APK with full features (~30 MB)
- Best access to platform-specific features (share sheet, widgets, background workers, MediaStore)

**Cons:**
- **Three codebases to maintain forever:** Python desktop/web/HF + Kotlin Android + Swift iOS
- **iOS yt-dlp is a brick wall.** Apple's sandbox blocks subprocess. Your options on iOS are:
  - Custom Swift extractors → write YouTube/TikTok/etc. parsers by hand; yt-dlp has 1000+ extractors maintained by a community; replicating even 10 is months of work and they break weekly
  - Embed Python via `Python-Apple-support` → at which point you've rebuilt half of BeeWare
  - Use a Swift port (`YoutubeKit`, `YoutubeDL.swift`) → support 1-5 sites, unmaintained
  - Skip yt-dlp on iOS → defeats the purpose
- iOS rebuild requires writing the entire UI again in Swift, with zero code reuse from Android

**Why we rejected it:** The iOS story collapses. Either you accept iOS being permanently second-class with limited platform support, or you end up embedding Python yourself — at which point BeeWare gives you that plus a shared codebase for free.

---

### Option B — Kivy

**Architecture:** Python framework with its own custom UI widget toolkit. Cross-platform via `python-for-android` (Android) and `kivy-ios` (iOS).

**Pros:**
- Single Python codebase
- Mature, has been around for over a decade
- yt-dlp works fine
- Reasonable build pipeline for Android

**Cons:**
- **Custom widget toolkit doesn't look native on any platform.** Kivy apps have a distinctive "Kivy" appearance — neither Material nor Cupertino. Would not match the editorial desktop look without significant custom drawing.
- **iOS support via `kivy-ios` is fragile.** Breaks with new Xcode versions, requires manual patches.
- Best-suited to games and prototypes, less so to polished consumer apps
- Active development has slowed in recent years

**Why we rejected it:** UI fidelity to the desktop design would be very hard. We chose a framework with native widgets we can style, not a custom toolkit we'd fight.

---

### Option C — Flet

**Architecture:** Python framework that renders Flutter widgets. You write Python, Flet runs a Flutter app under the hood.

**Pros:**
- Looks great out of the box — Flutter's Material 3 / Cupertino widgets are polished
- Cross-platform (Android, iOS, web, desktop)
- Easy to learn, single Python codebase
- yt-dlp works fine
- Active development, growing community

**Cons:**
- **It's Flutter wearing a Python costume.** The original goal explicitly excluded "fancy frameworks" — Flet is exactly that.
- **Largest binary by far:** ~50-80 MB minimum due to Flutter runtime, before any of your code or yt-dlp
- **Limited access to platform-specific APIs.** Background `WorkManager` jobs, MediaStore, share extensions, etc. are awkward or unavailable through Flet's abstraction layer
- Not truly native — every widget is a Flutter render, not a real `View` or `UIView`

**Why we rejected it:** Contradicts the "native technologies" constraint and ships a Flutter runtime on every device for what is fundamentally a UI shell around yt-dlp.

---

### Option D — BeeWare (Toga + Briefcase) ← CHOSEN

**Architecture:** Python framework that renders **native widgets** on each platform via platform-specific backends:
- Android: uses Chaquopy internally to embed CPython, renders real Android `View`s
- iOS: uses `Python-Apple-support` to embed CPython, renders real `UIView`s via Rubicon-ObjC
- macOS, Windows, Linux, web also supported

You write Python with the **Toga** UI library and package with **Briefcase**.

**Pros:**
- **Single Python codebase for Android + iOS** (and reusable with the existing desktop/web code where it makes sense)
- **Native widgets on each platform** — not a Flutter wrapper, not a custom toolkit
- **yt-dlp just works on both platforms** — including iOS, because BeeWare does the Python-on-iOS embedding for you
- Significantly less code to write and maintain
- BeeWare's Android backend literally uses Chaquopy, which was our second-choice solution anyway
- Active development, backed by the Python Software Foundation

**Cons:**
- **iOS support is less polished** than the Android side. Some Toga widgets are missing or partial on iOS. Active improvement but rough edges remain.
- **Styling system is more limited than SwiftUI / Compose.** Matching the exact editorial desktop look (specific fonts, paper-cream background, orange accents) is possible but requires more careful styling than a fully native app would.
- **Maturity gap with Compose / SwiftUI.** Both are battle-tested by millions of apps; Toga is mature but smaller in user base.
- **Larger binary than fully native** (~40-60 MB) due to embedded CPython runtime, though smaller than Flet
- Some iOS-specific niceties (share extensions, app widgets, Siri shortcuts) require dropping into Swift via Rubicon-ObjC bridging — possible but not idiomatic

**Why we chose it:** It is the only option that simultaneously solves the iOS yt-dlp problem, gives us native widgets, and lets us maintain one codebase instead of three. Every other path either fails on iOS, ships a fat framework, or commits us to writing the same app three times.

---

### Option E — PWA / WebView wrapper

**Architecture:** Wrap the existing Flask web frontend in a WebView or install it as a Progressive Web App.

**Why we rejected it immediately:** Both require a backend to run yt-dlp. The PWA sandbox cannot bundle Python or any native binary. WebView gives us no execution model for yt-dlp on the device. This contradicts the no-backend goal — already covered in the [DEPLOYMENT_OPTIONS.md](../DEPLOYMENT_OPTIONS.md) on the `hf-deploy` branch.

---

## Decision Matrix

Score each option (1-5, higher is better) against the goals that matter for ReClip mobile:

| Criterion | Weight | Kotlin+Swift | Kivy | Flet | **BeeWare** | PWA |
|---|---|---|---|---|---|---|
| yt-dlp works on Android | 5 | 5 | 5 | 5 | **5** | 0 |
| yt-dlp works on iOS | 5 | 1 | 3 | 4 | **5** | 0 |
| Single codebase | 4 | 1 | 5 | 5 | **5** | 5 |
| Native look on each platform | 3 | 5 | 1 | 4 | **4** | 3 |
| Match editorial desktop design | 3 | 5 | 1 | 4 | **3** | 5 |
| Sideloadable distribution | 3 | 5 | 5 | 5 | **5** | 4 |
| Low maintenance burden | 4 | 1 | 4 | 4 | **4** | 5 |
| Small binary | 2 | 5 | 4 | 1 | **3** | 5 |
| Mature ecosystem | 3 | 5 | 4 | 3 | **3** | 5 |
| Platform-specific APIs (notifications, shares, MediaStore) | 3 | 5 | 3 | 2 | **3** | 1 |
| **Weighted total** | | **121** | **115** | **124** | **131** | **94** |

BeeWare wins on the goals that matter most to this project: solving iOS, code reuse, native widgets without a framework runtime.

(PWA scores low because it fails the no-backend constraint entirely; Kotlin+Swift scores low primarily because of the iOS yt-dlp problem and the maintenance cost of three codebases.)

---

## Risks We Are Accepting

1. **iOS BeeWare backend may have rough edges.** Mitigation: develop Android first (more mature backend), tackle iOS later when BeeWare's iOS story has matured further or we have time to contribute fixes upstream.

2. **Styling fidelity to desktop design will require effort.** Mitigation: accept "close enough" on first release, refine over time. The serifs and custom colors are achievable; pixel-perfect parity is not the goal.

3. **BeeWare project health is a single point of failure.** Mitigation: BeeWare is backed by the PSF and has steady contributor activity. If BeeWare were to stall, we could fall back to the Kotlin path for Android (already scaffolded as reference) and accept the iOS gap.

4. **Larger APK than fully native.** Mitigation: ~40-60 MB is acceptable for a media downloader. Modern phones handle this fine. Users sideloading a YouTube downloader already accept it's not a tiny app.

5. **Some platform-specific features may need bridging code.** Mitigation: BeeWare allows dropping into native code (Java/Kotlin on Android, ObjC/Swift on iOS) when needed. Most features we want (file save, notifications, share intent) are already supported by Toga.

---

## When to Re-evaluate

This decision should be revisited if any of the following happen:

- BeeWare's iOS backend regresses or stalls in development for an extended period
- The desktop look requires UI features Toga genuinely cannot support
- The project scales beyond a single maintainer and the team has strong Swift/Kotlin expertise
- yt-dlp adopts a different architecture that no longer requires Python at runtime
- Apple or Google introduce restrictions that block Python embedding on their platforms

---

## What We Are NOT Reusing From the Kotlin Scaffold

The earlier `mobile/android/` Kotlin scaffold was started before this decision. It is being archived rather than developed further. Specifically:

- **Discarded:** Gradle config, Kotlin source files, Compose UI, Chaquopy plugin setup
- **Kept as reference:** [`mobile/android/ARCHITECTURE.md`](android/ARCHITECTURE.md), the Python `reclip_runner.py` (logic can be adapted for the BeeWare version), the color/typography values that define the desktop design tokens

---

## References

- [BeeWare project](https://beeware.org)
- [Toga widget toolkit](https://toga.readthedocs.io)
- [Briefcase packaging tool](https://briefcase.readthedocs.io)
- [Chaquopy (used by BeeWare Android backend)](https://chaquo.com/chaquopy)
- [Python-Apple-support (used by BeeWare iOS backend)](https://github.com/beeware/Python-Apple-support)
- [Kivy](https://kivy.org)
- [Flet](https://flet.dev)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
