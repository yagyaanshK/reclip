import json
import tempfile
import unittest
import tomllib
from pathlib import Path
from unittest.mock import patch

import reclip_cli
import reclip_core
import reclip_mcp


class UrlValidationTests(unittest.TestCase):
    def test_accepts_public_http_urls(self):
        self.assertEqual(
            reclip_core.validate_source_url("https://example.com/video"),
            "https://example.com/video",
        )

    def test_rejects_unsafe_or_non_http_urls(self):
        for value in ("file:///tmp/media", "https://localhost/video", "http://127.0.0.1/a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reclip_core.validate_source_url(value)


class QualitySelectorTests(unittest.TestCase):
    def test_maps_human_video_and_audio_quality(self):
        self.assertEqual(reclip_core.quality_selector("1080p", "mp4"), "bestvideo[height<=1080]")
        self.assertEqual(reclip_core.quality_selector("192k", "mp3"), "bestaudio[abr<=192]")
        self.assertIsNone(reclip_core.quality_selector("best", "mp4"))


class CoreOperationTests(unittest.TestCase):
    @patch("reclip_core.subprocess.run")
    def test_inspect_normalizes_extractor_output(self, run):
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = json.dumps({
            "id": "abc",
            "title": "Example",
            "duration": 42,
            "formats": [
                {"format_id": "v1", "height": 720, "vcodec": "h264", "tbr": 500},
                {"format_id": "a1", "vcodec": "none", "abr": 128, "asr": 44100},
            ],
        })

        result = reclip_core.inspect_media("https://example.com/video")

        self.assertEqual(result["title"], "Example")
        self.assertEqual(result["formats"]["video"][0]["label"], "720p")
        self.assertEqual(result["formats"]["audio"][0]["label"], "128kbps")

    @patch("reclip_core.subprocess.run")
    def test_download_returns_structured_file_result(self, run):
        def create_output(command, **_kwargs):
            template = Path(command[command.index("-o") + 1])
            Path(str(template).replace("%(ext)s", "mp3")).write_bytes(b"media")
            response = unittest.mock.Mock(returncode=0, stdout="", stderr="")
            return response

        run.side_effect = create_output
        with tempfile.TemporaryDirectory() as directory:
            result = reclip_core.download_media(
                "https://example.com/audio",
                output_directory=directory,
                media_format="mp3",
                clip_start="10.250",
                clip_end="12.750",
            )

            self.assertEqual(result["size_bytes"], 5)
            self.assertEqual(result["clip"], {"start_seconds": 10.25, "end_seconds": 12.75})
            self.assertTrue(Path(result["path"]).exists())


class CliTests(unittest.TestCase):
    def test_version_matches_package_and_registry_metadata(self):
        root = Path(__file__).parent.parent
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        server = json.loads((root / "server.json").read_text(encoding="utf-8"))
        version_action = next(
            action
            for action in reclip_cli.build_parser()._actions
            if "--version" in action.option_strings
        )

        self.assertEqual(project["version"], server["version"])
        self.assertEqual(project["version"], server["packages"][0]["version"])
        self.assertIn(project["version"], version_action.version)
        self.assertEqual(project["version"], reclip_mcp.mcp.version)

    @patch("reclip_cli.inspect_media")
    def test_json_inspect_contract(self, inspect):
        inspect.return_value = {"title": "Example"}
        with patch("builtins.print") as output:
            exit_code = reclip_cli.main(["inspect", "https://example.com/v", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.call_args.args[0])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "inspect")

    def test_json_validation_error_contract(self):
        with patch("builtins.print") as output:
            exit_code = reclip_cli.main(["inspect", "file:///tmp/video", "--json"])

        self.assertEqual(exit_code, 2)
        payload = json.loads(output.call_args.args[0])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
