"""Build revised text against the last verified Crimson localization."""

import argparse
import csv
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from prepare_crimson import OVERRIDES, prepare

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_chinese_glyphs import build
from repack_images import rebuild_archive
from stage_text import STEM, stage
from verify_glyph_table import verify


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("modzip", "original", "previous", "font", "output"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    out = args.output
    staged = out / "staged-text"
    report = stage(args.original, staged)
    with ZipFile(args.previous) as archive:
        changes = {}
        for name in report["members"]:
            before = archive.read(name)
            after = (staged / name).read_bytes()
            if before != after:
                changes[name] = (before, after)
    merged = out / "Local_Eng.nob"
    archive_report = rebuild_archive(args.previous, merged, {}, changes)
    prepare(args.modzip, args.original, merged, out / "overlay")
    corpus = out / "glyph-input.csv"
    with STEM.with_name(STEM.name + "_translated.csv").open(encoding="utf-8-sig", newline="") as source:
        with corpus.open("w", encoding="utf-8", newline="") as target:
            writer = csv.writer(target)
            writer.writerows(csv.reader(source))
            writer.writerows((term,) for term in OVERRIDES.values())
    glyphs = out / "glyphs"
    build(corpus, args.font, glyphs)
    glyph_report = verify(glyphs / "glyphs.bin", corpus)
    assert glyph_report["status"] == "passed"
    (out / "build.json").write_text(
        json.dumps({"translation_sha256": report["translation_sha256"], "archive": archive_report,
                    "glyphs": glyph_report}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Repacked {len(changes)} text members; {glyph_report['glyphs_per_profile']} glyphs per size")


if __name__ == "__main__":
    main()
