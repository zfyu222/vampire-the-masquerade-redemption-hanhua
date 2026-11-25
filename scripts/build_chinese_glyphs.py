"""Bake a compact grayscale glyph table for the Nod text renderer adapter."""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

MAGIC = b"NODZHGL2"
PROFILES = (10, 15, 20)
WEIGHT = 650


def sized_font(path, size):
    font = ImageFont.truetype(str(path), size)
    try:
        axes = font.get_variation_axes()
        font.set_variation_by_axes([
            min(axis["maximum"], max(axis["minimum"], WEIGHT))
            if axis["name"] == b"Weight" else axis["default"]
            for axis in axes
        ])
    except OSError:
        pass
    return font


def build(translations, font_path, destination):
    with translations.open(encoding="utf-8-sig", newline="") as stream:
        texts = [text for (text,) in csv.reader(stream, strict=True)]
    characters = sorted({ch for text in texts for ch in text if not ch.isascii() and not ch.isspace()})
    with TTFont(font_path) as font_file:
        cmap = font_file.getBestCmap()
    missing = [ch for ch in characters if ord(ch) not in cmap]
    if missing:
        raise ValueError(f"Font does not cover: {''.join(missing)}")
    table = bytearray(MAGIC + struct.pack("<II", len(characters), len(PROFILES)))
    sizes = {}
    for cell in PROFILES:
        font = sized_font(font_path, cell)
        compact = sized_font(font_path, cell - 2)
        table.extend(struct.pack("<I", cell))
        for ch in characters:
            left, top, right, bottom = font.getbbox(ch)
            if right - left > cell or bottom - top > cell:
                fitted = compact
                left, top, right, bottom = fitted.getbbox(ch)
            else:
                fitted = font
            if right - left > cell or bottom - top > cell:
                raise ValueError(f"Glyph exceeds {cell}px cell: {ch!r}")
            bitmap = Image.new("L", (cell, cell))
            offset = ((cell - right - left) // 2, (cell - bottom - top) // 2)
            ImageDraw.Draw(bitmap).text(offset, ch, font=fitted, fill=255)
            if bitmap.getbbox() is None:
                raise ValueError(f"Empty visible glyph: {ch!r}")
            table.extend(struct.pack("<I", ord(ch)))
            table.extend(bitmap.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes())
        sizes[cell] = len(characters)
    destination.mkdir(parents=True)
    (destination / "glyphs.bin").write_bytes(table)
    report = {
        "records": len(texts),
        "han_characters": sum("\u3400" <= ch <= "\u9fff" for ch in characters),
        "glyphs_by_size": sizes,
        "variable_font_weight": WEIGHT,
        "bitmap_row_order": "bottom_up",
        "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
        "translation_sha256": hashlib.sha256(translations.read_bytes()).hexdigest(),
        "table_sha256": hashlib.sha256(table).hexdigest(),
        "bytes": len(table),
    }
    (destination / "glyphs_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("translations", type=Path)
    cli.add_argument("font", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    print(json.dumps(build(args.translations, args.font, args.output), indent=2))
