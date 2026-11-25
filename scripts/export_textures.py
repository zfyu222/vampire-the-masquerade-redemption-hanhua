"""Export Nod TGA entries for OCR, retaining their archive member paths."""
import io
import json
import sys
import zipfile
from pathlib import Path

from PIL import Image


project = Path(__file__).resolve().parents[1]
destination = Path(sys.argv[1])
images = destination / "images"
images.mkdir(parents=True)
provenance = {}
failures = []
for archive in sorted((project / "Game").glob("*.nob")):
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not member.filename.lower().endswith(".tga"):
                continue
            relative = Path(archive.name) / Path(member.filename).with_suffix(".png")
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(member.filename)
            target = images / relative
            if target.exists():
                raise FileExistsError(target)
            try:
                with Image.open(io.BytesIO(package.read(member))) as image:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    image.convert("RGBA").save(target)
            except OSError as error:
                failures.append({"archive": archive.name, "member": member.filename, "error": str(error)})
                continue
            provenance[relative.as_posix()] = {
                "asset": archive.name,
                "texture_name": member.filename,
                "crc32": f"{member.CRC:08x}",
            }
(destination / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
(destination / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
print(f"{len(provenance)} textures exported; {len(failures)} failed")
