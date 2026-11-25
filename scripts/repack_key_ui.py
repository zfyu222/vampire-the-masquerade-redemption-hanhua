"""Localize the fixed Nod menu art in the user-reported screens."""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

from preview_menu import PROJECT, QUAD, assemble_menu
from repack_images import rebuild_archive, sha

LAYOUT = PROJECT / "ImagePatch/key-ui-layout.json"
IMAGE_CSV = PROJECT / f"{PROJECT.name}_images_text"
BUTTON = re.compile(r"^element button .*rollover=.*$", re.MULTILINE)
GEOMETRY = re.compile(r"pos=(\d+),(\d+)\s+size=(\d+),(\d+)")
STATES = re.compile(r"(bitmap|rollover|depressed|greyed)=(\S+)")
INK = {"gold": (226, 198, 113), "ivory": (218, 196, 172),
       "rollover": (219, 32, 23), "depressed": (245, 232, 218), "greyed": (87, 78, 69),
       "map_red": (157, 25, 15), "map_ink": (34, 41, 40)}
SCALE = 4
IMAGE_TOOLS = PROJECT.parent.parent / "Tools/image_text"


def key(string):
    return " ".join(string.casefold().split())


def load_translations(spec):
    with IMAGE_CSV.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as source:
        originals = list(csv.reader(source))
    with IMAGE_CSV.with_name(IMAGE_CSV.name + "_translated.csv").open(encoding="utf-8-sig", newline="") as target:
        translated = list(csv.reader(target))
    result = {}
    for (original,), (text,) in zip(originals, translated, strict=True):
        result.setdefault(key(original), " ".join(text.split()))
    result.update({key(original): text for original, text in spec["new_terms"].items()})
    return result


def mask_text(image, style):
    red, green, blue = np.asarray(image.convert("RGB"), dtype=np.int16).transpose(2, 0, 1)
    if style == "gold":
        seed = (red > 112) & (green > 84) & (red - blue > 42) & (green - blue > 25)
    elif style == "map_red":
        seed = (red > 75) & (red - green > 38) & (red - blue > 36) & (green < 80)
    elif style == "map_ink":
        luminance = (red + 2*green + blue) / 4
        seed = luminance < min(105, np.median(luminance)-35)
    else:
        seed = (green > 90) & (blue > 64) & (red - green < 62)
    mask = seed.astype(np.uint8) * 255
    if style not in {"gold", "map_ink"}:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        for label in range(1, count):
            single = labels == label
            minimum = 4 if style == "map_red" else 2
            if stats[label, cv2.CC_STAT_AREA] < minimum and green[single].max() < 135:
                mask[labels == label] = 0
    bounds = Image.fromarray(mask).getbbox()
    if bounds is None:
        raise ValueError("No visible strokes in the recorded source rectangle")
    dilation = 3 if style == "ivory" else (1 if style == "map_ink" else 2)
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*dilation+1, 2*dilation+1)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask, bounds


def erase(image, mask, grain=False):
    rgba = np.array(image.convert("RGBA"))
    rgb = rgba[:, :, :3].copy()
    if grain:
        sys.path.insert(0, str(IMAGE_TOOLS))
        from image_style import fill_strokes

        rgba[:, :, :3], _ = fill_strokes(rgb, mask, "grain")
    else:
        rgba[:, :, :3] = cv2.inpaint(rgb, mask, 2, cv2.INPAINT_TELEA)
    return Image.fromarray(rgba)


def draw_label(image, text, bounds, style, font_dir, large=False, angle=0):
    left, top, right, bottom = bounds
    if angle == -90:
        rotated = image.transpose(Image.Transpose.ROTATE_270)
        draw_label(rotated, text, (image.height-bottom, left, image.height-top, right),
                   style, font_dir, large)
        image.paste(rotated.transpose(Image.Transpose.ROTATE_90))
        return
    center = ((left+right)/2, (top+bottom)/2)
    available_width = (image.width - 2) * SCALE
    available_height = (image.height - 2) * SCALE
    font_name = "NotoSerifSC-variable.ttf" if large or style == "map_ink" else "NotoSansSC-variable.ttf"
    size = 22 if large else (13 if bottom-top >= 11 else 11)
    while size >= 8:
        font = ImageFont.truetype(str(font_dir / font_name), size*SCALE)
        font.set_variation_by_axes([650])
        box = font.getbbox(text)
        if box[2]-box[0] <= available_width and box[3]-box[1] <= available_height:
            break
        size -= 1
    else:
        raise ValueError(f"Label does not fit: {text}")
    overlay = Image.new("RGBA", (image.width*SCALE, image.height*SCALE))
    pen = ImageDraw.Draw(overlay)
    at = tuple(
        min(max(round(axis*SCALE-(lower+upper)/2), SCALE-lower), extent*SCALE-SCALE-upper)
        for axis, lower, upper, extent in zip(center, box[:2], box[2:], image.size, strict=True)
    )
    shadow = 2 if large else 1
    pen.text((at[0]+shadow, at[1]+shadow), text, font=font, fill=(13, 9, 5, 205),
             stroke_width=shadow, stroke_fill=(13, 9, 5, 175))
    pen.text(at, text, font=font, fill=(*INK[style], 255))
    if angle:
        overlay = overlay.rotate(-angle, resample=Image.Resampling.BICUBIC,
                                 center=(center[0]*SCALE, center[1]*SCALE))
    image.alpha_composite(overlay.resize(image.size, Image.Resampling.LANCZOS))


def patch_label(canvas, original, box, text, font_dir, mode, style="gold", large=False, angle=0):
    sample = original.crop(box)
    mask, bounds = mask_text(sample, style)
    if mode == "draw":
        cleaned = canvas.crop(box)
        draw_label(cleaned, text, bounds, style, font_dir, large, angle)
        canvas.paste(cleaned, box[:2])
    else:
        canvas.paste(erase(sample, mask, style.startswith("map_")), box[:2], Image.fromarray(mask))
    return mask, bounds


def subtitle_layout(archive_path, style):
    name = "ui/subtitle.nui"
    font, height = style["font"], style["height"]
    with zipfile.ZipFile(archive_path) as archive:
        names = {entry.casefold() for entry in archive.namelist()}
        if f"ui/{font.casefold()}.nfd" not in names:
            raise ValueError(f"Subtitle font not found: {font}")
        previous = archive.read(name)
    def enlarge(line):
        text = line[0]
        if b" font=" in text or text.count(b" size=510,126 ") != 1:
            return text
        return text.replace(b" size=510,126 ", f" size=510,{height} ".encode("ascii")) + b" font=" + font.encode("ascii")

    new, count = re.subn(br"(?m)^element textbox name=subtitleTextBox[^\r\n]*", enlarge, previous)
    if count != 1 or new == previous:
        raise ValueError("Subtitle layout did not match the expected original widget")
    return {name: (previous, new)}


def button_box(button, height):
    x, y, w, h = map(int, GEOMETRY.search(button).groups())
    top = height-y-h
    return (x, top, x+w, top+h)


def escape_mask(image, buttons):
    mask = Image.new("L", image.size)
    for button in buttons:
        box = button_box(button, image.height)
        strokes, _ = mask_text(image.crop(box), "ivory")
        mask.paste(Image.fromarray(strokes), box[:2])
    return np.array(mask)


def clean_escape(original, buttons, alternative, alternative_buttons):
    rgba, donor = np.array(original), np.array(alternative)
    mask = escape_mask(original, buttons) != 0
    alternate_ink = escape_mask(alternative, alternative_buttons) != 0
    reuse = mask & ~alternate_ink
    rgba[reuse] = donor[reuse]
    pending = mask & alternate_ink
    for x in np.flatnonzero(pending.any(axis=0)):
        rows = np.flatnonzero(pending[:, x])
        known = np.flatnonzero(~pending[:, x])
        rgba[rows, x, 3] = np.where(np.interp(rows, known, rgba[known, x, 3]) >= 128, 255, 0)
    paint = pending & (rgba[:, :, 3] != 0)
    nearby = cv2.dilate(paint.astype(np.uint8), np.ones((11, 11), np.uint8)) != 0
    paint_mask = paint | (nearby & (rgba[:, :, 3] == 0))
    rgb = cv2.inpaint(rgba[:, :, :3].copy(), paint_mask.astype(np.uint8)*255, 4, cv2.INPAINT_TELEA)
    rgba[paint, :3] = rgb[paint]
    rgba[mask & (rgba[:, :, 3] == 0)] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(rgba[:, :, 3].copy())
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] <= 8:
            rgba[mask & (labels == index)] = 0
    return Image.fromarray(rgba)


def trim_transparent_fringe(image):
    alpha = image.getchannel("A")
    image.paste((0, 0, 0, 0), (0, 0, *image.size),
                alpha.point(lambda value: 255 if value < 32 else 0))


def make_images(archive_path, spec, font_dir, mode, out, clean_dir):
    translations = load_translations(spec)
    patches = {}
    out.mkdir()
    (out / "screens").mkdir()
    (out / "textures").mkdir()

    with zipfile.ZipFile(archive_path) as archive:
        names = {name.casefold(): name for name in archive.namelist()}

        def texture_name(material):
            return names[f"ui/materials/{material.removesuffix('.tga')}.tga".casefold()]

        def read_texture(name):
            return Image.open(io.BytesIO(archive.read(name))).convert("RGBA")

        def clean_texture(name):
            path = clean_dir / "textures" / (Path(name).stem + ".png")
            with Image.open(path) as saved:
                return saved.convert("RGBA")

        def keep(name, modified):
            original = read_texture(name)
            if modified.tobytes() == original.tobytes():
                return
            path = out / "textures" / (Path(name).stem + ".png")
            if name in patches:
                with Image.open(path) as other:
                    if modified.tobytes() != other.tobytes():
                        raise ValueError(f"Shared texture has inconsistent edits: {name}")
                return
            modified.save(path)
            original.paste((0, 0, 0, 0), (0, 0, *original.size),
                           original.getchannel("A").point(lambda alpha: 255 if alpha == 0 else 0))
            evidence = {"image_id": hashlib.sha256(str(original.size).encode() + original.tobytes()).hexdigest(),
                        "width": original.width, "height": original.height,
                        "provenance": {"crc32": f"{archive.getinfo(name).CRC:08x}"}}
            patches[name] = (path, evidence)

        screens = dict.fromkeys((*spec["buttons"], *spec["labels"], *spec.get("map_labels", {})))
        for page in screens:
            definition = archive.read(names[f"ui/{page}.nui".casefold()])
            buttons = BUTTON.findall(definition.decode("ascii"))
            original = assemble_menu(archive, page)
            canvas = original.copy()
            transparent = page in {"escapeMenu", "escapeMenuMP"}
            if mode == "draw":
                with Image.open(clean_dir / "screens" / (page + ".png")) as saved:
                    canvas = saved.convert("RGBA")
            elif transparent:
                other_page = "escapeMenuMP" if page == "escapeMenu" else "escapeMenu"
                other = assemble_menu(archive, other_page)
                other_definition = archive.read(names[f"ui/{other_page}.nui".casefold()]).decode("ascii")
                canvas = clean_escape(original, buttons, other, BUTTON.findall(other_definition))
            art_mask = Image.new("L", canvas.size)
            for phrase, *box in spec["labels"].get(page, []):
                try:
                    patch_label(canvas, original, box, translations[key(phrase)], font_dir, mode)
                except ValueError as error:
                    raise ValueError(f"{page}: {phrase}") from error
            for phrase, x0, y0, x1, y1 in spec.get("map_labels", {}).get(page, []):
                patch_label(canvas, original, (x0, y0, x1, y1), translations[key(phrase)],
                            font_dir, mode, "map_red", True)
            for phrase, x0, y0, x1, y1, angle in spec.get("map_ink_labels", {}).get(page, []):
                patch_label(canvas, original, (x0, y0, x1, y1), translations[key(phrase)],
                            font_dir, mode, "map_ink", angle=angle)
            phrases = spec["buttons"].get(page, [])
            for button, phrase in zip(buttons, phrases, strict=True):
                box = button_box(button, canvas.height)
                w, h = box[2]-box[0], box[3]-box[1]
                text = translations[key(phrase)]
                large = transparent or page in {"mainMenu", "options", "sp"}
                if transparent and mode == "clean":
                    mask, bounds = mask_text(original.crop(box), "ivory")
                else:
                    mask, bounds = patch_label(canvas, original, box, text, font_dir, mode, "ivory", large)
                if large and not transparent and mode == "clean":
                    art_mask.paste(Image.fromarray(mask), box[:2])
                states = dict(STATES.findall(button))
                if "bitmap" in states:
                    mask, _ = mask_text(read_texture(texture_name(states["bitmap"])), "ivory")
                for state, material in states.items():
                    name = texture_name(material)
                    texture = read_texture(name)
                    if texture.size != (w, h) and not transparent:
                        raise ValueError(f"Unexpected sprite size: {name}")
                    if mode == "draw":
                        sprite = clean_texture(name)
                        sprite_bounds = tuple(
                            round(coord * actual / logical) for coord, actual, logical in
                            zip(bounds, texture.size * 2, (w, h) * 2, strict=True)
                        )
                        draw_label(sprite, text, sprite_bounds,
                                   "ivory" if state == "bitmap" else state, font_dir, large)
                        if transparent:
                            trim_transparent_fringe(sprite)
                    else:
                        sprite = (canvas.crop(box).resize(texture.size, Image.Resampling.NEAREST)
                                  if transparent else erase(texture, mask))
                    keep(name, sprite)
            if transparent and mode == "draw":
                trim_transparent_fringe(canvas)
            if art_mask.getbbox():
                sys.path.insert(0, str(IMAGE_TOOLS))
                from image_style import LAMA_DEFAULT, lama_fill

                filled, _ = lama_fill(np.array(original.convert("RGB")), np.array(art_mask), LAMA_DEFAULT)
                artwork = Image.fromarray(filled).convert("RGBA")
                canvas.paste(artwork, (0, 0), art_mask)
                if page == "mainMenu":
                    # The tip of the final "s" from "credits" survives the first repair.
                    box = (342, 247, 374, 265)
                    residual = Image.new("L", (32, 18))
                    ImageDraw.Draw(residual).ellipse((8, 4, 24, 13), fill=255)
                    canvas.paste(erase(canvas.crop(box), np.array(residual)), box[:2], residual)
            for mat, x, y, w, h in QUAD.findall(definition):
                name = texture_name(mat.decode("ascii"))
                x, y, w, h = (int(value) for value in (x, y, w, h))
                top = canvas.height-y-h
                box = (x, top, x+w, top+h)
                art = canvas.crop(box)
                base = original.crop(box)
                if art.tobytes() != base.tobytes():
                    tile = read_texture(name)
                    # Preserve original hidden RGB and unused texels outside the modified pixels.
                    changes = np.any(np.array(art) != np.array(base), axis=2)
                    tile.paste(art, (0, 0), Image.fromarray(changes.astype(np.uint8)*255))
                    keep(name, tile)
            canvas.save(out / "screens" / (page + ".png"))

        for material, phrase, *box in spec["standalone"]:
            name = texture_name(material)
            original = read_texture(name)
            image = clean_texture(name) if mode == "draw" else original.copy()
            patch_label(image, original, box, translations[key(phrase)], font_dir, mode)
            keep(name, image)
    return patches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=("clean", "draw"), required=True)
    parser.add_argument("--clean-dir", type=Path)
    parser.add_argument("--layout", type=Path, default=LAYOUT)
    parser.add_argument("--pack", action="store_true")
    args = parser.parse_args()
    if args.pack and args.mode != "draw":
        parser.error("--pack requires drawn textures")
    if args.mode == "draw" and not args.clean_dir:
        parser.error("--mode draw requires a reviewed --clean-dir")
    font_dir = PROJECT.parent.parent / "Tools/Fonts/NotoSC"
    spec = json.loads(args.layout.read_text(encoding="utf-8"))
    translations = load_translations(spec)
    phrases = {label[0] for labels in spec["labels"].values() for label in labels}
    phrases.update(phrase for buttons in spec["buttons"].values() for phrase in buttons)
    phrases.update(label[1] for label in spec["standalone"])
    phrases.update(label[0] for page in spec.get("map_labels", {}).values() for label in page)
    phrases.update(label[0] for page in spec.get("map_ink_labels", {}).values() for label in page)
    characters = {ord(char) for phrase in phrases for char in translations[key(phrase)] if not char.isspace()}
    font_names = ("NotoSansSC-variable.ttf", "NotoSerifSC-variable.ttf")
    for name in font_names:
        with TTFont(font_dir / name, lazy=True) as font:
            if missing := characters - font.getBestCmap().keys():
                raise ValueError(f"{name} lacks glyphs: {sorted(missing)}")
    if args.clean_dir:
        clean_report = json.loads((args.clean_dir / "archive_report.json").read_text(encoding="utf-8"))
        if clean_report["source_sha256"] != sha(args.archive) or clean_report["layout_sha256"] != sha(args.layout):
            raise ValueError("Clean preview came from a different archive or layout")
        for path, digest in clean_report["clean_files"].items():
            if sha(args.clean_dir / path) != digest:
                raise ValueError(f"Clean preview changed: {path}")
    patches = make_images(args.archive, spec, font_dir, args.mode, args.output, args.clean_dir)
    result = {"source_sha256": sha(args.archive), "layout_sha256": sha(args.layout),
              "image_translations_sha256": sha(IMAGE_CSV.with_name(IMAGE_CSV.name + "_translated.csv")),
              "fonts": {name: sha(font_dir / name) for name in font_names},
              "textures": {name: sha(path) for name, (path, _) in sorted(patches.items())}}
    if args.mode == "clean":
        result["clean_files"] = {path.relative_to(args.output).as_posix(): sha(path)
                                 for path in sorted(args.output.rglob("*.png"))}
    if args.pack:
        raw_patches = subtitle_layout(args.archive, spec["subtitle"]) if "subtitle" in spec else {}
        result["archives"] = [rebuild_archive(args.archive, args.output / args.archive.name, patches, raw_patches)]
    (args.output / "archive_report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{len(patches)} modified textures")


if __name__ == "__main__":
    main()
