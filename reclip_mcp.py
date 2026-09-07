import os
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from reclip_core import (
    download_media as _download_media,
    inspect_media as _inspect_media,
    list_supported_sites as _list_supported_sites,
    parse_clip_time,
)


mcp = MCPServer(
    name="ReClip",
    version="0.1.1",
    website_url="https://github.com/yagyaanshK/reclip",
    instructions=(
        "Use ReClip only when the user explicitly wants to inspect or download media they are "
        "authorized to save. Downloads run locally and write only to ReClip's configured download "
        "directory. Never claim that ReClip bypasses DRM, authentication, or platform restrictions."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
DOWNLOAD_ACTION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)


def _download_directory():
    configured = os.environ.get("RECLIP_MCP_DOWNLOAD_DIR")
    path = Path(configured).expanduser() if configured else Path.home() / "Downloads" / "ReClip"
    return path.resolve()


def _require_authorization(confirm_authorized):
    if not confirm_authorized:
        raise ValueError(
            "The user must explicitly confirm they are authorized to download this media"
        )


@mcp.tool(
    title="Inspect media",
    description="Inspect a public media URL and return normalized metadata and available formats without downloading it.",
    annotations=READ_ONLY,
)
def inspect_media(
    url: Annotated[str, Field(description="Public HTTP or HTTPS media page URL")],
) -> dict:
    return _inspect_media(url)


@mcp.tool(
    title="Download media",
    description=(
        "Download a complete authorized media item locally as MP4 video or MP3 audio. "
        "This writes a file and can use significant bandwidth and storage."
    ),
    annotations=DOWNLOAD_ACTION,
)
def download_media(
    url: Annotated[str, Field(description="Public HTTP or HTTPS media page URL")],
    media_format: Annotated[Literal["mp4", "mp3"], Field(description="Output media format")] = "mp4",
    quality: Annotated[
        str,
        Field(description="'best', a video height such as 1080p, or an audio bitrate such as 192k"),
    ] = "best",
    confirm_authorized: Annotated[
        bool,
        Field(description="True only after the user confirms they may download this media"),
    ] = False,
) -> dict:
    _require_authorization(confirm_authorized)
    return _download_media(
        url,
        output_directory=_download_directory(),
        media_format=media_format,
        quality=quality,
    )


@mcp.tool(
    title="Download media clip",
    description=(
        "Download only a precise authorized time range locally as MP4 video or MP3 audio. "
        "Timestamps support SS, MM:SS, or HH:MM:SS.000."
    ),
    annotations=DOWNLOAD_ACTION,
)
def download_clip(
    url: Annotated[str, Field(description="Public HTTP or HTTPS media page URL")],
    start: Annotated[str, Field(description="Inclusive clip start: SS, MM:SS, or HH:MM:SS.000")],
    end: Annotated[str, Field(description="Exclusive clip end: SS, MM:SS, or HH:MM:SS.000")],
    media_format: Annotated[Literal["mp4", "mp3"], Field(description="Output media format")] = "mp4",
    quality: Annotated[
        str,
        Field(description="'best', a video height such as 1080p, or an audio bitrate such as 192k"),
    ] = "best",
    confirm_authorized: Annotated[
        bool,
        Field(description="True only after the user confirms they may download this media"),
    ] = False,
) -> dict:
    _require_authorization(confirm_authorized)
    start_seconds = parse_clip_time(start)
    end_seconds = parse_clip_time(end)
    max_clip_seconds = int(os.environ.get("RECLIP_MCP_MAX_CLIP_SECONDS", "14400"))
    if end_seconds - start_seconds > max_clip_seconds:
        raise ValueError(f"Clip duration exceeds the configured {max_clip_seconds}-second limit")
    return _download_media(
        url,
        output_directory=_download_directory(),
        media_format=media_format,
        quality=quality,
        clip_start=start,
        clip_end=end,
    )


@mcp.tool(
    title="List supported sites",
    description=(
        "List or search extractor names provided by the locally installed yt-dlp version. "
        "An extractor name indicates potential support, not a permanent compatibility guarantee."
    ),
    annotations=READ_ONLY,
)
def list_supported_sites(
    query: Annotated[str, Field(description="Optional case-insensitive extractor-name filter")] = "",
    limit: Annotated[int, Field(ge=1, le=200, description="Maximum names to return")] = 50,
) -> dict:
    sites = _list_supported_sites()
    if query.strip():
        needle = query.strip().lower()
        sites = [site for site in sites if needle in site.lower()]
    return {"total_matches": len(sites), "sites": sites[:limit], "truncated": len(sites) > limit}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
