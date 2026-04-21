"""
make_icons.py  –  Generate ReClip app icons for all platforms.

Outputs:
  icons/app.ico   (Windows – multi-size ICO)
  icons/app.icns  (macOS   – icns via iconutil or Pillow fallback)
  icons/app.png   (Linux   – 512x512 PNG)

Run:  python make_icons.py
Requires: Pillow  (pip install pillow)
"""

import os
import math
from PIL import Image, ImageDraw, ImageFont

OUT = "icons"
os.makedirs(OUT, exist_ok=True)

# ── Brand colours ────────────────────────────────────────────────────────────
BG      = "#f4f1eb"   # warm off-white  (same as website)
R_COL   = "#3a3a38"   # charcoal        ("Re")
C_COL   = "#e85d2a"   # burnt-orange    ("Clip")

# ── Draw one square frame at `size` pixels ───────────────────────────────────
def make_frame(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square background  (radius ≈ 25 % of size, matching rx=32/128)
    r = max(2, size // 4)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    # Typography – try to use a real serif, fall back to Pillow default
    font_size = int(size * 0.74)
    font = None
    for candidate in [
        "GeorgiaItalic.ttf", "Georgia.ttf", "georgia.ttf",
        "Times New Roman.ttf", "timesbd.ttf",
    ]:
        try:
            font = ImageFont.truetype(candidate, font_size)
            break
        except OSError:
            pass
    if font is None:
        font = ImageFont.load_default()

    # --- "R" (left half, upright) ---
    bbox_r = draw.textbbox((0, 0), "R", font=font)
    tw_r   = bbox_r[2] - bbox_r[0]
    th_r   = bbox_r[3] - bbox_r[1]

    # --- "C" (right half, draw with slight slant via affine transform) ---
    bbox_c = draw.textbbox((0, 0), "C", font=font)
    tw_c   = bbox_c[2] - bbox_c[0]
    th_c   = bbox_c[3] - bbox_c[1]

    # Place them so total width ≈ 75 % of the frame, centred
    gap    = int(size * 0.03)
    total  = tw_r + gap + tw_c
    x0     = (size - total) // 2

    # Vertical centre based on cap-height (bbox top is usually the ascender)
    cy = (size - th_r) // 2 - bbox_r[1]

    draw.text((x0 - bbox_r[0], cy), "R", font=font, fill=R_COL)

    # Draw "C" on a tmp layer and paste (enables us to italicise via shear)
    c_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    c_draw  = ImageDraw.Draw(c_layer)
    cx = x0 + tw_r + gap
    c_draw.text((cx - bbox_c[0], cy), "C", font=font, fill=C_COL)

    # Shear the C layer ~12° to fake italic
    shear  = -0.21          # tangens of ~12°
    affine = (1, shear, -shear * size / 2,   0, 1, 0)
    c_layer = c_layer.transform(c_layer.size, Image.AFFINE, affine,
                                resample=Image.BICUBIC)
    img = Image.alpha_composite(img, c_layer)
    return img


# ── Build all sizes ───────────────────────────────────────────────────────────
SIZES = [16, 32, 48, 64, 128, 256, 512]
frames = {s: make_frame(s) for s in SIZES}

# PNG (Linux)
frames[512].save(os.path.join(OUT, "app.png"))
print("[ok] icons/app.png")

# ICO (Windows) – embed multiple sizes
ico_sizes = [(s, s) for s in [16, 32, 48, 64, 128, 256]]
frames[256].save(
    os.path.join(OUT, "app.ico"),
    format="ICO",
    sizes=ico_sizes,
    append_images=[frames[s].resize((s, s), Image.LANCZOS) for s in [16, 32, 48, 64, 128]],
)
print("[ok] icons/app.ico")

# ICNS (macOS) – write a minimal icns manually, or use iconutil when on macOS
try:
    import subprocess, shutil, tempfile, struct

    if shutil.which("iconutil"):           # macOS native path
        iconset = tempfile.mkdtemp(suffix=".iconset")
        for s, n in [(16,"16x16"),(32,"16x16@2x"),(32,"32x32"),
                     (64,"32x32@2x"),(128,"128x128"),(256,"128x128@2x"),
                     (256,"256x256"),(512,"256x256@2x"),(512,"512x512")]:
            frames[s].save(os.path.join(iconset, f"icon_{n}.png"))
        icns_path = os.path.join(OUT, "app.icns")
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)
        print("[ok] icons/app.icns  (iconutil)")
    else:
        raise RuntimeError("iconutil not found")

except Exception:
    # Fallback: write a bare-bones ICNS that embeds the 512-px PNG
    # (Pillow doesn't support ICNS save natively on non-macOS)
    png_bytes = b""
    import io
    buf = io.BytesIO()
    frames[512].save(buf, format="PNG")
    png_bytes = buf.getvalue()

    MAGIC   = b"icns"
    IC09    = b"ic09"   # 512×512 PNG slot
    entry   = IC09 + (8 + len(png_bytes)).to_bytes(4, "big") + png_bytes
    total   = 8 + len(entry)
    with open(os.path.join(OUT, "app.icns"), "wb") as f:
        f.write(MAGIC + total.to_bytes(4, "big") + entry)
    print("[ok] icons/app.icns  (fallback PNG-in-ICNS)")
