"""Inspect Nod's original 8-bit bitmap font resources without changing them."""
import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path

from PIL import Image

HEADER = struct.Struct("<II")
GLYPH = struct.Struct("<6i")
GLYPH_COUNT = 256
ATLAS_OFFSET = HEADER.size + GLYPH.size * GLYPH_COUNT + 44


def parse(data):
    nominal_height, width = HEADER.unpack_from(data)
    if not width or len(data) <= ATLAS_OFFSET or (len(data) - ATLAS_OFFSET) % width:
        raise ValueError("Invalid NFD bitmap dimensions")
    height = (len(data) - ATLAS_OFFSET) // width
    table = list(GLYPH.iter_unpack(data[HEADER.size:HEADER.size + GLYPH.size * GLYPH_COUNT]))
    for _, _, glyph_width, glyph_height, _, x in table:
        if min(glyph_width, glyph_height) < 0 or glyph_height > height:
            raise ValueError("Invalid NFD glyph dimensions")
        if glyph_width and (x < 0 or x + glyph_width > width):
            raise ValueError("Glyph offset exceeds atlas")
    atlas = Image.frombytes("L", (width, height), data[ATLAS_OFFSET:])
    return nominal_height, table, atlas.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def inspect(archive, output):
    output.mkdir(parents=True)
    summary = {}
    with zipfile.ZipFile(archive) as package:
        for item in package.namelist():
            if not item.lower().endswith(".nfd"):
                continue
            data = package.read(item)
            nominal_height, table, atlas = parse(data)
            path = output / (Path(item).name + ".png")
            atlas.save(path)
            summary[item] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "nominal_height": nominal_height,
                "atlas_dimensions": list(atlas.size),
                "index_slots": len(table),
                "nonempty_slots": sum(width > 0 and height > 0 for _, _, width, height, _, _ in table),
                "atlas_byte_offset": ATLAS_OFFSET,
                "preview": path.name,
            }
    (output / "nfd_report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    print(json.dumps(inspect(args.archive, args.output), indent=2))
