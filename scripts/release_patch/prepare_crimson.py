"""Prepare hash-bound Chinese overlays for Crimson Edition 1.0."""

import argparse
from collections import Counter
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile

from PIL import Image, ImageChops

PREFIX = "MODS/VTMR Crimson Edition/"
EXE = "326cf834c5ba01e5485da4e5d6fbd43b9066cc452bee6da2bb52c720d2dc445f"
LINE = re.compile(r"^([^\s/]+)([ \t]+)(.*?)([ \t]*)(\r\n|\n|\r)?$")
OVERRIDES = {
    "POTIONDISEASE": "祛病灵药", "SILVERCOINS": "一堆银币", "GOLDCOINS": "一堆金币",
    "CASH": "一沓现金", "GEN_CLICKOPENDOOR": "开门", "GEN_CLICKTURNWHEEL": "转动轮盘",
    "GEN_CLICKPULLLEVER": "拉动拉杆", "GEN_CLICKPUSHBUTTON": "按下按钮",
    "RPG_PICKEDUPCASHDA": "你拾取了%D钱币。", "RPG_PICKEDUPCASHMD": "你拾取了%D现金。",
    "UI_HINT_DISCTABSCROLL1": "上一项天赋", "UI_HINT_DISCTABSCROLL2": "下一项天赋",
    "UI_HINT_DISCSCROLL1": "上一项异能", "UI_HINT_DISCSCROLL2": "下一项异能",
    "UI_HINT_SBLVLUPBUTTON": "升级", "UI_HINT_SBVAULTBUTTON": "打开储物箱",
    "UI_HINT_VAULTOKBUTTON": "关闭储物箱", "UI_HINT_INVGOLDBUTTON": "丢弃现金",
    "UI_HINT_BSDONEBUTTON": "离开商店", "UI_HINT_READOKBUTTON": "结束阅读",
    "UI_INV_DROPCASH": "你想丢弃多少现金？",
    "UI_NET_OLDVERSION": "你的游戏版本已过期。请选择“下载更新”检查游戏更新。",
    "UI_STATUSIND_HINT": "切换跟随状态", "UI_BUYSELL_BUYHINT": "购买物品",
    "UI_BUYSELL_SELLHINT": "出售物品",
}
TEXTURES = (
    "UI/Materials/CharacterPane01.tga", "UI/Materials/CharacterPane02.tga",
    "UI/Materials/CharacterPane03.tga", "UI/Materials/OpsDisplay02.tga",
)


def digest(data):
    return sha256(data).hexdigest()


def rows(data, encoding):
    for line in data.decode(encoding).splitlines(keepends=True):
        yield line, LINE.fullmatch(line)


def table(data, encoding):
    result = {}
    for _, row in rows(data, encoding):
        if row:
            key, value = row[1], row[3]
            if result.setdefault(key, value) != value:
                raise ValueError(f"Conflicting repeated key: {key}")
    return result


def merge(mod, original, translated):
    en, zh = table(original, "cp1252"), table(translated, "utf-8")
    if en.keys() != zh.keys():
        raise ValueError("Original and translation keys differ")
    changed, added, output, covered = [], [], [], set()
    for line, row in rows(mod, "cp1252"):
        if row is None:
            output.append(line)
            continue
        key, sep, value, trailing, newline = row.groups()
        covered.add(key)
        if value == en.get(key):
            chinese = zh[key]
        else:
            chinese = OVERRIDES[key]
            (changed if key in en else added).append(key)
        token = r"%[A-Za-z]|\\[tnr]"
        if Counter(re.findall(token, value)) != Counter(re.findall(token, chinese)):
            raise ValueError(f"Placeholder mismatch: {key}")
        output.append(key + sep + chinese + trailing + (newline or ""))
    if not en.keys() <= covered:
        raise ValueError("Missing original keys in Crimson table")
    new = "".join(output).encode("utf-8")
    if [row[1] for _, row in rows(mod, "cp1252") if row] != [row[1] for _, row in rows(new, "utf-8") if row]:
        raise ValueError("Crimson key order changed")
    return new, {"changed": changed, "added": added}


def overlay(mod, original, translated):
    def pixels(data):
        return Image.open(io.BytesIO(data)).convert("RGBA")

    old, new, image = map(pixels, (original, translated, mod))
    if old.size != new.size or image.size != new.size:
        raise ValueError("Texture size differs")
    delta = ImageChops.difference(old.convert("RGB"), new.convert("RGB"))
    mask = ImageChops.lighter(ImageChops.lighter(*delta.split()[:2]), delta.getchannel("B")).point(lambda x: 255 if x else 0)
    image.paste(new.convert("RGB"), mask=mask)
    image.putalpha(pixels(mod).getchannel("A"))
    if mod[:3] != b"\0\0\2" or mod[16:18] not in (b"\x20\0", b"\x20\x08"):
        raise ValueError("Unexpected Crimson TGA layout")
    raw = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes("raw", "BGRA")
    result = mod[:18] + raw + mod[18 + len(raw):]
    if pixels(result).tobytes() != image.tobytes():
        raise ValueError("TGA round trip changed pixels")
    return result, {"changed_pixels": mask.histogram()[255]}


def prepare(modzip, original, translated, output):
    output.mkdir(parents=True, exist_ok=False)
    result = {"supported_exe_sha256": EXE, "resources": []}
    with ZipFile(modzip) as mod, ZipFile(original) as base, ZipFile(translated) as zh:
        if digest(mod.read(PREFIX + "Vampire.exe")) != EXE:
            raise ValueError("Unsupported Crimson executable")
        def index(z):
            return {name.casefold(): name for name in z.namelist()}

        original_names, translated_names = index(base), index(zh)
        for name in ("Strings/Game.nls", "Strings/System.nls", *TEXTURES):
            source = mod.read(PREFIX + name)
            old = base.read(original_names[name.casefold()])
            chinese = zh.read(translated_names[name.casefold()])
            transform = merge if name.endswith(".nls") else overlay
            after, evidence = transform(source, old, chinese)
            if after == source:
                continue
            result["resources"].append({"name": name, "source": digest(source), "target": digest(after), **evidence})
            for folder, content in (("original", source), ("translated", after)):
                path = output / folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("modzip", "original", "translated", "output"):
        parser.add_argument(name, type=Path)
    prepare(**vars(parser.parse_args()))
