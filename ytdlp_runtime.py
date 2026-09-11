"""Runtime yt-dlp updater for the frozen ReClip desktop app.

PyInstaller freezes yt-dlp into the executable, so the copy shipped with a
release goes stale as soon as YouTube changes its player. This module keeps a
newer yt-dlp (plus the yt-dlp-ejs challenge scripts it pins) in a per-user
directory and makes the ``--yt-dlp-worker`` subprocess import that copy instead
of the bundled one.

Layout under :func:`runtime_home`::

    <home>/current.json           {"version": "...", "ejs_version": "...", "path": "..."}
    <home>/state.json             {"last_check": <epoch seconds>}
    <home>/<version>/yt_dlp/...   extracted pure-python wheels
    <home>/<version>/yt_dlp_ejs/...

Wheels come from PyPI (JSON API + files.pythonhosted.org) and are verified
against the sha256 digest PyPI publishes before extraction.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

DIST_NAME = "yt-dlp"
EJS_DIST_NAME = "yt-dlp-ejs"
PACKAGES = ("yt_dlp", "yt_dlp_ejs")
PYPI_JSON = "https://pypi.org/pypi/{name}/json"
PYPI_VERSION_JSON = "https://pypi.org/pypi/{name}/{version}/json"
USER_AGENT = "ReClip-updater/1.0 (+https://github.com/yagyaanshK/reclip)"

DEFAULT_CHECK_INTERVAL = 24 * 60 * 60  # startup check: once a day
FAILURE_CHECK_INTERVAL = 15 * 60  # after a suspicious download failure

_lock = threading.Lock()


class UpdateError(Exception):
    """Raised when an update could not be downloaded or installed."""


# --------------------------------------------------------------------------- paths


def runtime_home() -> Path:
    override = os.environ.get("RECLIP_YTDLP_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "ReClip" / "yt-dlp"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ReClip" / "yt-dlp"
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "reclip" / "yt-dlp"


def enabled() -> bool:
    """Runtime updates only make sense for the frozen app (or when forced for tests)."""
    return bool(getattr(sys, "frozen", False) or os.environ.get("RECLIP_YTDLP_HOME"))


# ------------------------------------------------------------------------ versions


def parse_version(text) -> tuple:
    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(p) for p in parts) if parts else (0,)


def bundled_version() -> str | None:
    """Version of the yt-dlp frozen into the app (needs --copy-metadata yt-dlp)."""
    try:
        return importlib.metadata.version(DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        return None


def _read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


def installed() -> dict | None:
    """The runtime-installed yt-dlp, if the install directory is intact."""
    current = _read_json(runtime_home() / "current.json")
    if not isinstance(current, dict) or not current.get("version") or not current.get("path"):
        return None
    root = Path(current["path"])
    if not all((root / package / "__init__.py").is_file() for package in PACKAGES):
        return None
    return {"version": current["version"], "ejs_version": current.get("ejs_version"), "path": root}


def active_override() -> dict | None:
    """The runtime install, but only if it is newer than the bundled copy."""
    current = installed()
    if not current:
        return None
    bundled = bundled_version()
    if bundled and parse_version(bundled) >= parse_version(current["version"]):
        return None
    return current


def effective_version() -> str | None:
    override = active_override()
    return override["version"] if override else bundled_version()


# ----------------------------------------------------------------------- activation


class _OverrideFinder(importlib.abc.MetaPathFinder):
    """Serve selected top-level packages from a directory, ahead of PyInstaller's archive."""

    def __init__(self, root: Path, packages):
        self.root = os.fspath(root)
        self.packages = frozenset(packages)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in self.packages:
            return None
        search = [self.root] if path is None else list(path)
        return importlib.machinery.PathFinder.find_spec(fullname, search, target)


def activate(packages=PACKAGES) -> str | None:
    """Install the override finder if a newer runtime yt-dlp exists. Returns its version."""
    override = active_override()
    if not override:
        return None
    for name in list(sys.modules):
        if name.split(".")[0] in packages:
            del sys.modules[name]
    sys.meta_path.insert(0, _OverrideFinder(override["path"], packages))
    return override["version"]


# --------------------------------------------------------------------------- network


def _fetch_json(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _download(url: str, destination: Path, sha256: str, timeout: float) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=timeout) as response, open(destination, "wb") as out:
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest().lower() != sha256.lower():
        raise UpdateError(f"Checksum mismatch for {url}")


def _wheel_entry(release_json) -> dict:
    for entry in release_json.get("urls") or []:
        if entry.get("packagetype") == "bdist_wheel" and entry.get("filename", "").endswith("py3-none-any.whl"):
            return {
                "url": entry["url"],
                "sha256": entry["digests"]["sha256"],
                "filename": entry["filename"],
            }
    raise UpdateError("No universal wheel found on PyPI")


def latest_release(timeout: float = 20) -> dict:
    """Latest yt-dlp version on PyPI and its wheel location."""
    data = _fetch_json(PYPI_JSON.format(name=DIST_NAME), timeout)
    version = data["info"]["version"]
    return {"version": version, **_wheel_entry(data)}


# ------------------------------------------------------------------------ installing


def _safe_extract(wheel: Path, destination: Path, package: str) -> None:
    prefixes = (f"{package}/", f"{package}-")
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            name = member.filename
            if not name.startswith(prefixes) or ".." in name.split("/") or name.startswith("/"):
                continue
            archive.extract(member, destination)


def _pinned_ejs_version(wheel: Path) -> str | None:
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith(".dist-info/METADATA"):
                metadata = archive.read(name).decode("utf-8", "replace")
                match = re.search(r"^Requires-Dist:\s*yt-dlp-ejs\s*==\s*([\w.]+)", metadata, re.M)
                return match.group(1) if match else None
    return None


def _touch_state(**fields) -> None:
    state = _read_json(runtime_home() / "state.json") or {}
    state.update(fields)
    _write_json(runtime_home() / "state.json", state)


def last_check() -> float:
    state = _read_json(runtime_home() / "state.json") or {}
    try:
        return float(state.get("last_check") or 0)
    except (TypeError, ValueError):
        return 0.0


def update(force: bool = False, timeout: float = 120) -> dict:
    """Install the newest yt-dlp from PyPI if it beats what the app already has.

    Returns ``{"updated": bool, "version": <effective version>, "latest": <pypi version>}``.
    Raises :class:`UpdateError` (or URLError/OSError) when the network or install fails.
    """
    with _lock:
        release = latest_release(timeout=min(timeout, 20))
        _touch_state(last_check=time.time())
        current = effective_version()
        if not force and current and parse_version(current) >= parse_version(release["version"]):
            return {"updated": False, "version": current, "latest": release["version"]}

        home = runtime_home()
        home.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="staging-", dir=home))
        try:
            wheel = staging / release["filename"]
            _download(release["url"], wheel, release["sha256"], timeout)
            ejs_version = _pinned_ejs_version(wheel)
            if not ejs_version:
                raise UpdateError("Could not determine the yt-dlp-ejs version pinned by yt-dlp")
            ejs_data = _fetch_json(PYPI_VERSION_JSON.format(name=EJS_DIST_NAME, version=ejs_version), 20)
            ejs = _wheel_entry(ejs_data)
            ejs_wheel = staging / ejs["filename"]
            _download(ejs["url"], ejs_wheel, ejs["sha256"], timeout)

            target = staging / "pkg"
            _safe_extract(wheel, target, "yt_dlp")
            _safe_extract(ejs_wheel, target, "yt_dlp_ejs")
            if not all((target / package / "__init__.py").is_file() for package in PACKAGES):
                raise UpdateError("Downloaded wheels did not contain the expected packages")

            final = home / release["version"]
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
            os.replace(target, final)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        _write_json(
            home / "current.json",
            {"version": release["version"], "ejs_version": ejs_version, "path": os.fspath(final)},
        )
        for child in home.iterdir():
            if child.is_dir() and child != final and not child.name.startswith("staging-"):
                shutil.rmtree(child, ignore_errors=True)
        return {"updated": True, "version": release["version"], "latest": release["version"]}


def ensure_latest(min_interval: float = DEFAULT_CHECK_INTERVAL, timeout: float = 120) -> dict:
    """Throttled :func:`update`. Never raises; failures are reported in ``error``."""
    if not enabled():
        return {"updated": False, "version": effective_version(), "skipped": "disabled"}
    if min_interval and time.time() - last_check() < min_interval:
        return {"updated": False, "version": effective_version(), "skipped": "recently-checked"}
    try:
        return update(timeout=timeout)
    except Exception as exc:  # network down, PyPI hiccup, disk full ...
        return {"updated": False, "version": effective_version(), "error": str(exc)}


def status() -> dict:
    override = active_override()
    return {
        "enabled": enabled(),
        "bundled": bundled_version(),
        "installed": override["version"] if override else None,
        "version": effective_version(),
        "last_check": last_check() or None,
    }
