"""
ReClip mobile — Toga UI.

Designed to track the editorial look of the desktop/web app: warm cream
background, orange-red accent, serif wordmark with italic "Clip", DM-Mono-
style uppercase tracking-out for labels and buttons.

Toga can't render every CSS detail (no border-radius, no inline rich text
within a single Label, no Google Fonts), so the wordmark is built from two
adjacent Labels and we fall back to platform-substituted serif + monospace
families.

Threading: yt-dlp is blocking; we hand it to asyncio.to_thread() and
marshal progress back via loop.call_soon_threadsafe().
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from reclip import yt_runner


# Exact palette from templates/index.html :root.
BG = "#f4f1eb"
FG = "#3a3a38"
ACCENT = "#e85d2a"
ACCENT_HOVER = "#d04e1f"
MUTED = "#9c9889"
CARD = "#ffffff"
CARD_BORDER = "#e2ded6"

SERIF = "serif"
MONO = "monospace"

PAGE_PAD = 20


class ReClipApp(toga.App):
    def startup(self) -> None:
        self._video_info: dict | None = None
        self._download_dir = self._resolve_download_dir()
        self._audio_mode = False  # False = Video (MP4), True = Audio (MP3)

        # --- brand wordmark: "Re" + italic accent "Clip" ---------------------
        re_label = toga.Label(
            "Re",
            style=Pack(
                font_family=SERIF, font_size=56, font_weight="normal", color=FG,
            ),
        )
        clip_label = toga.Label(
            "Clip",
            style=Pack(
                font_family=SERIF, font_size=56, font_style="italic", color=ACCENT,
            ),
        )
        wordmark = toga.Box(
            children=[re_label, clip_label],
            style=Pack(direction=ROW, padding=(36, PAGE_PAD, 0, PAGE_PAD)),
        )

        subtitle = toga.Label(
            "FREE  MEDIA  DOWNLOADER",
            style=Pack(
                font_family=MONO, font_size=10, color=MUTED,
                padding=(6, PAGE_PAD, 28, PAGE_PAD),
            ),
        )

        # --- URL input -------------------------------------------------------
        self.url_input = toga.MultilineTextInput(
            placeholder="Paste a video URL…",
            style=Pack(
                flex=1, height=84,
                padding=(0, PAGE_PAD, 0, PAGE_PAD),
                background_color=CARD, color=FG,
                font_family=MONO, font_size=13,
            ),
        )
        hint = toga.Label(
            "ONE LINK AT A TIME ON MOBILE.",
            style=Pack(
                font_family=MONO, font_size=9, color=MUTED,
                padding=(6, PAGE_PAD, 18, PAGE_PAD),
            ),
        )

        # --- Video / Audio pill toggle --------------------------------------
        self.video_pill = toga.Button(
            "VIDEO",
            on_press=self.on_pick_video,
            style=Pack(
                flex=1, padding=(0, 4, 0, PAGE_PAD),
                background_color=FG, color=BG,
                font_family=MONO, font_size=11, font_weight="bold",
            ),
        )
        self.audio_pill = toga.Button(
            "AUDIO",
            on_press=self.on_pick_audio,
            style=Pack(
                flex=1, padding=(0, PAGE_PAD, 0, 4),
                background_color=CARD, color=MUTED,
                font_family=MONO, font_size=11, font_weight="bold",
            ),
        )
        pill_row = toga.Box(
            children=[self.video_pill, self.audio_pill],
            style=Pack(direction=ROW, padding=(0, 0, 14, 0)),
        )

        # --- Fetch button ----------------------------------------------------
        self.fetch_button = toga.Button(
            "FETCH",
            on_press=self.on_fetch,
            style=Pack(
                padding=(0, PAGE_PAD, 18, PAGE_PAD),
                background_color=ACCENT, color="#ffffff",
                font_family=MONO, font_size=12, font_weight="bold",
                height=44,
            ),
        )

        # --- Result card (hidden until fetch completes) ----------------------
        self.card_title = toga.Label(
            "",
            style=Pack(
                font_family=SERIF, font_size=18, color=FG,
                padding=(14, 14, 4, 14), background_color=CARD,
            ),
        )
        self.card_meta = toga.Label(
            "",
            style=Pack(
                font_family=MONO, font_size=9, color=MUTED,
                padding=(0, 14, 12, 14), background_color=CARD,
            ),
        )
        self.download_button = toga.Button(
            "DOWNLOAD",
            on_press=self.on_download,
            enabled=False,
            style=Pack(
                padding=(0, 14, 14, 14),
                background_color=FG, color=BG,
                font_family=MONO, font_size=11, font_weight="bold",
                height=40,
            ),
        )
        self.card_box = toga.Box(
            children=[self.card_title, self.card_meta, self.download_button],
            style=Pack(
                direction=COLUMN, background_color=CARD,
                padding=(0, PAGE_PAD, 14, PAGE_PAD), display="none",
            ),
        )

        # --- Progress + status (under card) ----------------------------------
        self.progress = toga.ProgressBar(
            max=100, value=0,
            style=Pack(padding=(0, PAGE_PAD, 8, PAGE_PAD), display="none"),
        )
        self.status_label = toga.Label(
            "",
            style=Pack(
                font_family=MONO, font_size=10, color=MUTED,
                padding=(0, PAGE_PAD, 18, PAGE_PAD),
            ),
        )

        # --- Footer ----------------------------------------------------------
        footer = toga.Label(
            "YOUTUBE  ·  TIKTOK  ·  INSTAGRAM  ·  X  ·  REDDIT\n"
            "VIMEO  ·  TWITCH  ·  SOUNDCLOUD  ·  1000+ MORE",
            style=Pack(
                font_family=MONO, font_size=8, color=MUTED,
                padding=(28, PAGE_PAD, 24, PAGE_PAD),
                text_align="center",
            ),
        )

        # --- Root layout -----------------------------------------------------
        content = toga.Box(
            style=Pack(direction=COLUMN, background_color=BG, flex=1),
            children=[
                wordmark,
                subtitle,
                self.url_input,
                hint,
                pill_row,
                self.fetch_button,
                self.card_box,
                self.progress,
                self.status_label,
                footer,
            ],
        )
        scroller = toga.ScrollContainer(
            content=content,
            horizontal=False,
            style=Pack(background_color=BG, flex=1),
        )

        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = scroller
        self.main_window.show()

    # ------------------------------------------------------------------
    # Pill toggle
    # ------------------------------------------------------------------
    async def on_pick_video(self, widget: toga.Widget) -> None:
        self._audio_mode = False
        self._apply_pill_style()

    async def on_pick_audio(self, widget: toga.Widget) -> None:
        self._audio_mode = True
        self._apply_pill_style()

    def _apply_pill_style(self) -> None:
        if self._audio_mode:
            self.video_pill.style.background_color = CARD
            self.video_pill.style.color = MUTED
            self.audio_pill.style.background_color = FG
            self.audio_pill.style.color = BG
        else:
            self.video_pill.style.background_color = FG
            self.video_pill.style.color = BG
            self.audio_pill.style.background_color = CARD
            self.audio_pill.style.color = MUTED

    # ------------------------------------------------------------------
    # Fetch / Download
    # ------------------------------------------------------------------
    async def on_fetch(self, widget: toga.Widget) -> None:
        text = (self.url_input.value or "").strip()
        url = text.splitlines()[0].strip() if text else ""
        if not url:
            self.status_label.text = "ENTER A URL FIRST."
            return

        self.fetch_button.enabled = False
        self.download_button.enabled = False
        self.card_box.style.display = "none"
        self.status_label.text = "FETCHING…"

        try:
            info = await asyncio.to_thread(yt_runner.fetch_info, url)
        except Exception as exc:
            self.status_label.text = f"FETCH FAILED: {exc}"
            self.fetch_button.enabled = True
            return

        self._video_info = {"url": url, **info}
        self.card_title.text = info.get("title") or "(no title)"
        meta_parts = []
        uploader = info.get("uploader") or ""
        if uploader:
            meta_parts.append(uploader.upper())
        dur = info.get("duration")
        if dur:
            mm, ss = divmod(int(dur), 60)
            meta_parts.append(f"{mm}:{ss:02d}")
        self.card_meta.text = "  ·  ".join(meta_parts)

        self.card_box.style.display = "pack"
        self.status_label.text = ""
        self.fetch_button.enabled = True
        self.download_button.enabled = True

    async def on_download(self, widget: toga.Widget) -> None:
        if not self._video_info:
            return
        url = self._video_info["url"]
        audio_only = self._audio_mode

        self.download_button.enabled = False
        self.fetch_button.enabled = False
        self.progress.value = 0
        self.progress.style.display = "pack"
        self.status_label.text = "DOWNLOADING…"

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
            self.status_label.text = f"DOWNLOAD FAILED: {exc}"
            self.download_button.enabled = True
            self.fetch_button.enabled = True
            return

        self.progress.value = 100
        name = Path(final_path).name
        self.status_label.text = f"SAVED  ·  {name}"
        self.download_button.enabled = True
        self.fetch_button.enabled = True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _set_progress(self, percent: int) -> None:
        self.progress.value = max(0, min(100, percent))

    def _resolve_download_dir(self) -> Path:
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
