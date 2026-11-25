"""Install the checked Chinese test build with a recoverable resource backup."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from build_native_test import EXE_SHA
from repack_images import sha

ARCHIVE = "Local_Eng.nob"
FILES = (ARCHIVE, "winmm.dll", "NodChinese/glyphs.bin")
LAB_REPORT = "NodChinese/build_report.json"


def install(game, lab, backup):
    game, lab, backup = (path.resolve() for path in (game, lab, backup))
    if game == lab or backup.is_relative_to(game) or backup.is_relative_to(lab):
        raise ValueError("Use separate game, laboratory and backup directories")
    if sha(game / "Vampire.exe") != EXE_SHA or sha(lab / "Vampire.exe") != EXE_SHA:
        raise ValueError("Unsupported executable version")
    if (game / "winmm.dll").exists() or (game / "NodChinese").exists():
        raise ValueError("Existing display adapter or data directory must be reviewed")
    report = json.loads((lab / LAB_REPORT).read_text(encoding="utf-8"))
    original = sha(game / ARCHIVE)
    if original != report["source_archive_sha256"]:
        raise ValueError("Installed game archive differs from the verified source")
    hashes = dict(zip(FILES, (report["archive_sha256"], report["adapter_sha256"], report["glyph_sha256"])))
    if any(sha(lab / name) != digest for name, digest in hashes.items()):
        raise ValueError("Laboratory payload changed after build verification")
    backup.mkdir(parents=True)
    shutil.copy2(game / ARCHIVE, backup / ARCHIVE)
    if sha(backup / ARCHIVE) != original:
        raise ValueError("Backup verification failed")
    receipt = {"source_archive_sha256": original, "installed_files": hashes,
               "records": report["records"], "translated_resources": report["translated_resources"]}
    (backup / "install_manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    replaced = []
    data = game / "NodChinese"
    try:
        with tempfile.TemporaryDirectory(prefix=".nod-stage-", dir=game) as directory:
            staging = Path(directory)
            for name, digest in hashes.items():
                temp = staging / name
                temp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(lab / name, temp)
                if sha(temp) != digest:
                    raise ValueError(f"Staging verification failed: {name}")
            data.mkdir()
            # Install the data before the module that uses it.
            for name in (FILES[2], FILES[1], ARCHIVE):
                target = game / name
                if (name == ARCHIVE and sha(target) != original) or (name != ARCHIVE and target.exists()):
                    raise ValueError(f"Game path changed during installation: {target}")
                (staging / name).replace(target)
                replaced.append(name)
                if sha(target) != hashes[name]:
                    raise ValueError(f"Installed hash differs: {target}")
    except Exception:
        for name in reversed(replaced):
            if name == ARCHIVE:
                shutil.copy2(backup / name, game / name)
            else:
                (game / name).unlink()
        if data.exists() and not any(data.iterdir()):
            data.rmdir()
        raise
    (backup / "installation_verified.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("game", type=Path)
    cli.add_argument("lab", type=Path)
    cli.add_argument("backup", type=Path)
    args = cli.parse_args()
    print(json.dumps(install(args.game, args.lab, args.backup), indent=2))
