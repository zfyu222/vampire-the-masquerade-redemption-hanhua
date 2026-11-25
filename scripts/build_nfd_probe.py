"""Build a lab-only Chinese glyph probe, separate from the installed game."""
import argparse
import json
import re
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from inspect_nfd import ATLAS_OFFSET, GLYPH, HEADER, parse
from repack_images import sha

SLOTS = {"W": "输", "M": "入"}
LABEL = re.compile(rb"(?m)^(UI_NET_ENTERKEY[ \t]+)Enter CD-Key(?=\r?$)")


def replace_font(data, font_path):
    nominal, table, atlas = parse(data)
    header = bytearray(data[:ATLAS_OFFSET])
    for slot, character in SLOTS.items():
        index = ord(slot)
        _, _, width, _, advance, x = table[index]
        font = ImageFont.truetype(font_path, min(nominal, width, atlas.height))
        left, top, right, bottom = font.getbbox(character)
        glyph = Image.new("L", (width, atlas.height))
        xy = ((width - right + left) // 2 - left, (atlas.height - bottom + top) // 2 - top)
        ImageDraw.Draw(glyph).text(xy, character, font=font, fill=255)
        atlas.paste(glyph, (x, 0))
        GLYPH.pack_into(header, HEADER.size + index * GLYPH.size, 0, 0, width, atlas.height, advance, x)
    result = bytes(header) + atlas.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
    parse(result)
    return result


def build(archive, destination, font):
    destination.mkdir(parents=True)
    output = destination / archive.name
    replacements = {}
    with zipfile.ZipFile(archive) as original:
        for name in original.namelist():
            if name.lower().endswith(".nfd"):
                replacements[name] = replace_font(original.read(name), str(font))
        label = "strings/system.nls"
        replacement, count = LABEL.subn(rb"\g<1>WM CD-Key", original.read(label))
        if count != 1 or len(replacements) != 6:
            raise ValueError("Expected the six original fonts and one probe label")
        replacements[label] = replacement
        with zipfile.ZipFile(output, "x") as patched:
            for member in original.infolist():
                patched.writestr(member, replacements.get(member.filename, original.read(member)))
    with zipfile.ZipFile(output) as patched:
        if patched.testzip() is not None or any(patched.read(name) != data for name, data in replacements.items()):
            raise ValueError("Glyph probe archive did not pass readback")
    receipt = {"source_sha256": sha(archive), "probe_sha256": sha(output), "test_label": "输入 CD-Key",
               "scope": "startup glyph experiment", "changed_members": sorted(replacements), "installed": False}
    (destination / "probe_report.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")
    return receipt


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("font", type=Path)
    args = cli.parse_args()
    print(json.dumps(build(args.archive, args.output, args.font), ensure_ascii=True, indent=2))
