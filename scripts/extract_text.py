"""Extract Nod localization fields with a byte locator for future repacking."""
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project.parents[1] / "Tools" / "localization"))
from workflow_resource_occurrences import export_occurrences


TABLE = {
    ".nls": re.compile(rb"[ \t]*(\S+)[ \t]+(\S.*?)\s*"),
    ".nvo": re.compile(rb"[ \t]*(\S+)[ \t]+\S+[ \t]+(\S.*?)\s*"),
}
TAG = re.compile(rb"</?([A-Z]+)(?:[ \t]+(.*?))?>")
counts = Counter()
records = []
contexts = {}
byte_ranges = []


def extract_member(name, data):
    suffix = Path(name).suffix
    document = None
    offset = 0
    for line_number, raw in enumerate(data.splitlines(keepends=True), 1):
        line = raw.rstrip(b"\r\n")
        start = offset
        offset += len(raw)
        if not line.strip() or line.lstrip().startswith((b"//", b";")):
            continue
        if suffix in TABLE:
            match = TABLE[suffix].fullmatch(line)
            if not match:
                raise ValueError((name, line_number, line))
            key = match[1].decode("ascii")
            value = match[2]
            begin = match.start(2)
            label = "subtitle" if suffix == ".nvo" else "string"
        else:
            tag = TAG.fullmatch(line.strip())
            if tag and tag[1] == b"TEXT":
                document = None if line.lstrip().startswith(b"</") else tag[2].split()[0].decode("ascii")
                continue
            if tag and tag[1] != b"TITLE":
                continue
            if document is None:
                raise ValueError((name, line_number, line))
            key = document
            value = tag[2].strip() if tag else line.strip()
            begin = line.index(value)
            label = "document_title" if tag else "document_text"
        if value in (b"<>", b"< >", b"-"):
            continue
        if not value.strip():
            continue
        source = value.decode("cp1252")
        locator = f"Local_Eng.nob/{name}#line={line_number}/{label}"
        records.append({"resource": locator, "source": source})
        entry = {"resource": locator, "group": name, "scene": key, "text_type": label}
        if label == "subtitle":
            entry["speaker"] = key.split("_", 1)[0]
        contexts[str(len(records))] = entry
        byte_ranges.append({"byte_offset": start + begin, "byte_length": len(value), "encoding": "cp1252"})
        counts[suffix] += 1


archive = project / "Game" / "Local_Eng.nob"
with zipfile.ZipFile(archive) as package:
    for name in sorted(package.namelist()):
        if Path(name).suffix in {".nls", ".nvo", ".ntx"}:
            extract_member(name, package.read(name))

csv = project / f"{project.name}_text.csv"
context = csv.with_suffix(".context.json")
if context.exists():
    raise FileExistsError(context)
mapping_path = csv.with_suffix(".mapping.json")
count = export_occurrences(records, csv, mapping_path)
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
for record, byte_range in zip(mapping["records"], byte_ranges, strict=True):
    record.update(byte_range)
mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
context.write_text(json.dumps(contexts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(count, dict(counts))
