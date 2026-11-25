"""Build the Steam Redemption display fix from the verified renderer profile."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
VERSION = "1.0"
UPSTREAM_HASH = "9afa493396feec7108f42a2d97661eef96bbaac5addf0dfb5cfbc3001cd76a0a"
VERIFIED_CONFIG_HASH = "00527bea522d83285cdc84cabc86554d2c5cd77d2f84165f67731b6d5c21a089"
FILENAME = f"Vampire The Masquerade - Redemption_体验优化{VERSION}.zip"
PAYLOAD = "RedemptionDisplayFix"
UPSTREAM_URL = "https://github.com/dege-diosg/dgVoodoo2/releases/tag/2.87.6"


def digest(content):
    return sha256(content).hexdigest()


def windows_text(text, encoding):
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode(encoding)


def launcher(action):
    return windows_text(
        f'@echo off\n'
        f'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0{PAYLOAD}\\Apply-DisplayFix.ps1" -Action {action}\n'
        f'set "patch_status=%errorlevel%"\n'
        f'pause\n'
        f'exit /b %patch_status%\n',
        "ascii",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream_zip", type=Path)
    parser.add_argument("verified_config", type=Path)
    args = parser.parse_args()

    if digest(args.upstream_zip.read_bytes()) != UPSTREAM_HASH:
        raise ValueError("Unexpected upstream dgVoodoo2 archive")
    config = args.verified_config.read_bytes()
    if digest(config) != VERIFIED_CONFIG_HASH:
        raise ValueError("Unexpected dgVoodoo2 profile")

    with ZipFile(args.upstream_zip) as upstream:
        graphics_files = {name: upstream.read(f"MS/x86/{name}") for name in ("DDraw.dll", "D3DImm.dll")}
    active_lines = [line for line in config.decode("ascii").splitlines() if line.strip() and not line.lstrip().startswith(";")]
    graphics_files["dgVoodoo.conf"] = windows_text("\n".join(active_lines) + "\n", "ascii")

    manifest = {
        "version": VERSION,
        "game": {
            "steam_appid": 559680,
            "steam_buildid": 1472805,
            "exe_sha256": "383f80768cc502044cfa64e242940a44dc72632b988440ef53bfac92fd4f387e",
            "renderer_sha256": "884f475d16e812ccda13fbb97280185ac6a1727608e3d2d0edc09f1ac05c8917",
        },
        "upstream": {"name": "dgVoodoo2", "version": "2.87.6", "url": UPSTREAM_URL, "archive_sha256": UPSTREAM_HASH},
        "files": [{"name": name, "sha256": digest(content)} for name, content in graphics_files.items()],
        "dpi": {"scope": "current_user", "target": "Vampire.exe", "flag": "HIGHDPIAWARE"},
    }
    files = {
        "安装体验优化.cmd": launcher("Install"),
        "卸载体验优化.cmd": launcher("Uninstall"),
        "体验优化补丁说明.txt": windows_text((HERE / "体验优化补丁说明.txt").read_text(encoding="utf-8"), "utf-8-sig"),
        f"{PAYLOAD}/Apply-DisplayFix.ps1": windows_text((HERE / "Apply-DisplayFix.ps1").read_text(encoding="ascii"), "ascii"),
        f"{PAYLOAD}/DisplayFixManifest.json": (json.dumps(manifest, indent=2) + "\n").encode("ascii"),
        **{f"{PAYLOAD}/{name}": content for name, content in graphics_files.items()},
    }
    files["体验优化_SHA256SUMS.txt"] = windows_text(
        "".join(f"{digest(content)}  {name}\n" for name, content in files.items()), "utf-8-sig"
    )

    # Stage the actual layout for the zip and for inspection.
    staging = PROJECT / "Dispatch" / "Files" / "体验优化1.0"
    output = PROJECT / "Dispatch" / FILENAME
    for name, content in files.items():
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    pending = output.with_suffix(".zip.tmp")
    with ZipFile(pending, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name in files:
            archive.write(staging / name, name)
    with ZipFile(pending) as archive:
        if archive.testzip() or archive.namelist() != list(files) or any(archive.read(name) != data for name, data in files.items()):
            raise ValueError("ZIP verification failed")
    pending.replace(output)
    print(f"{digest(output.read_bytes())}  {output}")


if __name__ == "__main__":
    main()
