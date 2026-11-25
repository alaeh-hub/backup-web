"""Draws the installer's wizard images (black + yellow, from app.ico) into installer/assets/*.bmp.

Run from anywhere:  python installer/make_images.py      (needs Pillow; only needed when the artwork changes,
the generated .bmp files are committed so the build itself does not depend on this script).
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
YELLOW = (255, 200, 0)
BLACK = (12, 12, 12)
SS = 4  # supersampling factor for smooth edges


def font(name_options, size):
    for n in name_options:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


BOLD = ["segoeuib.ttf", "arialbd.ttf"]
REG = ["segoeui.ttf", "arial.ttf"]


def logo(px):
    im = Image.open(os.path.join(HERE, "app.ico"))
    im.size = max(im.info["sizes"])
    return im.convert("RGBA").resize((px, px), Image.LANCZOS)


def centered(draw, y, text, f, fill, w):
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((w - (box[2] - box[0])) / 2 - box[0], y), text, font=f, fill=fill)


def side(w, h):
    W, H = w * SS, h * SS
    im = Image.new("RGB", (W, H), BLACK)
    # soft yellow glow behind the logo
    glow = Image.new("RGB", (W, H), BLACK)
    g = ImageDraw.Draw(glow)
    cx, cy, r = W // 2, int(H * 0.36), int(W * 0.75)
    g.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(95, 72, 0))
    glow = glow.filter(ImageFilter.GaussianBlur(W * 0.22))
    im = Image.blend(im, glow, 1.0)
    d = ImageDraw.Draw(im)
    # diagonal accent stripes at the bottom
    for i in range(3):
        off = int(H * (0.86 + i * 0.035))
        d.polygon([(0, off + int(W * 0.35)), (W, off - int(W * 0.12)), (W, off - int(W * 0.12) + SS * (3 - i) * 2),
                   (0, off + int(W * 0.35) + SS * (3 - i) * 2)], fill=YELLOW if i == 0 else (120, 92, 0))
    # logo
    size = int(W * 0.78)
    lg = logo(size)
    im.paste(lg, ((W - size) // 2, int(H * 0.36) - size // 2), lg)
    # text
    centered(d, int(H * 0.60), "File Backup", font(BOLD, int(W * 0.15)), YELLOW, W)
    centered(d, int(H * 0.60) + int(W * 0.21), "Your files, safe and", font(REG, int(W * 0.082)), (235, 235, 235), W)
    centered(d, int(H * 0.60) + int(W * 0.32), "copied in minutes.", font(REG, int(W * 0.082)), (235, 235, 235), W)
    return im.resize((w, h), Image.LANCZOS)


def small(px):
    W = px * SS
    im = Image.new("RGB", (W, W), (255, 255, 255))
    lg = logo(int(W * 0.94))
    im.paste(lg, (int(W * 0.03), int(W * 0.03)), lg)
    return im.resize((px, px), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for scale, tag in ((1.0, ""), (1.25, "-125"), (1.5, "-150"), (2.0, "-200")):
        side(round(164 * scale), round(314 * scale)).save(os.path.join(OUT, f"side{tag}.bmp"))
        small(round(55 * scale)).save(os.path.join(OUT, f"small{tag}.bmp"))
    print("wrote", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    sys.exit(main())
