#!/usr/bin/env python3
"""動画のスライド切り替え候補を検出し、ブラウザで確認できる一覧を作る。"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path
import webbrowser


def detect(video: Path, crop: str, start: float, end: float, threshold: float) -> list[float]:
    duration = max(0.1, end - start)
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "info", "-ss", str(start), "-t", str(duration),
            "-i", str(video), "-vf", f"crop={crop},select='gt(scene,{threshold})',showinfo",
            "-fps_mode", "vfr", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [start + float(value) for value in re.findall(r"pts_time:([0-9.]+)", result.stderr)]


def merge_nearby(values: list[float], window: float) -> list[float]:
    merged = []
    for value in values:
        if merged and value - merged[-1] <= window:
            merged[-1] = value
        else:
            merged.append(value)
    return merged


def stamp(value: float) -> str:
    minute, second = divmod(int(value), 60)
    return f"{minute:02d}:{second:02d}"


def capture(video: Path, destination: Path, crop: str, at: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(at), "-i", str(video),
            "-vf", f"crop={crop}", "-frames:v", "1", "-q:v", "2", str(destination),
        ],
        check=True,
    )


def render(items: list[dict], video: Path, crop: str, threshold: float) -> str:
    cards = "".join(
        f'''<article><header><b>候補 {item["index"]:02d}</b><time>{stamp(item["time"])}</time></header>
        <img loading="lazy" src="{html.escape(item["image"])}" alt="{stamp(item["time"])} のフレーム">
        <code>{item["time"]:.3f}</code></article>'''
        for item in items
    )
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>スライド切り替え候補</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#181715;color:#f5f1ea;font-family:-apple-system,"Hiragino Sans",sans-serif}}
    header.top{{padding:28px 24px;background:#24211d;position:sticky;top:0;z-index:2;border-bottom:1px solid #443f38}}
    h1{{font-size:24px;margin:0 0 6px}}p{{margin:0;color:#beb6aa;font-size:13px}}main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px;padding:22px}}
    article{{background:#24211d;border:1px solid #443f38;border-radius:12px;padding:12px}}article header{{display:flex;justify-content:space-between;margin-bottom:8px}}time,code{{color:#f7b447;font-variant-numeric:tabular-nums}}
    img{{width:100%;height:auto;display:block;border-radius:7px;background:#fff}}code{{display:block;margin-top:8px;font-size:11px}}
    </style></head><body><header class="top"><h1>スライド切り替え候補 · {len(items)}件</h1><p>{html.escape(str(video))}<br>crop={html.escape(crop)} / scene={threshold}</p></header><main>{cards}</main></body></html>'''



def open_page(page: Path, browser: str | None) -> None:
    """生成したページを開く。指定が無ければ OS の標準ブラウザ、macOS で指定があれば open -a を使う。"""
    url = page.resolve().as_uri()
    if browser and sys.platform == "darwin":
        subprocess.run(["open", "-a", browser, url], check=True)
    elif browser:
        webbrowser.get(browser).open(url)
    else:
        webbrowser.open(url)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--crop", default="iw:ih:0:0", help="ffmpeg crop: width:height:x:y")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--threshold", type=float, default=0.04)
    parser.add_argument("--settle", type=float, default=0.8, help="切り替え後、画像を撮るまでの秒数")
    parser.add_argument("--merge-window", type=float, default=0.2)
    parser.add_argument("--open", action="store_true", help="生成したHTMLをブラウザで開く")
    parser.add_argument("--browser", help="開くブラウザの名前（例: Safari）。省略すると OS の標準ブラウザ")
    args = parser.parse_args()

    if args.end is None:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(args.video)],
            capture_output=True, text=True, check=True,
        )
        args.end = float(result.stdout.strip())

    args.out.mkdir(parents=True, exist_ok=True)
    assets = args.out / "candidates"
    assets.mkdir(exist_ok=True)
    times = merge_nearby([args.start, *detect(args.video, args.crop, args.start, args.end, args.threshold)], args.merge_window)
    items = []
    for index, change in enumerate(times, 1):
        at = min(change + args.settle, args.end - 0.1)
        image = assets / f"candidate-{index:03d}.jpg"
        capture(args.video, image, args.crop, at)
        items.append({"index": index, "time": change, "capture": at, "image": f"candidates/{image.name}"})

    (args.out / "candidates.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    page = args.out / "candidates.html"
    page.write_text(render(items, args.video, args.crop, args.threshold), encoding="utf-8")
    print(page)
    if args.open:
        open_page(page, args.browser)


if __name__ == "__main__":
    main()
