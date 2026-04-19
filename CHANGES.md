# Changes from Original Repository

This fork ([yagyaanshK/reclip](https://github.com/yagyaanshK/reclip)) is based on [averygan/reclip](https://github.com/averygan/reclip) and has been modified for deployment on **Hugging Face Spaces**.

Live deployment: https://huggingface.co/spaces/Daddy23/reclip

---

## Modified Files

### `Dockerfile`
- Added non-root user `appuser` (UID 1000) — required by HF Spaces security policy
- Created `/app/downloads` directory with correct ownership for `appuser`
- Switched container to run as `appuser` via `USER appuser`
- Changed exposed port from `8899` to `7860` (HF Spaces default)
- Added `ENV PORT=7860` environment variable

### `app.py`
- Changed default port fallback from `8899` to `7860` (line 169)

### `README.md`
- Added HF Spaces YAML frontmatter:
  - `sdk: docker`
  - `app_port: 7860`
  - `license: mit`
  - `short_description`, `emoji`, `colorFrom`, `colorTo`, `pinned`

### `.gitignore`
- Added `.hf_token` to prevent accidentally committing the Hugging Face access token

## New Files

### `entrypoint.sh`
- Entrypoint script that sets DNS servers (Google `8.8.8.8`, Cloudflare `1.1.1.1`) at container startup
- Fixes DNS resolution failure (`Errno -5`) that occurs inside HF Spaces Docker containers when `yt-dlp` tries to reach external sites like YouTube

### `.hf_token` (gitignored)
- Local-only file storing the Hugging Face access token for pushing to the Space

### `CHANGES.md`
- This file

## Removed Files

### `assets/preview-mp3.png` and `assets/preview.mp4`
- Removed from the HF Spaces deployment branch (`hf-deploy`) only
- HF Spaces rejects pushes containing binary files
- These are README demo assets and not needed for the app to function

---

## Summary

All changes are deployment-related. **No application logic was modified.** The app behaves identically to the original — only the container configuration was adapted for HF Spaces.
