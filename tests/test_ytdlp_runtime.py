import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import reclip_core
import ytdlp_runtime


def _wheel_bytes(package, version, metadata_extra=""):
    """A minimal pure-python wheel containing <package>/__init__.py and dist-info."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{package}/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr(f"{package}/sub.py", "VALUE = 'sub'\n")
        archive.writestr(f"{package}-{version}.dist-info/METADATA",
                         f"Name: {package}\nVersion: {version}\n{metadata_extra}")
        archive.writestr("../evil.py", "print('zip slip')\n")
    return buffer.getvalue()


class DescribeErrorTests(unittest.TestCase):
    def test_classifies_common_failures(self):
        cases = {
            "ERROR: unable to download video data: HTTP Error 403: Forbidden": ("platform_denied", True),
            "ERROR: [youtube] x: Sign in to confirm you’re not a bot": ("bot_check", True),
            "ERROR: [youtube] x: Requested format is not available": ("player_changed", True),
            "ERROR: [youtube] x: No supported JavaScript runtime could be found": ("js_runtime_missing", False),
            "ERROR: [youtube] x: Video unavailable": ("unavailable", False),
            "ERROR: [youtube] x: Private video. Sign in if you've been granted access": ("private", False),
            "ERROR: Unsupported URL: https://example.com/": ("unsupported_url", False),
            "ERROR: HTTP Error 404: Not Found": ("not_found", False),
            "ERROR: HTTP Error 429: Too Many Requests": ("rate_limited", False),
            "ERROR: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>": ("network", False),
        }
        for raw, (code, outdated) in cases.items():
            with self.subTest(raw=raw):
                described = reclip_core.describe_error(raw)
                self.assertEqual(described["code"], code)
                self.assertEqual(described["maybe_outdated"], outdated)
                self.assertEqual(described["detail"], raw)
                self.assertTrue(described["message"])

    def test_unknown_error_is_truncated(self):
        raw = "ERROR: " + "x" * 300
        described = reclip_core.describe_error(raw)
        self.assertEqual(described["code"], "unknown")
        self.assertFalse(described["maybe_outdated"])
        self.assertLessEqual(len(described["message"]), 120)

    def test_empty_error_uses_fallback(self):
        self.assertEqual(reclip_core.describe_error("")["message"], "Download failed")


class RuntimeHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "yt-dlp"
        self.env = patch.dict(os.environ, {"RECLIP_YTDLP_HOME": os.fspath(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _fake_network(self, version="2099.1.1", ejs_version="9.9.9"):
        wheels = {
            "https://files/yt_dlp.whl": _wheel_bytes(
                "yt_dlp", version, f"Requires-Dist: yt-dlp-ejs=={ejs_version}; extra == 'default'\n"),
            "https://files/yt_dlp_ejs.whl": _wheel_bytes("yt_dlp_ejs", ejs_version),
        }
        import hashlib

        def release(url_key, filename):
            data = wheels[url_key]
            return {"packagetype": "bdist_wheel", "filename": filename, "url": url_key,
                    "digests": {"sha256": hashlib.sha256(data).hexdigest()}}

        pages = {
            ytdlp_runtime.PYPI_JSON.format(name="yt-dlp"): {
                "info": {"version": version},
                "urls": [{"packagetype": "sdist", "filename": "x.tar.gz", "url": "u", "digests": {"sha256": ""}},
                         release("https://files/yt_dlp.whl", f"yt_dlp-{version}-py3-none-any.whl")],
            },
            ytdlp_runtime.PYPI_VERSION_JSON.format(name="yt-dlp-ejs", version=ejs_version): {
                "info": {"version": ejs_version},
                "urls": [release("https://files/yt_dlp_ejs.whl", f"yt_dlp_ejs-{ejs_version}-py3-none-any.whl")],
            },
        }

        def fetch_json(url, timeout):
            return pages[url]

        def download(url, destination, sha256, timeout):
            data = wheels[url]
            Path(destination).write_bytes(data)
            if hashlib.sha256(data).hexdigest() != sha256:
                raise ytdlp_runtime.UpdateError("Checksum mismatch")

        return patch.object(ytdlp_runtime, "_fetch_json", fetch_json), patch.object(ytdlp_runtime, "_download", download)

    def test_enabled_when_home_forced(self):
        self.assertTrue(ytdlp_runtime.enabled())
        self.assertEqual(ytdlp_runtime.runtime_home(), self.home)

    def test_update_installs_newer_version_and_records_state(self):
        fetch, download = self._fake_network()
        with fetch, download, patch.object(ytdlp_runtime, "bundled_version", return_value="2026.8.19"):
            outcome = ytdlp_runtime.update()
            self.assertTrue(outcome["updated"])
            self.assertEqual(outcome["version"], "2099.1.1")
            installed = ytdlp_runtime.installed()
            self.assertEqual(installed["version"], "2099.1.1")
            self.assertEqual(installed["ejs_version"], "9.9.9")
            self.assertTrue((installed["path"] / "yt_dlp" / "__init__.py").is_file())
            self.assertTrue((installed["path"] / "yt_dlp_ejs" / "__init__.py").is_file())
            self.assertFalse((self.home / "evil.py").exists())
            self.assertFalse((self.home / "2099.1.1" / "evil.py").exists())
            self.assertGreater(ytdlp_runtime.last_check(), 0)
            self.assertEqual(ytdlp_runtime.effective_version(), "2099.1.1")
            # Second call: already newest, nothing downloaded again.
            self.assertFalse(ytdlp_runtime.update()["updated"])

    def test_update_skips_when_bundled_is_newer(self):
        fetch, download = self._fake_network(version="2020.1.1")
        with fetch, download, patch.object(ytdlp_runtime, "bundled_version", return_value="2026.8.19"):
            outcome = ytdlp_runtime.update()
        self.assertFalse(outcome["updated"])
        self.assertEqual(outcome["version"], "2026.8.19")
        self.assertIsNone(ytdlp_runtime.installed())

    def test_override_ignored_once_app_ships_newer_ytdlp(self):
        fetch, download = self._fake_network(version="2027.1.1")
        with fetch, download, patch.object(ytdlp_runtime, "bundled_version", return_value="2026.8.19"):
            ytdlp_runtime.update()
        with patch.object(ytdlp_runtime, "bundled_version", return_value="2028.1.1"):
            self.assertIsNone(ytdlp_runtime.active_override())
            self.assertEqual(ytdlp_runtime.effective_version(), "2028.1.1")

    def test_checksum_mismatch_aborts_install(self):
        fetch, download = self._fake_network()
        with fetch, patch.object(ytdlp_runtime, "_download",
                                 side_effect=ytdlp_runtime.UpdateError("Checksum mismatch")), \
                patch.object(ytdlp_runtime, "bundled_version", return_value="2026.8.19"):
            with self.assertRaises(ytdlp_runtime.UpdateError):
                ytdlp_runtime.update()
        self.assertIsNone(ytdlp_runtime.installed())
        self.assertEqual([p.name for p in self.home.iterdir() if p.is_dir()], [])

    def test_ensure_latest_is_throttled_and_never_raises(self):
        with patch.object(ytdlp_runtime, "update", side_effect=OSError("offline")) as update:
            first = ytdlp_runtime.ensure_latest(min_interval=0)
            self.assertIn("offline", first["error"])
            self.assertEqual(update.call_count, 1)
        ytdlp_runtime._touch_state(last_check=ytdlp_runtime.time.time())
        with patch.object(ytdlp_runtime, "update") as update:
            self.assertEqual(ytdlp_runtime.ensure_latest(min_interval=3600)["skipped"], "recently-checked")
            update.assert_not_called()

    def test_activate_serves_packages_from_override_dir(self):
        fetch, download = self._fake_network(version="2099.1.1")
        with fetch, download, patch.object(ytdlp_runtime, "bundled_version", return_value="2026.8.19"):
            ytdlp_runtime.update()
        # Import in a fresh interpreter so this process' real yt_dlp stays untouched.
        # There, bundled_version() is the pip-installed yt-dlp (2026.x), older than 2099.1.1.
        code = (
            "import ytdlp_runtime; v = ytdlp_runtime.activate();"
            "import yt_dlp, yt_dlp.sub, yt_dlp_ejs;"
            "print(v, yt_dlp.__version__, yt_dlp.sub.VALUE, yt_dlp_ejs.__version__)"
        )
        env = {**os.environ, "PYTHONPATH": os.fspath(Path(__file__).resolve().parents[1])}
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["2099.1.1", "2099.1.1", "sub", "9.9.9"])


class SelfHealTests(unittest.TestCase):
    """app._run_ytdlp updates and retries once on failures a newer yt-dlp typically fixes."""

    def setUp(self):
        import app
        self.app = app

    def _completed(self, code, stderr=""):
        return subprocess.CompletedProcess(args=[], returncode=code, stdout="{}", stderr=stderr)

    def test_retries_after_successful_update(self):
        runs = [self._completed(1, "ERROR: HTTP Error 403: Forbidden"), self._completed(0)]
        with patch.object(self.app.subprocess, "run", side_effect=runs) as run, \
                patch.object(ytdlp_runtime, "enabled", return_value=True), \
                patch.object(ytdlp_runtime, "ensure_latest", return_value={"updated": True, "version": "2099.1.1"}):
            result, error = self.app._run_ytdlp(["yt-dlp"], timeout=5)
        self.assertIsNone(error)
        self.assertEqual(run.call_count, 2)

    def test_reports_up_to_date_when_nothing_to_install(self):
        with patch.object(self.app.subprocess, "run", return_value=self._completed(1, "ERROR: HTTP Error 403: Forbidden")) as run, \
                patch.object(ytdlp_runtime, "enabled", return_value=True), \
                patch.object(ytdlp_runtime, "ensure_latest", return_value={"updated": False, "version": "2026.8.19"}), \
                patch.object(ytdlp_runtime, "effective_version", return_value="2026.8.19"):
            _, error = self.app._run_ytdlp(["yt-dlp"], timeout=5)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(error["code"], "platform_denied")
        self.assertIn("already the newest", error["message"])
        self.assertEqual(error["ytdlp"], "2026.8.19")

    def test_non_outdated_errors_do_not_trigger_update(self):
        with patch.object(self.app.subprocess, "run", return_value=self._completed(1, "ERROR: [youtube] x: Video unavailable")), \
                patch.object(ytdlp_runtime, "enabled", return_value=True), \
                patch.object(ytdlp_runtime, "ensure_latest") as ensure:
            _, error = self.app._run_ytdlp(["yt-dlp"], timeout=5)
        ensure.assert_not_called()
        self.assertEqual(error["code"], "unavailable")
        self.assertEqual(error["message"], "This video is unavailable or was removed.")


if __name__ == "__main__":
    unittest.main()
