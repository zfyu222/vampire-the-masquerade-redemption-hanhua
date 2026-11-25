"""Install the player-supplied Crimson baseline for a local compatibility test."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from zipfile import ZipFile

from prepare_crimson import EXE, PREFIX

STEAM = "383f80768cc502044cfa64e242940a44dc72632b988440ef53bfac92fd4f387e"


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def check_closed():
    processes = subprocess.check_output(["tasklist.exe", "/FI", "IMAGENAME eq Vampire.exe", "/NH"])
    if b"vampire.exe" in processes.lower():
        raise RuntimeError("Close Vampire before synchronizing the game")


def target(root, name):
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes game directory: {name}")
    return resolved


def copy(source, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".crimson-pending")
    if temp.exists():
        raise ValueError(f"Unexpected staging file: {temp}")
    try:
        shutil.copy2(source, temp)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def restore(game, state, entries):
    for row in entries:
        path = target(game, row["name"])
        current = digest(path) if path.is_file() else None
        if current not in (row["after"], row["before"]):
            raise ValueError(f"Changed since installation: {row['name']}")
        if row["before"] and digest(state / "original" / row["name"]) != row["before"]:
            raise ValueError(f"Invalid backup: {row['name']}")
    for row in reversed(entries):
        path = target(game, row["name"])
        if row["before"]:
            if not path.is_file() or digest(path) != row["before"]:
                copy(state / "original" / row["name"], path)
        else:
            path.unlink(missing_ok=True)


def install(game, state, mod_path, patch_payload):
    if digest(game / "Vampire.exe") != STEAM:
        raise ValueError("Expected the original Steam executable before enabling Crimson")
    state.mkdir(parents=True, exist_ok=False)
    prepared = state / "prepared"
    entries, seen = [], set()
    with ZipFile(mod_path) as mod:
        if hashlib.sha256(mod.read(PREFIX + "Vampire.exe")).hexdigest() != EXE:
            raise ValueError("Unsupported Crimson archive")
        for member in mod.infolist():
            if not member.filename.startswith(PREFIX) or member.is_dir():
                continue
            name = member.filename[len(PREFIX):]
            key = name.casefold()
            if key == "reshade.log":
                continue
            if key in seen:
                raise ValueError(f"Duplicate mod path: {name}")
            seen.add(key)
            dest = target(game, name)
            stage = target(prepared, name)
            stage.parent.mkdir(parents=True, exist_ok=True)
            if key == "masquerade.ini":
                data = dest.read_bytes()
                stock = mod.read(member)
                for option in (b"ScreenWidth", b"ScreenHeight", b"ScreenDepth"):
                    pattern = rb"(?im)^(" + option + rb"=)([0-9]+)"
                    value = re.search(pattern, stock)[2]
                    data, count = re.subn(pattern, lambda m: m[1] + value, data)
                    if count != 1:
                        raise ValueError(f"Missing or duplicate render setting: {option!r}")
                stage.write_bytes(data)
            else:
                with mod.open(member) as source, stage.open("xb") as stream:
                    shutil.copyfileobj(source, stream, 1024 * 1024)
            before = digest(dest) if dest.is_file() else None
            after = digest(stage)
            if before == after:
                continue
            if before:
                save = state / "original" / name
                save.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, save)
                if digest(save) != before:
                    raise ValueError(f"Backup verification failed: {name}")
            entries.append({"name": name, "before": before, "after": after})
    entries.sort(key=lambda row: row["name"].casefold() == "vampire.exe")
    receipt = state / "baseline.json"
    receipt.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    check_closed()
    applied = []
    try:
        for row in entries:
            dest = target(game, row["name"])
            if (digest(dest) if dest.is_file() else None) != row["before"]:
                raise ValueError(f"Live file changed: {row['name']}")
            copy(prepared / row["name"], dest)
            applied.append(row)
            if digest(dest) != row["after"]:
                raise ValueError(f"Live verification failed: {row['name']}")
    except Exception:
        restore(game, state, applied)
        raise
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(patch_payload / "Apply-CrimsonChinese.ps1"), "-Game", str(game)],
        check=True,
    )
    return len(entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("state", type=Path)
    parser.add_argument("patch_payload", type=Path)
    parser.add_argument("--mod", type=Path, help="Install this archive, otherwise restore the saved Steam baseline")
    args = parser.parse_args()
    game, state, payload = (p.resolve() for p in (args.game, args.state, args.patch_payload))
    if state.is_relative_to(game) or game.is_relative_to(state):
        raise ValueError("Keep developer backups outside the game directory")
    check_closed()
    if args.mod:
        print(f"Verified Crimson baseline files installed: {install(game, state, args.mod.resolve(), payload)}")
    else:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(payload / "Apply-CrimsonChinese.ps1"), "-Game", str(game), "-Uninstall"],
            check=True,
        )
        entries = json.loads((state / "baseline.json").read_text(encoding="utf-8"))
        restore(game, state, entries)
        print("Steam baseline restored")


if __name__ == "__main__":
    main()
