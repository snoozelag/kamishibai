#!/usr/bin/env python3
"""Apple Developer の動画ページ（WWDC・Tech Talks）から、動画・字幕・章立て・コード・リンクを取り出す。"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SITE = "https://developer.apple.com"
# 字幕の言語コードと、同じ言語のページがある地域パス
LOCALE_PATHS = {"ja": "/jp", "ko": "/kr", "zh": "/cn"}
# 古い動画の字幕は3文字の言語コードで配信される
LANG_ALIASES = {"eng": "en", "jpn": "ja", "zho": "zh", "kor": "ko", "spa": "es", "fra": "fr", "por": "pt", "deu": "de"}


def get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8")


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def video_path(url: str) -> str:
    match = re.search(r"/videos/play/([^/]+)/(\d+)", url)
    if not match:
        raise SystemExit(f"Apple Developer の動画ページの URL ではありません: {url}")
    return f"/videos/play/{match.group(1)}/{match.group(2)}/"


def page_info(page: str) -> dict:
    title = text(re.search(r"<title>([^<]*)", page).group(1)).split(" - ")[0]
    details = page[page.find('data-supplement-id="details"'):]
    description = re.search(r"</h1>\s*</div>\s*<p>(.*?)</p>", details, re.S)
    chapters: dict[float, str] = {}
    for start, name in re.findall(r'class="jump-to-time"[^>]*data-start-time="(\d+)"[^>]*>([^<]*)</a>', page):
        chapters.setdefault(float(start), text(name))  # ページ内に章の一覧が2回載ることがある
    code = []
    for block in re.findall(r'<li class="sample-code-main-container">(.*?)</li>', page, re.S):
        head = re.search(r'data-start-time="(\d+)"[^>]*>([^<]*)</a>', block)
        body = re.search(r'<code>(.*?)</code>', block, re.S)
        if head and body:
            code.append({"time": float(head.group(1)), "title": text(head.group(2)),
                         "code": html.unescape(re.sub(r"<[^>]+>", "", body.group(1)))})
    resources = [{"title": text(t), "url": u} for u, t in re.findall(
        r'<li class="document"><a href="([^"]+)"[^>]*>(.*?)</a>', details)]
    related = [{"title": text(t), "url": SITE + u if u.startswith("/") else u} for u, t in re.findall(
        r'<li class="video">\s*<a href="([^"]+)">(.*?)</a>', details)]
    videos: dict[str, str] = {}
    for url, quality in re.findall(r'href="(https://devstreaming-cdn[^"?]+?_(hd|sd)[^"?/]*\.mp4)', page):
        videos.setdefault(quality, url)
    stream = re.search(r'(https://devstreaming-cdn[^"\']+/(?:cmaf|hls_vod_mvp)\.m3u8)', page)
    transcript = [(float(t), text(line)) for t, line in re.findall(r'data-start="([\d.]+)"[^>]*>([^<]*)', page)]
    return {"title": title, "description": text(description.group(1)) if description else "",
            "chapters": [{"start": k, "title": v} for k, v in sorted(chapters.items())], "code": code,
            "transcript": [row for row in transcript if row[1]], "resources": resources, "related": related,
            "videos": videos, "stream": stream.group(1) if stream else ""}


def subtitle_tracks(master_url: str) -> dict[str, str]:
    tracks: dict[str, str] = {}
    for line in get(master_url).splitlines():
        if "TYPE=SUBTITLES" not in line or 'GROUP-ID="subsC"' in line:
            continue  # subsC は聴覚障害者向けの字幕（効果音の説明入り）
        lang = re.search(r'LANGUAGE="([^"]+)"', line).group(1)
        tracks.setdefault(LANG_ALIASES.get(lang, lang), re.search(r'URI="([^"]+)"', line).group(1))
    return tracks


def srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def transcript_to_srt(rows: list[tuple[float, str]]) -> str:
    """ページ内の文字起こし（文の開始時刻だけ）から SRT を作る。終わりは次の文の開始時刻にする。"""
    return "".join(
        f"{n}\n{srt_time(start)} --> {srt_time(rows[n][0] if n < len(rows) else start + 4)}\n{line}\n\n"
        for n, (start, line) in enumerate(rows, 1))


def subtitles_to_srt(master_url: str, uri: str) -> str:
    stream = master_url.rsplit("/", 1)[0]
    base = f"{stream}/{uri.rsplit('/', 1)[0]}"
    segments = [line for line in get(f"{stream}/{uri}").splitlines() if line and not line.startswith("#")]
    vtt = "".join(get(f"{base}/{segment}") + "\n\n" for segment in segments)
    seen, cues = set(), []
    for start, end, body in re.findall(
            r"(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3})[^\n]*\n(.*?)(?:\n\n|\Z)", vtt, re.S):
        if (start, end) in seen:
            continue  # セグメントの境目で同じ字幕が重複する
        seen.add((start, end))
        cues.append((start, end, " ".join(body.strip().splitlines())))
    cues.sort()
    return "".join(
        f"{n}\n{a.replace('.', ',')} --> {b.replace('.', ',')}\n{t}\n\n" for n, (a, b, t) in enumerate(cues, 1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="例: https://developer.apple.com/videos/play/wwdc2025/256/")
    parser.add_argument("--out", type=Path, required=True, help="video.mp4・text.srt・meta.json を置くフォルダ")
    parser.add_argument("--lang", default="ja", help="字幕の言語（ja, en, ko, zh など）。既定は ja")
    parser.add_argument("--fallback", default="en", help="指定の言語の字幕が無いときに使う言語。既定は en")
    parser.add_argument("--alt", default="en", help="並べて表示する原文の字幕の言語。text.<言語>.srt に保存する。none で取らない")
    parser.add_argument("--quality", choices=["hd", "sd"], default="hd")
    parser.add_argument("--skip-video", action="store_true", help="動画をダウンロードしない（字幕と情報だけ）")
    args = parser.parse_args()

    path = video_path(args.url)
    source_url = SITE + path
    english = page_info(get(source_url))
    local = page_info(get(SITE + LOCALE_PATHS[args.lang] + path)) if args.lang in LOCALE_PATHS else english
    args.out.mkdir(parents=True, exist_ok=True)

    tracks = subtitle_tracks(english["stream"]) if english["stream"] else {}
    lang = args.lang if args.lang in tracks else args.fallback if args.fallback in tracks else ""
    source = "stream"
    if lang:
        (args.out / "text.srt").write_text(subtitles_to_srt(english["stream"], tracks[lang]))
    elif local["transcript"]:
        # 配信に字幕が無い場合は、ページに載っている文字起こしを使う
        lang, source = (args.lang if local is not english else "en"), "page"
        (args.out / "text.srt").write_text(transcript_to_srt(local["transcript"]))
    else:
        print("この動画には字幕も文字起こしもありません。README の「字幕の用意」を参照してください", file=sys.stderr)
    # 読み手の言語の字幕が無いときは、原文を text.<言語>.srt に残し、Claude が text.srt を訳で作り直す
    needs_translation = bool(lang) and lang != args.lang and args.alt != "none"
    if needs_translation:
        alt = lang
        (args.out / f"text.{alt}.srt").write_text((args.out / "text.srt").read_text())
    else:
        alt = "" if args.alt == "none" or args.alt == lang else args.alt
        if alt and alt in tracks:
            (args.out / f"text.{alt}.srt").write_text(subtitles_to_srt(english["stream"], tracks[alt]))
        elif alt == "en" and english["transcript"]:
            (args.out / "text.en.srt").write_text(transcript_to_srt(english["transcript"]))
        elif alt:
            alt = ""
    if needs_translation:
        print(f"{args.lang} の字幕が無いため、text.srt は {lang} のままです。scripts/translate_srt.py で1行ずつ訳し、"
              f"text.srt を訳に置き換えてください（原文は text.{alt}.srt）", file=sys.stderr)

    meta = {
        "sourceUrl": source_url, "title": local["title"], "titleEnglish": english["title"],
        "description": local["description"], "subtitleLanguage": lang, "subtitleSource": source, "altSubtitleLanguage": alt, "subtitleLanguages": sorted(tracks),
        "needsTranslation": needs_translation,
        "chapters": local["chapters"] or english["chapters"], "code": english["code"],
        "resources": english["resources"], "related": local["related"] or english["related"],
    }
    (args.out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    video = english["videos"].get(args.quality) or next(iter(english["videos"].values()), "")
    if not args.skip_video:
        if not video:
            raise SystemExit("ダウンロードできる動画が見つかりませんでした")
        subprocess.run(["curl", "-fL", "--progress-bar", video, "-o", str(args.out / "video.mp4")], check=True)
    print(json.dumps({"out": str(args.out), "title": meta["title"], "subtitle": lang,
                      "chapters": len(meta["chapters"]), "code": len(meta["code"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
