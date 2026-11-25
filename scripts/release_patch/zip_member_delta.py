"""Record the unchanged ZIP member spans and the changed bytes of a Nod archive."""

import argparse
from pathlib import Path
import struct
from zipfile import ZipFile


def members(archive, data):
    entries = sorted(archive.infolist(), key=lambda item: item.header_offset)
    if not entries or entries[0].header_offset != 0 or len({x.filename for x in entries}) != len(entries):
        raise ValueError("Expected a contiguous Nod ZIP without duplicate entries")
    stops = [entry.header_offset for entry in entries[1:]] + [archive.start_dir]
    return {entry.filename: (entry.header_offset, data[entry.header_offset:end])
            for entry, end in zip(entries, stops, strict=True)}


def build(old, new, delta):
    before, after = old.read_bytes(), new.read_bytes()
    with ZipFile(old) as source, ZipFile(new) as revision:
        originals = members(source, before)
        replacements = members(revision, after)
        if list(originals) != list(replacements):
            raise ValueError("Archive member inventory or order changed")
        ops = []
        for name, (_, value) in replacements.items():
            old_at, old_value = originals[name]
            if value == old_value:
                if ops and ops[-1][0] >= 0 and ops[-1][0] + ops[-1][1] == old_at:
                    ops[-1] = (ops[-1][0], ops[-1][1] + len(value), b"")
                else:
                    ops.append((old_at, len(value), b""))
            else:
                ops.append((-1, len(value), value))
        directory = after[revision.start_dir:]
        ops.append((-1, len(directory), directory))
    with delta.open("xb") as target:
        target.write(b"RZP1" + struct.pack("<I", len(ops)))
        for offset, length, literal in ops:
            target.write(struct.pack("<qi", offset, length))
            target.write(literal)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("old", "new", "delta"):
        parser.add_argument(argument, type=Path)
    build(**vars(parser.parse_args()))
