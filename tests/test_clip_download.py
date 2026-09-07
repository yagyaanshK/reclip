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


class ExtractorErrorTests(unittest.TestCase):
    def test_extracts_error_before_verbose_traceback(self):
        stderr = "debug\nERROR: [youtube] blocked\nTraceback\nraise ExtractorError"
        self.assertEqual(reclip._yt_dlp_error_message(stderr), "[youtube] blocked")


class ClipDownloadApiTests(unittest.TestCase):
    def setUp(self):
        reclip.app.config.update(TESTING=True)
        self.client = reclip.app.test_client()
        self.dns = patch("app.socket.getaddrinfo")
        self.getaddrinfo = self.dns.start()
        self.getaddrinfo.return_value = [
            (reclip.socket.AF_INET, reclip.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ]

    def tearDown(self):
        self.dns.stop()
        reclip.jobs.clear()
        reclip.rate_events.clear()

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

    @patch("app.threading.Thread")
    def test_api_rejects_private_and_non_http_urls(self, thread_cls):
        for url in ("file:///tmp/video", "http://127.0.0.1/video", "https://localhost/video"):
            with self.subTest(url=url):
                response = self.client.post("/api/download", json={"url": url})
                self.assertEqual(response.status_code, 400)
        thread_cls.assert_not_called()

    @patch("app.socket.getaddrinfo")
    @patch("app.threading.Thread")
    def test_api_rejects_hostname_resolving_to_private_network(self, thread_cls, getaddrinfo):
        getaddrinfo.return_value = [
            (reclip.socket.AF_INET, reclip.socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))
        ]

        response = self.client.post(
            "/api/download",
            json={"url": "https://internal.example/video"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Local network", response.get_json()["error"])
        thread_cls.assert_not_called()

    @patch("app.threading.Thread")
    def test_api_limits_active_jobs_per_client(self, thread_cls):
        for number in range(reclip.MAX_ACTIVE_JOBS_PER_CLIENT):
            response = self.client.post(
                "/api/download",
                json={"url": f"https://example.com/video-{number}"},
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/download",
            json={"url": "https://example.com/one-too-many"},
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("current downloads", response.get_json()["error"])

    def test_job_status_is_bound_to_originating_client(self):
        reclip.jobs["owned-job"] = {
            "status": "done",
            "client_id": "203.0.113.10",
            "created_at": reclip.time.time(),
            "filename": "example.mp4",
        }

        owned = self.client.get(
            "/api/status/owned-job",
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        other = self.client.get(
            "/api/status/owned-job",
            headers={"X-Forwarded-For": "203.0.113.11"},
        )

        self.assertEqual(owned.status_code, 200)
        self.assertEqual(other.status_code, 404)


class HostedDocumentationTests(unittest.TestCase):
    def setUp(self):
        reclip.app.config.update(TESTING=True)
        self.client = reclip.app.test_client()

    def test_machine_readable_docs_are_served(self):
        for path in ("/openapi.json", "/llms.txt", "/llms-full.txt", "/sitemap.xml"):
            with self.subTest(path=path):
                with self.client.get(path) as response:
                    self.assertEqual(response.status_code, 200)

        with self.client.get("/openapi.json") as response:
            spec = response.get_json()
        self.assertEqual(spec["openapi"], "3.1.0")
        self.assertIn("/api/download", spec["paths"])

    def test_api_docs_page_references_openapi_document(self):
        response = self.client.get("/api-docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'/openapi.json', response.data)


if __name__ == "__main__":
    unittest.main()
