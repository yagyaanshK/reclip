import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client

import reclip_mcp


class McpToolTests(unittest.TestCase):
    def test_download_requires_explicit_authorization(self):
        with self.assertRaisesRegex(ValueError, "explicitly confirm"):
            reclip_mcp.download_media("https://example.com/media")

    @patch("reclip_mcp._download_media")
    def test_clip_uses_confined_configured_directory(self, download):
        download.return_value = {"path": "example.mp3"}
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"RECLIP_MCP_DOWNLOAD_DIR": directory}):
                result = reclip_mcp.download_clip(
                    "https://example.com/media",
                    "01:00.250",
                    "01:05.750",
                    media_format="mp3",
                    confirm_authorized=True,
                )

        self.assertEqual(result, {"path": "example.mp3"})
        self.assertEqual(download.call_args.kwargs["output_directory"], Path(directory).resolve())
        self.assertEqual(download.call_args.kwargs["clip_start"], "01:00.250")

    def test_rejects_clip_over_configured_limit(self):
        with patch.dict(os.environ, {"RECLIP_MCP_MAX_CLIP_SECONDS": "60"}):
            with self.assertRaisesRegex(ValueError, "60-second limit"):
                reclip_mcp.download_clip(
                    "https://example.com/media",
                    "0",
                    "61",
                    confirm_authorized=True,
                )

    @patch("reclip_mcp._list_supported_sites")
    def test_site_search_is_bounded(self, sites):
        sites.return_value = ["Youtube", "Youtube:tab", "Vimeo"]
        self.assertEqual(
            reclip_mcp.list_supported_sites("youtube", limit=1),
            {"total_matches": 2, "sites": ["Youtube"], "truncated": True},
        )


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_advertises_expected_tools(self):
        async with Client(reclip_mcp.mcp) as client:
            result = await client.list_tools()

        names = {tool.name for tool in result.tools}
        self.assertEqual(
            names,
            {"inspect_media", "download_media", "download_clip", "list_supported_sites"},
        )
        download = next(tool for tool in result.tools if tool.name == "download_media")
        self.assertFalse(download.annotations.read_only_hint)
        self.assertIn("confirm_authorized", download.input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
