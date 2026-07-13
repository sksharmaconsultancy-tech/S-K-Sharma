"""S.K. Sharma & Co. brand logo generator.

Renders a professional monogram + wordmark logo as PNGs (transparent
background) that fit our forest-green brand. No LLM cost.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("/app/frontend/assets/images")
OUT.mkdir(parents=True, exist_ok=True)

FOREST = (30, 58, 95)         # navy primary  #1E3A5F
FOREST_DARK = (15, 42, 71)    # navy deep     #0F2A47
CREAM = (251, 251, 249)       # #FBFBF9
GOLD = (201, 162, 39)         # rich gold     #C9A227
INK = (26, 29, 26)


def find_font(bold: bool = False) -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return ""


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = find_font(bold=bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()


def draw_seal(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int,
              fg=FOREST, ring_thickness: int = 6) -> None:
    """Outer ring + inner filled circle."""
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=fg, width=ring_thickness)
    inner = r - ring_thickness - 8
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=fg)


def draw_monogram(img: Image.Image, cx: int, cy: int, r: int) -> None:
    """SKS monogram (tightly-kerned uniform caps) on the seal, with fingerprint arcs."""
    draw = ImageDraw.Draw(img)

    # subtle fingerprint arcs bottom half
    for i in range(3):
        rr = r - 26 - i * 12
        if rr < 20:
            break
        draw.arc(
            (cx - rr, cy - rr, cx + rr, cy + rr),
            start=210, end=330, fill=CREAM, width=2,
        )

    # SKS monogram — three uniform caps, tight kerning
    size = int(r * 0.95)
    font = load_font(size, bold=True)

    # Draw glyphs individually so we control the kerning precisely
    letters = ["S", "K", "S"]
    widths = []
    heights = []
    for l in letters:
        bbox = draw.textbbox((0, 0), l, font=font)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])

    # tight kerning: overlap letters slightly
    kern = int(size * -0.08)
    total_w = sum(widths) + kern * (len(letters) - 1)
    start_x = cx - total_w // 2
    max_h = max(heights)
    baseline_y = cy - max_h // 2 - int(size * 0.05)

    x = start_x
    for i, l in enumerate(letters):
        draw.text((x, baseline_y), l, fill=CREAM, font=font)
        x += widths[i] + kern

    # Gold tick underline
    draw.rectangle((cx - int(r * 0.55), cy + int(r * 0.55),
                    cx + int(r * 0.55), cy + int(r * 0.55) + 5),
                   fill=GOLD)


def render_full_logo(size: int, transparent: bool = True, filename: str = "logo.png") -> None:
    W = size
    H = int(size * 1.15)
    bg = (0, 0, 0, 0) if transparent else CREAM + (255,)
    img = Image.new("RGBA", (W, H), bg)
    draw = ImageDraw.Draw(img)

    r = int(W * 0.22)
    cx = W // 2
    cy = int(H * 0.34)

    # subtle drop shadow disc
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((cx - r - 4, cy - r + 6, cx + r + 4, cy + r + 12), fill=(0, 0, 0, 32))
    img.alpha_composite(shadow)

    draw_seal(draw, cx, cy, r, fg=FOREST, ring_thickness=int(r * 0.09))
    draw_monogram(img, cx, cy, r)

    # Wordmark
    wm_font = load_font(int(W * 0.09), bold=True)
    tag_font = load_font(int(W * 0.038), bold=False)
    wm = "S.K. SHARMA & CO."
    wm_w, wm_h = draw.textbbox((0, 0), wm, font=wm_font)[2:]
    y_wm = cy + r + int(r * 0.55)
    draw.text((cx - wm_w // 2, y_wm), wm, fill=FOREST_DARK, font=wm_font)

    tag = "LABOUR LAW  ·  BIOMETRIC ATTENDANCE"
    tw, th = draw.textbbox((0, 0), tag, font=tag_font)[2:]
    draw.text((cx - tw // 2, y_wm + wm_h + int(W * 0.02)),
              tag, fill=(80, 80, 78), font=tag_font)

    img.save(OUT / filename)
    print(f"Saved {OUT / filename} ({W}x{H})")


def render_seal_only(size: int, filename: str) -> None:
    """Square icon (transparent) — just the seal + monogram."""
    W = H = size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = int(W * 0.42)
    cx = cy = W // 2
    draw_seal(draw, cx, cy, r, fg=FOREST, ring_thickness=int(r * 0.09))
    draw_monogram(img, cx, cy, r)
    img.save(OUT / filename)
    print(f"Saved {OUT / filename} ({W}x{H})")


def render_app_icon(size: int, filename: str) -> None:
    """Square with forest green rounded background (for adaptive icon)."""
    W = H = size
    bg = Image.new("RGBA", (W, H), FOREST_DARK + (255,))
    draw = ImageDraw.Draw(bg)
    r = int(W * 0.38)
    cx = cy = W // 2
    # Outer ring in cream
    draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                 outline=CREAM, width=int(r * 0.08))
    # gold underline
    draw.rectangle((cx - int(r * 0.5), cy + int(r * 0.55),
                    cx + int(r * 0.5), cy + int(r * 0.55) + int(r * 0.06)),
                   fill=GOLD)

    # SKS monogram — uniform tight caps
    size_g = int(r * 0.95)
    font = load_font(size_g, bold=True)
    letters = ["S", "K", "S"]
    widths = []
    heights = []
    for l in letters:
        bb = draw.textbbox((0, 0), l, font=font)
        widths.append(bb[2] - bb[0])
        heights.append(bb[3] - bb[1])
    kern = int(size_g * -0.08)
    total_w = sum(widths) + kern * (len(letters) - 1)
    x = cx - total_w // 2
    max_h = max(heights)
    y = cy - max_h // 2 - int(size_g * 0.05)
    for i, l in enumerate(letters):
        draw.text((x, y), l, fill=CREAM, font=font)
        x += widths[i] + kern
    bg.save(OUT / filename)
    print(f"Saved {OUT / filename} ({W}x{H})")


if __name__ == "__main__":
    render_full_logo(1024, transparent=True, filename="logo.png")
    render_seal_only(512, filename="logo-mark.png")
    render_app_icon(1024, filename="icon.png")
    render_app_icon(1024, filename="adaptive-icon.png")
    # Splash: transparent full logo on cream (splash bg = brand)
    render_full_logo(1024, transparent=True, filename="splash-image.png")
    render_app_icon(256, filename="favicon.png")
