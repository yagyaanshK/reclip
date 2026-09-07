import argparse
import json
import sys

from reclip_core import ReClipError, download_media, inspect_media, list_supported_sites


def _add_output_mode(parser):
    parser.add_argument("--json", action="store_true", help="Emit one structured JSON result")


def build_parser():
    parser = argparse.ArgumentParser(prog="reclip", description="Inspect and download permitted media locally")
    parser.add_argument("--version", action="version", version="ReClip CLI 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect", help="Inspect metadata and available formats")
    inspect_parser.add_argument("url")
    inspect_parser.add_argument("--timeout", type=int, default=60)
    _add_output_mode(inspect_parser)

    download_parser = commands.add_parser("download", help="Download a complete media item")
    download_parser.add_argument("url")
    download_parser.add_argument("--format", choices=("mp4", "mp3"), default="mp4")
    download_parser.add_argument("--quality", default="best")
    download_parser.add_argument("--output", default="downloads")
    download_parser.add_argument("--timeout", type=int, default=1800)
    _add_output_mode(download_parser)

    clip_parser = commands.add_parser("clip", help="Download only a precise time range")
    clip_parser.add_argument("url")
    clip_parser.add_argument("--start", required=True, help="SS, MM:SS, or HH:MM:SS.000")
    clip_parser.add_argument("--end", required=True, help="SS, MM:SS, or HH:MM:SS.000")
    clip_parser.add_argument("--format", choices=("mp4", "mp3"), default="mp4")
    clip_parser.add_argument("--quality", default="best")
    clip_parser.add_argument("--output", default="downloads")
    clip_parser.add_argument("--timeout", type=int, default=1800)
    _add_output_mode(clip_parser)

    sites_parser = commands.add_parser("sites", help="List extractors in the installed yt-dlp version")
    sites_parser.add_argument("--timeout", type=int, default=60)
    _add_output_mode(sites_parser)
    return parser


def _success(args):
    if args.command == "inspect":
        return {"ok": True, "command": "inspect", "media": inspect_media(args.url, args.timeout)}
    if args.command == "download":
        result = download_media(
            args.url,
            output_directory=args.output,
            media_format=args.format,
            quality=args.quality,
            timeout=args.timeout,
        )
        return {"ok": True, "command": "download", "result": result}
    if args.command == "clip":
        result = download_media(
            args.url,
            output_directory=args.output,
            media_format=args.format,
            quality=args.quality,
            clip_start=args.start,
            clip_end=args.end,
            timeout=args.timeout,
        )
        return {"ok": True, "command": "clip", "result": result}
    sites = list_supported_sites(args.timeout)
    return {"ok": True, "command": "sites", "count": len(sites), "sites": sites}


def _render_human(payload):
    command = payload["command"]
    if command == "inspect":
        media = payload["media"]
        print(media["title"] or media["id"])
        print(f"Duration: {media['duration'] if media['duration'] is not None else 'unknown'} seconds")
        print(f"Video qualities: {', '.join(item['label'] for item in media['formats']['video']) or 'unknown'}")
    elif command in {"download", "clip"}:
        result = payload["result"]
        print(f"Saved {result['path']} ({result['size_bytes']} bytes)")
    else:
        print("\n".join(payload["sites"]))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _success(args)
    except (ValueError, ReClipError) as exc:
        code = getattr(exc, "code", "invalid_request")
        payload = {"ok": False, "error": {"code": code, "message": str(exc)}}
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print(f"reclip: {exc}", file=sys.stderr)
        return 2 if code == "invalid_request" else 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=True))
    else:
        _render_human(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
