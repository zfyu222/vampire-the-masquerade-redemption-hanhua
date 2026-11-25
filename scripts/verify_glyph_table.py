"""Read back the whole glyph sidecar and verify it against the approved text."""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path

from build_chinese_glyphs import MAGIC, PROFILES


def verify(table_path, translations):
    with translations.open(encoding="utf-8-sig", newline="") as stream:
        characters = sorted({ord(ch) for (row,) in csv.reader(stream, strict=True)
                             for ch in row if not ch.isascii() and not ch.isspace()})
    data = table_path.read_bytes()
    if data[:len(MAGIC)] != MAGIC:
        raise ValueError("Invalid glyph table version")
    offset = len(MAGIC)
    count, profiles = struct.unpack_from("<II", data, offset)
    offset += 8
    if (count, profiles) != (len(characters), len(PROFILES)):
        raise ValueError("Glyph count or profile coverage differs")
    for expected_cell in PROFILES:
        cell, = struct.unpack_from("<I", data, offset)
        offset += 4
        if cell != expected_cell:
            raise ValueError("Unexpected font profile")
        for expected_code in characters:
            code, = struct.unpack_from("<I", data, offset)
            offset += 4
            ink = data[offset:offset + cell * cell]
            if code != expected_code or len(ink) != cell * cell or not any(ink):
                raise ValueError(f"Bad glyph U+{expected_code:04X} in {cell}px profile")
            offset += cell * cell
    if offset != len(data):
        raise ValueError("Unexpected trailing bytes")
    return {"status": "passed", "profiles": list(PROFILES), "glyphs_per_profile": count,
            "table_sha256": hashlib.sha256(data).hexdigest()}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("table", type=Path)
    cli.add_argument("translations", type=Path)
    args = cli.parse_args()
    print(json.dumps(verify(args.table, args.translations), indent=2))
