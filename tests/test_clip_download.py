import unittest
from unittest.mock import patch

import app as reclip


class ClipTimeTests(unittest.TestCase):
    def test_parses_supported_timestamp_formats(self):
        cases = {
            "90": 90.0,
            "01:30": 90.0,
            "01:02:03.456": 3723.456,
            "00:10.125": 10.125,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertAlmostEqual(reclip._parse_clip_time(value), expected)

    def test_rejects_invalid_timestamp_components(self):
        for value in ("", "1:60", "1:60:00", "1:2:3:4", "abc", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    reclip._parse_clip_time(value)

    def test_validates_range_and_duration(self):
        self.assertEqual(
            reclip._validate_clip_range("01:02.125", "01:05.750", 70),
            (62.125, 65.75),
        )
        self.assertEqual(reclip._validate_clip_range(None, None, 70), (None, None))

        invalid = (
            ("10", None, 70),
            ("10", "10", 70),
            ("20", "10", 70),
            ("10", "71", 70),
        )
        for start, end, duration in invalid:
            with self.subTest(start=start, end=end, duration=duration):
                with self.assertRaises(ValueError):
                    reclip._validate_clip_range(start, end, duration)

    def test_formats_safe_timestamp_for_clip_filename(self):
        self.assertEqual(reclip._format_filename_time(65.25), "01-05.250")
        self.assertEqual(reclip._format_filename_time(3665.25), "01-01-05.250")


class ClipCommandTests(unittest.TestCase):
    def test_clipped_download_uses_section_and_exact_cut_flags(self):
        command = reclip._build_download_command(
            "output.%(ext)s",
            "https://example.com/video",
            "video",
            "137",
            clip_start=62.125,
            clip_end=64.5,
        )

        section_index = command.index("--download-sections")
        self.assertEqual(command[section_index + 1], "*62.125-64.5")
        self.assertIn("--force-keyframes-at-cuts", command)
        self.assertEqual(command[-1], "https://example.com/video")

    def test_full_download_has_no_section_flags(self):
        command = reclip._build_download_command(
            "output.%(ext)s",
            "https://example.com/video",
            "audio",
            None,
        )
        self.assertNotIn("--download-sections", command)
        self.assertNotIn("--force-keyframes-at-cuts", command)


class ClipDownloadApiTests(unittest.TestCase):
    def setUp(self):
        reclip.app.config.update(TESTING=True)
        self.client = reclip.app.test_client()

    def tearDown(self):
        reclip.jobs.clear()

    @patch("app.threading.Thread")
    def test_api_passes_validated_clip_to_background_job(self, thread_cls):
        response = self.client.post(
            "/api/download",
            json={
                "url": "https://example.com/video",
                "format": "audio",
                "clip_start": "00:10.250",
                "clip_end": "00:20.750",
                "duration": 60,
            },
        )

        self.assertEqual(response.status_code, 200)
        job = reclip.jobs[response.get_json()["job_id"]]
        self.assertEqual(job["clip_start"], 10.25)
        self.assertEqual(job["clip_end"], 20.75)
        thread_cls.return_value.start.assert_called_once_with()

    @patch("app.threading.Thread")
    def test_api_rejects_invalid_clip_before_starting_job(self, thread_cls):
        response = self.client.post(
            "/api/download",
            json={
                "url": "https://example.com/video",
                "clip_start": "00:30",
                "clip_end": "00:10",
                "duration": 60,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("after clip start", response.get_json()["error"])
        thread_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
