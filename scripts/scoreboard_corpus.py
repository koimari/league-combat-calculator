#!/usr/bin/env python3
"""Corpus tooling for the scoreboard reader (static/js/scoreboard.js).

    read  <image>... [--sheet out.png]     read frames, print rows, draw a contact sheet
    scan  <video.mp4> [--step 10]          rank a VoD's frames by scoreboard evidence
    grab  <video.mp4> --at SECONDS --out frame.jpg   cut one full-resolution frame
    label <image> --league LCK --source ID@T   append the reader's rows to labels.json for review

A VoD comes down once with yt-dlp (a 480p stream is enough to scan, the 1080p
one to grab from): yt-dlp -f "bv*[height=1080][ext=mp4]" -o "%(id)s.%(ext)s" URL

Every subcommand reads through the one Node harness (tests/js/scoreboard_harness.mjs)
so the corpus is judged by the code the browser runs. Frames and labels live in
tests/fixtures/scoreboard/; tests/test_scoreboard_vision.py is the gate over them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "static" / "js" / "scoreboard.js"
HARNESS = ROOT / "tests" / "js" / "scoreboard_harness.mjs"
SPRITE = ROOT / "static" / "icon-sprite.webp"
CORPUS = ROOT / "tests" / "fixtures" / "scoreboard"
LABELS = CORPUS / "labels.json"


def _dump(image: Image.Image, path: Path) -> dict[str, Any]:
    rgba = image.convert("RGBA")
    path.write_bytes(rgba.tobytes())
    return {"bin": path.name, "width": rgba.width, "height": rgba.height}


def read_frames(paths: list[Path]) -> dict[str, Any]:
    """Run the harness over `paths`; the per-frame readings keyed by file name."""
    if shutil.which("node") is None:
        raise RuntimeError("node is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        with Image.open(SPRITE) as sheet:
            sprite = _dump(sheet, work / "sprite.bin")
        sprite["index"] = json.loads(
            SPRITE.with_suffix(".json").read_text(encoding="utf-8")
        )
        frames = []
        for path in paths:
            with Image.open(path) as image:
                frames.append(
                    {
                        "name": path.name,
                        **_dump(image, work / f"{path.stem}.bin"),
                    }
                )
        manifest = work / "manifest.json"
        manifest.write_text(
            json.dumps({"sprite": sprite, "frames": frames}), encoding="utf-8"
        )
        result = subprocess.run(
            ["node", str(HARNESS), str(SCRIPT), str(manifest)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)["frames"]


def item_names() -> dict[str, str]:
    items = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
    return {str(record["id"]): record["name"] for record in items.values()}


def describe(reading: dict[str, Any], names: dict[str, str]) -> str:
    lines = [
        f"  {len(reading['hits'])} hits, {len(reading['rows'])} rows, {reading['ms']} ms"
    ]
    for r, row in enumerate(reading["rows"]):
        for player in row:
            champion = player["champion"]
            items = " | ".join(
                (
                    f"{names.get(hit['key'], hit['key'])} {hit['score']:.2f}"
                    + ("?" if hit["gap"] < 0.08 else "")
                    if hit
                    else "-"
                )
                for hit in player["items"]
            )
            lines.append(
                f"  row{r} {champion['key']:<14} {champion['score']:.2f}  [{items}]"
            )
    return "\n".join(lines)


def contact_sheet(
    path: Path, reading: dict[str, Any], sprite_index: dict
) -> Image.Image:
    """Each read cell beside the sprite cell it was matched to, one row per player."""
    tile = 48
    with Image.open(path) as frame, Image.open(SPRITE) as sheet:
        frame = frame.convert("RGB")
        sheet = sheet.convert("RGB")
        players = [p for row in reading["rows"] for p in row]
        width = 2 * tile * 9
        out = Image.new("RGB", (width, max(1, len(players)) * tile), (20, 20, 20))
        draw = ImageDraw.Draw(out)
        cell, columns = sprite_index["cell"], sprite_index["columns"]
        for r, player in enumerate(players):
            for c, hit in enumerate([player["champion"], *player["items"]]):
                if not hit:
                    continue
                crop = frame.crop(
                    (hit["x"], hit["y"], hit["x"] + hit["size"], hit["y"] + hit["size"])
                ).resize((tile, tile))
                number = sprite_index[
                    "champions" if hit["kind"] == "champion" else "items"
                ][hit["key"]]
                sx, sy = (number % columns) * cell, (number // columns) * cell
                ref = sheet.crop((sx, sy, sx + cell, sy + cell)).resize((tile, tile))
                out.paste(crop, (c * 2 * tile, r * tile))
                out.paste(ref, (c * 2 * tile + tile, r * tile))
                colour = (255, 170, 0) if hit["gap"] < 0.08 else (0, 220, 0)
                draw.text(
                    (c * 2 * tile + 2, r * tile + 2), f"{hit['score']:.2f}", fill=colour
                )
    return out


def cmd_read(args: argparse.Namespace) -> int:
    """Print each frame's rows; with --sheet, draw every read cell beside its match."""
    names = item_names()
    readings = read_frames([Path(p) for p in args.images])
    index = json.loads(SPRITE.with_suffix(".json").read_text(encoding="utf-8"))
    sheets = []
    for image in args.images:
        reading = readings[Path(image).name]
        print(image)
        print(describe(reading, names))
        if args.sheet:
            sheets.append(contact_sheet(Path(image), reading, index))
    if args.sheet:
        height = sum(s.height for s in sheets)
        out = Image.new("RGB", (max(s.width for s in sheets), height))
        y = 0
        for sheet in sheets:
            out.paste(sheet, (0, y))
            y += sheet.height
        out.save(args.sheet)
        print("sheet ->", args.sheet)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Rank a VoD's frames by champions and items read, one frame per --step seconds."""
    video = Path(args.video)
    frames_dir = video.with_name(f"{video.stem}_frames")
    frames_dir.mkdir(exist_ok=True)
    if not any(frames_dir.glob("*.jpg")):
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(video),
                "-vf",
                f"fps=1/{args.step}",
                "-q:v",
                "3",
                str(frames_dir / "f%05d.jpg"),
            ],
            check=True,
        )
    paths = sorted(frames_dir.glob("*.jpg"))
    ranked = []
    for start in range(0, len(paths), 20):
        batch = paths[start : start + 20]
        for name, reading in read_frames(batch).items():
            players = [p for row in reading["rows"] for p in row]
            items = sum(1 for p in players for hit in p["items"] if hit)
            seconds = (int(name[1:6]) - 1) * args.step
            ranked.append((items, len(players), seconds, name))
            if len(players) >= 8:
                print(
                    f"  t={seconds:5d}s champions={len(players):2d} items={items:2d}  {name}",
                    flush=True,
                )
    ranked.sort(reverse=True)
    print("== top candidates ==")
    for items, players, seconds, name in ranked[:12]:
        print(f"  items={items:2d} champions={players:2d} t={seconds:5d}s  {name}")
    return 0


def cmd_grab(args: argparse.Namespace) -> int:
    """Cut the frame at --at seconds out of a local VoD."""
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            str(args.at),
            "-i",
            str(args.video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(args.out),
        ],
        check=True,
    )
    print("wrote", args.out)
    return 0


def write_labels(labels: dict[str, Any]) -> None:
    """labels.json with one player per line, so a review diff reads as rows."""
    frames = []
    for name, entry in labels.items():
        rows = ",\n".join(
            "   ["
            + ", ".join(json.dumps(player, ensure_ascii=False) for player in row)
            + "]"
            for row in entry["rows"]
        )
        head = ", ".join(
            f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}"
            for k, v in entry.items()
            if k != "rows"
        )
        frames.append(f' {json.dumps(name)}: {{{head}, "rows": [\n{rows}\n  ]}}')
    LABELS.write_text("{\n" + ",\n".join(frames) + "\n}\n", encoding="utf-8")


def cmd_label(args: argparse.Namespace) -> int:
    """Write the reader's rows for one frame into labels.json, to be reviewed by eye."""
    path = Path(args.image)
    reading = read_frames([path])[path.name]
    labels = json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists() else {}
    labels[path.name] = {
        "league": args.league,
        "source": args.source,
        "rows": [
            [
                {
                    "champion": p["champion"]["key"],
                    "items": [hit["key"] if hit else None for hit in p["items"]],
                }
                for p in row
            ]
            for row in reading["rows"]
        ],
    }
    write_labels(labels)
    print(describe(reading, item_names()))
    print(
        f"appended {path.name} to {LABELS}; review it against a contact sheet before committing"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("read")
    read.add_argument("images", nargs="+")
    read.add_argument("--sheet", type=Path)
    read.set_defaults(run=cmd_read)
    scan = commands.add_parser("scan")
    scan.add_argument("video")
    scan.add_argument("--step", type=int, default=10)
    scan.set_defaults(run=cmd_scan)
    grab = commands.add_parser("grab")
    grab.add_argument("video")
    grab.add_argument("--at", type=int, required=True)
    grab.add_argument("--out", type=Path, required=True)
    grab.set_defaults(run=cmd_grab)
    label = commands.add_parser("label")
    label.add_argument("image")
    label.add_argument("--league", required=True)
    label.add_argument("--source", required=True)
    label.set_defaults(run=cmd_label)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
