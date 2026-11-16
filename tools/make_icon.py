"""Generate assets/icon.ico (and a preview PNG) for the app: a gold star and wand on a leather square."""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

S = 512
GOLD, LIGHT, LEATHER = (216, 172, 44), (243, 230, 196), (58, 36, 22)


def star(cx, cy, r_outer, r_inner, points=5, rot=-90):
    pts = []
    for i in range(points * 2):
        r = r_outer if i % 2 == 0 else r_inner
        a = math.radians(rot + i * 180 / points)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def build():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=96, fill=LEATHER, outline=GOLD, width=14)
    d.rounded_rectangle((34, 34, S - 34, S - 34), radius=74, outline=(120, 84, 40), width=6)
    # wand: tapered diagonal from bottom-left to the star
    x0, y0, x1, y1 = 120, 400, 300, 220
    d.polygon([(x0 - 14, y0 + 6), (x0 + 6, y0 + 14), (x1 + 4, y1 + 12), (x1 - 8, y1 - 2)], fill=LIGHT)
    d.polygon([(x0 - 14, y0 + 6), (x0 + 6, y0 + 14), (x0 + 30, y0 - 12), (x0 + 12, y0 - 26)], fill=(120, 70, 36))
    # glow + star
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((250, 90, 450, 290), fill=(255, 210, 80, 140))
    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(im)
    d.polygon(star(350, 190, 100, 42), fill=GOLD, outline=LIGHT)
    for (sx, sy, r) in [(200, 130, 16), (430, 330, 12), (250, 330, 10)]:
        d.polygon(star(sx, sy, r, r * 0.4, 4, -90), fill=LIGHT)
    return im


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("assets", "icon.ico")
    img = build()
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.resize((256, 256), Image.LANCZOS).save(os.path.splitext(out)[0] + "_preview.png")
    print("wrote", out)
