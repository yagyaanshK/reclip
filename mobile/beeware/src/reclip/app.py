"""
ReClip mobile — Toga UI.

MVP scope (per FRAMEWORK_DECISION.md and the v1 brief):
  - paste a single URL
  - choose MP4 / MP3
  - Fetch -> show title + uploader
  - Download -> progress bar -> "Saved" status with file path

Threading model: yt-dlp is blocking, so we hand it to a background thread
via asyncio.to_thread() and update Toga widgets from the main loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from reclip import yt_runner


# Editorial palette (matches the desktop look as closely as Toga allows).
BG = "#f5f0e8"
INK = "#1a1a1a"
ACCENT = "#d97757"
MUTED = "#6b6b6b"


class ReClipApp(toga.App):
    def startup(self) -> None:
        self._video_info: dict | None = None
        self._download_dir = self._resolve_download_dir()

        # --- widgets ---------------------------------------------------------
        title = toga.Label(
            "ReClip",
            style=Pack(padding=(20, 16, 4, 16), font_size=28, font_weight="bold", color=INK),
        )
        subtitle = toga.Label(
            "Paste a video link.",
            style=Pack(padding=(0, 16, 16, 16), color=MUTED),
        )

        self.url_input = toga.MultilineTextInput(
            placeholder="https://...",
            style=Pack(flex=1, padding=(0, 16), height=80),
        )

        self.audio_switch = toga.Switch(
            "MP3 (audio only)",
            value=False,
            style=Pack(padding=(12, 16, 4, 16), color=INK),
        )

        self.fetch_button = toga.Button(
            "Fetch",
            on_press=self.on_fetch,
            style=Pack(padding=(8, 16, 4, 16), background_color=ACCENT, color="#ffffff"),
        )

        self.info_label = toga.Label(
            "",
            style=Pack(padding=(8, 16), color=INK),
        )

        self.download_button = toga.Button(
            "Download",
            on_press=self.on_download,
            enabled=False,
            style=Pack(padding=(8, 16), background_color=ACCENT, color="#ffffff"),
        )

        self.progress = toga.ProgressBar(max=100, value=0, style=Pack(padding=(8, 16)))

        self.status_label = toga.Label(
            "",
            style=Pack(padding=(8, 16, 16, 16), color=MUTED),
        )

        # --- layout ----------------------------------------------------------
        root = toga.Box(
            style=Pack(direction=COLUMN, background_color=BG, flex=1),
            children=[
                title,
                subtitle,
                self.url_input,
                self.audio_switch,
                self.fetch_button,
                self.info_label,
                self.download_button,
                self.progress,
                self.status_label,
            ],
        )

        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = root
        self.main_window.show()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    async def on_fetch(self, widget: toga.Widget) -> None:
        url = (self.url_input.value or "").strip().splitlines()[0:1]
        url = url[0].strip() if url else ""
        if not url:
            self.status_label.text = "Enter a URL first."
            return

        self.fetch_button.enabled = False
        self.download_button.enabled = False
        self.info_label.text = ""
        self.status_label.text = "Fetching info…"

        try:
            info = await asyncio.to_thread(yt_runner.fetch_info, url)
        except Exception as exc:
            self.status_label.text = f"Fetch failed: {exc}"
            self.fetch_button.enabled = True
            return

        self._video_info = {"url": url, **info}
        title = info.get("title") or "(no title)"
        uploader = info.get("uploader") or ""
        self.info_label.text = f"{title}\n{uploader}".strip()
        self.status_label.text = ""
        self.fetch_button.enabled = True
        self.download_button.enabled = True

    async def on_download(self, widget: toga.Widget) -> None:
        if not self._video_info:
            return
        url = self._video_info["url"]
        audio_only = self.format_mp4.value

        self.download_button.enabled = False
        self.fetch_button.enabled = False
        self.progress.value = 0
        self.status_label.text = "Downloading…"

        loop = asyncio.get_event_loop()

        def report(percent: int) -> None:
            loop.call_soon_threadsafe(self._set_progress, percent)

        try:
            final_path = await asyncio.to_thread(
                yt_runner.download,
                url,
                str(self._download_dir),
                audio_only,
                report,
            )
        except Exception as exc:
            self.status_label.text = f"Download failed: {exc}"
            self.download_button.enabled = True
            self.fetch_button.enabled = True
            return

        self.progress.value = 100
        self.status_label.text = f"Saved → {final_path}"
        self.download_button.enabled = True
        self.fetch_button.enabled = True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _set_progress(self, percent: int) -> None:
        self.progress.value = max(0, min(100, percent))

    def _resolve_download_dir(self) -> Path:
        # paths.data is app-private and always writable on every platform.
        base = Path(self.paths.data)
        downloads = base / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        return downloads


def main() -> ReClipApp:
    return ReClipApp(
        formal_name="ReClip",
        app_id="com.yagyaansh.reclip",
        app_name="reclip",
    )
