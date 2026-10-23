# Generate and save the weather app icons

import os
from PIL import Image, ImageDraw

ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "survivor", "icons")


def create_weather_icon(size: int, filename: str):
    os.makedirs(ICON_DIR, exist_ok=True)
    img = Image.new("RGBA", (size, size), (29, 111, 114, 255))
    draw = ImageDraw.Draw(img)

    # Draw a calm sun + cloud weather emblem
    sun_r = int(size * 0.16)
    sun_cx, sun_cy = int(size * 0.38), int(size * 0.38)
    draw.ellipse(
        (sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r),
        fill=(253, 224, 71, 255),
    )

    cloud_y = int(size * 0.50)
    draw.rounded_rectangle(
        (int(size * 0.25), cloud_y, int(size * 0.78), int(size * 0.72)),
        radius=int(size * 0.11),
        fill=(248, 246, 242, 255),
    )
    draw.ellipse(
        (int(size * 0.34), int(size * 0.38), int(size * 0.62), int(size * 0.65)),
        fill=(248, 246, 242, 255),
    )

    out_path = os.path.join(ICON_DIR, filename)
    img.save(out_path, "PNG")
    print(f"Created {out_path}")


if __name__ == "__main__":
    create_weather_icon(192, "icon-192.png")
    create_weather_icon(512, "icon-512.png")