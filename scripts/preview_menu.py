"""Assemble menu backdrop tiles at their Nod UI coordinates for visual review."""
import argparse
import io
import re
import zipfile
from pathlib import Path

from PIL import Image


QUAD = re.compile(rb"^quad mat=([^ \t]+) pos=(\d+),(\d+) size=(\d+),(\d+)", re.MULTILINE)
PROJECT = Path(__file__).resolve().parents[1]


def assemble_menu(archive, layout, size=(640, 480)):
    names = {name.casefold(): name for name in archive.namelist()}
    definition = archive.read(names[f"ui/{layout}.nui".casefold()])
    canvas = Image.new("RGBA", size)
    quads = QUAD.findall(definition)
    if not quads:
        raise ValueError(f"No backdrop quads in {layout}")
    for material, left, bottom, width, height in quads:
        material = material.decode("ascii")
        if not material.lower().endswith(".tga"):
            material += ".tga"
        left, bottom, width, height = map(int, (left, bottom, width, height))
        offset = (left, canvas.height - bottom - height)
        with Image.open(io.BytesIO(archive.read(names[f"ui/materials/{material}".casefold()]))) as tile:
            if tile.width < width or tile.height < height:
                raise ValueError(f"Quad exceeds texture dimensions: {material}")
            canvas.alpha_composite(tile.convert("RGBA").crop((0, 0, width, height)), offset)
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", choices=("mainMenu", "escapeMenu"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(PROJECT / "Game" / "Local_Eng.nob") as archive:
        preview = assemble_menu(archive, args.layout)
    with args.output.open("xb") as output:
        preview.save(output, format="PNG")


if __name__ == "__main__":
    main()
