"""Prepare the generated environment plate at the final 4K raster size."""

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "assets" / "rift-imagegen-plate-color-v4.png"
OUTPUT = ROOT / "assets" / "rift-imagegen-plate-color-v4-4k-source.png"


def main() -> None:
    image = Image.open(SOURCE).convert("RGB")
    image = image.resize((3840, 2160), Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.35, percent=125, threshold=2))
    image = ImageEnhance.Sharpness(image).enhance(1.08)
    image.save(OUTPUT, format="PNG", optimize=True)


if __name__ == "__main__":
    main()
