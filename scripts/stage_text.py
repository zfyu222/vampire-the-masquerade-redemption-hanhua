"""Validate all Nod text locations and build UTF-8 resource inputs for renderer testing."""
import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

from repack_images import sha

PROJECT = Path(__file__).resolve().parents[1]
STEM = PROJECT / f"{PROJECT.name}_text"
LOCATOR = re.compile(r"Local_Eng\.nob/(.+)#line=([0-9]+)/(string|subtitle|document_title|document_text)")


def read_column(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [value for (value,) in csv.reader(stream, strict=True)]


def stage(archive, destination):
    source_path = STEM.with_suffix(".csv")
    translated_path = STEM.with_name(STEM.name + "_translated.csv")
    mapping = json.loads(STEM.with_suffix(".mapping.json").read_text(encoding="utf-8"))
    validation = json.loads((PROJECT / "TranslateFiles/reports/final_validation.json").read_text(encoding="utf-8"))
    source_hash, target_hash = sha(source_path), sha(translated_path)
    if (validation["status"] != "passed" or source_hash != validation["source_sha256"]
            or source_hash != mapping["source_sha256"] or target_hash != validation["translation_sha256"]):
        raise ValueError("Input differs from approved translation or extraction")
    source, target = read_column(source_path), read_column(translated_path)
    if len(source) != validation["records"]:
        raise ValueError("Source record count differs from validation")
    groups = defaultdict(list)
    for ordinal, (record, old, new) in enumerate(zip(mapping["records"], source, target, strict=True), 1):
        match = LOCATOR.fullmatch(record["resource"])
        if not match or record["ordinal"] != ordinal or record["encoding"] != "cp1252":
            raise ValueError(f"Invalid resource binding at record {ordinal}")
        if hashlib.sha256(old.encode()).hexdigest() != record["source_sha256"]:
            raise ValueError(f"Original text hash differs at record {ordinal}")
        member, line, _kind = match.groups()
        if any(character in new for character in "\r\n\0"):
            raise ValueError(f"Invalid line break or NUL at record {ordinal}")
        groups[member].append((record["byte_offset"], record["byte_length"], int(line), old, new))
    payloads = {}
    with zipfile.ZipFile(archive) as original:
        for member, edits in groups.items():
            raw = original.read(member)
            cursor = 0
            result = bytearray()
            for offset, length, line, old, new in sorted(edits):
                if offset < cursor or raw[offset:offset + length] != old.encode("cp1252"):
                    raise ValueError(f"Overlapping or mismatched original bytes: {member}:{line}")
                if raw.count(b"\n", 0, offset) + 1 != line:
                    raise ValueError(f"Original line differs: {member}:{line}")
                result.extend(raw[cursor:offset].decode("cp1252").encode("utf-8"))
                result.extend(new.encode("utf-8"))
                cursor = offset + length
            result.extend(raw[cursor:].decode("cp1252").encode("utf-8"))
            if result.count(b"\n") != raw.count(b"\n"):
                raise ValueError(f"Line count changed: {member}")
            payloads[member] = bytes(result)
    destination.mkdir(parents=True)
    for member, data in payloads.items():
        path = (destination / member).resolve()
        if not path.is_relative_to(destination.resolve()):
            raise ValueError(f"Invalid member path: {member}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    report = {
        "status": "renderer_test_input",
        "archive_sha256": sha(archive),
        "source_sha256": source_hash,
        "translation_sha256": target_hash,
        "records": len(source),
        "encoding": "utf-8",
        "members": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
        "installed": False,
    }
    (destination / "text_stage_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    report = stage(args.archive, args.destination)
    print(f"{report['records']} validated records in {len(report['members'])} test resources")
