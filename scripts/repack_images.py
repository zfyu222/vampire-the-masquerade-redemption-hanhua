"""Rebuild Nod archives from a visually approved texture manifest."""
import argparse
import hashlib
import io
import json
import shutil
import struct
import zipfile
from collections import defaultdict
from pathlib import Path

from PIL import Image


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace_tga(original, png, source):
    size = struct.unpack_from("<HH", original, 12)
    formats = {0x18: ("RGB", "BGR", 3), 0x20: ("RGBA", "BGRA", 4)}
    if original[:3] != b"\0\0\x02" or original[16:18] not in (b"\x18\x00", b"\x20\x00", b"\x20\x08"):
        raise ValueError("Expected an uncompressed bottom-up 24-bit or 32-bit TGA")
    mode, encoding, bytes_per_pixel = formats[original[16]]
    end = 18 + bytes_per_pixel * size[0] * size[1]
    if len(original) < end:
        raise ValueError("Truncated TGA pixel data")
    old = Image.open(io.BytesIO(original)).convert("RGBA")
    old.paste((0, 0, 0, 0), (0, 0, *size), old.getchannel("A").point(lambda a: 255 if a == 0 else 0))
    image_id = hashlib.sha256(str(size).encode() + old.tobytes()).hexdigest()
    if image_id != source["image_id"] or size != (source["width"], source["height"]):
        raise ValueError("Original texture pixels or dimensions do not match image evidence")
    image = Image.open(png).convert("RGBA")
    if image.size != size:
        raise ValueError("Texture dimensions changed")
    if mode == "RGB" and image.getchannel("A").getextrema() != (255, 255):
        raise ValueError("24-bit TGA cannot store transparency")
    payload = image.convert(mode).transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", encoding)
    result = original[:18] + payload + original[end:]
    if Image.open(io.BytesIO(result)).convert("RGBA").tobytes() != image.tobytes():
        raise ValueError("Encoded TGA differs from approved PNG")
    return result


def rebuild_archive(archive, destination, replacements, raw_replacements=None):
    raw_replacements = raw_replacements or {}
    if replacements.keys() & raw_replacements.keys():
        raise ValueError("A member has both texture and raw replacement data")
    targets = replacements.keys() | raw_replacements.keys()
    with zipfile.ZipFile(archive) as original:
        names = original.namelist()
        if len(set(names)) != len(names) or not targets <= set(names):
            raise ValueError(f"Duplicate or unmapped members in {archive.name}")
        expected = {}
        with zipfile.ZipFile(destination, "x") as patched:
            patched.comment = original.comment
            for record in original.infolist():
                name = record.filename
                data = original.read(record)
                if name in replacements:
                    png, source = replacements[name]
                    if f"{record.CRC:08x}" != source["provenance"]["crc32"]:
                        raise ValueError(f"Original CRC differs: {name}")
                    data = replace_tga(data, png, source)
                if name in raw_replacements:
                    expected_source, replacement = raw_replacements[name]
                    if data != expected_source:
                        raise ValueError(f"Original bytes differ: {name}")
                    data = replacement
                expected[name] = hashlib.sha256(data).digest()
                patched.writestr(record, data)
    with zipfile.ZipFile(destination) as patched:
        if patched.namelist() != names or any(
            hashlib.sha256(patched.read(name)).digest() != expected[name] for name in names
        ):
            raise ValueError(f"Archive readback failed: {destination}")
    return {"archive": archive.name, "source_sha256": sha(archive), "patch_sha256": sha(destination),
            "total_members": len(names), "replacements": sorted(targets)}


def build(game, manifest_path, output):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "ready_for_engine_adapter" or manifest.get("stage") != "final":
        raise ValueError("Expected verified texture collection")
    images = {item["image_id"]: item for item in manifest["files"]}
    replacements = defaultdict(dict)
    for entry in manifest["entries"]:
        item = images[entry["image_id"]]
        png = (manifest_path.parent / item["path"]).resolve()
        if not png.is_relative_to(manifest_path.parent.resolve()) or sha(png) != item["sha256"]:
            raise ValueError("Approved PNG changed")
        if item["visual_evidence"]["decision"]["decision"] != "pass":
            raise ValueError("Texture requires visual approval")
        for source in entry["sources"]:
            provenance = source["provenance"]
            archive, name = provenance["asset"], provenance["texture_name"]
            if Path(archive).name != archive or Path(archive).suffix.lower() != ".nob":
                raise ValueError("Invalid Nod archive name")
            previous = replacements[archive].setdefault(name, (png, source))
            if previous != (png, source):
                raise ValueError(f"Conflicting replacement: {archive}/{name}")
    output.mkdir(parents=True)
    archives = [rebuild_archive(game / name, output / name, entries)
                for name, entries in sorted(replacements.items())]
    report = {"manifest_sha256": sha(manifest_path), "archives": archives}
    (output / "archive_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def install(game, output, backups):
    report = json.loads((output / "archive_report.json").read_text(encoding="utf-8"))
    for item in report["archives"]:
        name = item["archive"]
        if Path(name).name != name or Path(name).suffix.lower() != ".nob":
            raise ValueError("Invalid archive name")
        if sha(game / name) != item["source_sha256"] or sha(output / name) != item["patch_sha256"]:
            raise ValueError(f"Install preflight failed: {name}")
    backups.mkdir(parents=True)
    staged = []
    installed = []
    try:
        for item in report["archives"]:
            name = item["archive"]
            target = game / name
            backup = backups / name
            temp = game / f"{name}.shh.tmp"
            shutil.copy2(target, backup)
            with temp.open("xb") as stream:
                staged.append((temp, target, backup, item))
                with (output / name).open("rb") as source:
                    shutil.copyfileobj(source, stream)
            if sha(temp) != item["patch_sha256"] or sha(backup) != item["source_sha256"]:
                raise ValueError(f"Staging verification failed: {name}")
        for temp, target, backup, item in staged:
            if sha(target) != item["source_sha256"]:
                raise ValueError(f"Game archive changed during install: {target}")
            temp.replace(target)
            installed.append((target, backup, item))
            if sha(target) != item["patch_sha256"]:
                raise ValueError(f"Installed hash differs: {target}")
    except Exception:
        for target, backup, _ in reversed(installed):
            shutil.copy2(backup, target)
        raise
    finally:
        for temp, _, _, _ in staged:
            temp.unlink(missing_ok=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("output", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--manifest", type=Path)
    action.add_argument("--install-with-backups", type=Path)
    args = parser.parse_args()
    if args.manifest:
        report = build(args.game, args.manifest, args.output)
    else:
        report = install(args.game, args.output, args.install_with_backups)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
