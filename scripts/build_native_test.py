"""Build the x86 adapter and compose a separate test installation."""
import argparse
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pefile

from repack_images import sha
from stage_text import stage


PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parents[1]
EXE_SHA = "383f80768cc502044cfa64e242940a44dc72632b988440ef53bfac92fd4f387e"
MINHOOK = "c3fcafdc10146beb5919319d0683e44e3c30d537"


def forwarders(build):
    system = Path("C:/Windows/SysWOW64/winmm.dll")
    with pefile.PE(str(system)) as image:
        exports = [(symbol.ordinal, symbol.name.decode("ascii") if symbol.name else None)
                   for symbol in image.DIRECTORY_ENTRY_EXPORT.symbols]
    if len(exports) != 193 or len({ordinal for ordinal, _ in exports}) != len(exports):
        raise ValueError("Unexpected x86 WinMM export inventory")
    names = ",".join(json.dumps(name) if name else "nullptr" for _, name in exports)
    ordinals = ",".join(str(ordinal) for ordinal, _ in exports)
    (build / "forward_metadata.hpp").write_text(
        f"#define NODZH_FORWARD_COUNT {len(exports)}\n"
        f"constexpr const char* forward_names[] = {{{names}}};\n"
        f"constexpr WORD forward_ordinals[] = {{{ordinals}}};\n", encoding="ascii")
    stubs = []
    definition = ["LIBRARY winmm", "EXPORTS"]
    for index, (ordinal, name) in enumerate(exports):
        symbol = f"Forward{index}"
        stubs.append(
            f'extern "C" __declspec(naked) void {symbol}() {{\n'
            f"    __asm {{\n        pushfd\n        pushad\n        push {index}\n"
            "        call resolve_forward\n        add esp,4\n        popad\n        popfd\n"
            f"        jmp dword ptr [g_forwards+{index * 4}]\n    }}\n}}")
        definition.append(f"    {name or f'Ordinal{ordinal}'}={symbol} @{ordinal}" + ("" if name else " NONAME"))
    (build / "forward_stubs.inc").write_text("\n".join(stubs), encoding="ascii")
    (build / "winmm.def").write_text("\n".join(definition) + "\n", encoding="ascii")


def compile_adapter(build):
    build.mkdir(parents=True)
    forwarders(build)
    vcvars = Path("C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars32.bat")
    hook = WORKSPACE / "Tools/native/MinHook"
    revision = subprocess.check_output(["git", "-C", str(hook), "rev-parse", "HEAD"], text=True).strip()
    if revision != MINHOOK:
        raise ValueError("MinHook revision differs from reviewed dependency")
    def quote(path):
        return '"' + str(path.resolve()) + '"'
    native = PROJECT / "scripts/native"
    obj = build / "obj"
    obj.mkdir()
    sources = [hook / rel for rel in ("src/buffer.c", "src/hook.c", "src/trampoline.c", "src/hde/hde32.c")]
    lines = ["@echo off", f"call {quote(vcvars)} >nul", "if errorlevel 1 exit /b 1"]
    lines.append(f'cl /nologo /c /O2 /MT /I{quote(hook / "include")} '
                 + " ".join(quote(path) for path in sources))
    lines.append("if errorlevel 1 exit /b 1")
    lines.append(f'cl /nologo /c /O2 /MT /EHsc /std:c++17 /utf-8 /DNOMINMAX /I{quote(hook / "include")} '
                 f'/I{quote(build)} {quote(native / "adapter.cpp")}')
    lines.append("if errorlevel 1 exit /b 1")
    lines.append(f'link /nologo /DLL /MACHINE:X86 /OUT:{quote(build / "winmm.dll")} '
                 f'/DEF:{quote(build / "winmm.def")} adapter.obj buffer.obj hook.obj trampoline.obj hde32.obj')
    batch = build / "compile.cmd"
    batch.write_text("\n".join(lines) + "\n", encoding="ascii")
    subprocess.run(["cmd.exe", "/d", "/c", str(batch.resolve())], cwd=obj, check=True)
    return build / "winmm.dll"


def compose(game, lab, dll, glyphs):
    if sha(game / "Vampire.exe") != EXE_SHA:
        raise ValueError("Unsupported Steam executable")
    stage_dir = lab.parent / (lab.name + "-resources")
    stage_report = stage(game / "Local_Eng.nob", stage_dir)
    ignored = shutil.ignore_patterns("savegame", "savegames", "save", "*.tmp", "*.bak")
    shutil.copytree(game, lab, ignore=ignored)
    archive = lab / "Local_Eng.nob"
    rebuilt = lab / "Local_Eng.nob.tmp"
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(rebuilt, "x") as target:
        names = original.namelist()
        replacements = stage_report["members"]
        target.comment = original.comment
        for member in original.infolist():
            if member.filename in replacements:
                data = (stage_dir / member.filename).read_bytes()
            else:
                data = original.read(member)
            target.writestr(member, data)
    with zipfile.ZipFile(rebuilt) as target:
        if target.namelist() != names or target.testzip() is not None:
            raise ValueError("Invalid rebuilt text archive")
        if any(target.read(name) != (stage_dir / name).read_bytes() for name in replacements):
            raise ValueError("Text differs on NOB readback")
    rebuilt.replace(archive)
    assets = lab / "NodChinese"
    assets.mkdir()
    shutil.copy2(dll, lab / "winmm.dll")
    shutil.copy2(glyphs, assets / "glyphs.bin")
    receipt = {"records": stage_report["records"], "translated_resources": len(replacements),
               "source_archive_sha256": stage_report["archive_sha256"],
               "archive_sha256": sha(archive), "adapter_sha256": sha(dll), "glyph_sha256": sha(glyphs)}
    (assets / "build_report.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--build", type=Path, required=True)
    cli.add_argument("--game", type=Path)
    cli.add_argument("--lab", type=Path)
    cli.add_argument("--glyphs", type=Path)
    args = cli.parse_args()
    if any((args.game, args.lab, args.glyphs)) and not all((args.game, args.lab, args.glyphs)):
        cli.error("Provide --game, --lab and --glyphs together")
    adapter = compile_adapter(args.build)
    print(json.dumps(compose(args.game, args.lab, adapter, args.glyphs), indent=2)
          if args.lab else str(adapter.resolve()))
