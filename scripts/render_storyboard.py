#!/usr/bin/env python3
"""JSON仕様から、スライド＋発話の縦読みの Storyboard HTML を作る。"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
import webbrowser


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def seconds(value: str) -> float:
    h, m, s = value.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def stamp(value: float) -> str:
    minute, second = divmod(int(value), 60)
    return f"{minute:02d}:{second:02d}"


def parse_srt(path: Path | None, replacements: dict[str, str]) -> list[Cue]:
    if path is None or not path.exists():
        return []
    cues = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start, end = lines[1].split(" --> ")
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        for source, target in sorted(replacements.items(), key=lambda item: -len(item[0])):
            text = text.replace(source, target)
        cues.append(Cue(seconds(start), seconds(end), text))
    return cues


COPY_ICON = '<span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>'


# ページの見出し・ボタン・案内文。spec の "lang" で選ぶ（無ければ ja）
UI = {
    "ja": {
        "copy": "{}をコピー", "copy_line": "この行の文字起こしをコピー", "copied": "コピーしました", "copy_failed": "コピーできません",
        "no_transcript": "この区間の文字起こしはありません。", "transcript_show": "時刻つき文字起こしを見る", "n_transcript": "時刻つき文字起こし",
        "n_code": "コード", "n_spoken": "このスライドで話していたこと", "n_takeaway": "読みどころ", "n_question": "質問", "n_answer": "回答", "n_point": "補足された条件",
        "code": "コード", "slide": "スライド", "label_default": "補足", "open_at": "元の動画をこの時刻から開く",
        "spoken": "このスライドで話していたこと", "takeaway": "読みどころ", "qa_counter": "質疑", "question": "質問", "answer": "回答", "point": "補足された条件",
        "doc": "ドキュメント", "search_apple": "Apple のサイトで検索", "not_found": "本文中に見つかりません",
        "glossary": "API・用語の索引", "glossary_lead": "最初に出てくる順に並べています。S番号を押すと、その語が出てくるスライドへ移ります。",
        "source_video": "元の動画", "resources": "リソース", "related": "関連ビデオ", "links": "リソースと関連ビデオ",
        "qa_lead": "本編後の質疑から、内容を理解するための補足を整理しました。",
        "nav_glossary": "索引", "nav_links": "リソース", "home": "← 目次", "toc": "目次",
        "focus_on": "重要だけ読む", "focus_off": "全スライドに戻す", "tr_open": "文字起こしを全部開く", "tr_close": "文字起こしを全部閉じる",
        "title_default": "講演動画", "lead_default": "動画を再生せず、スライドと話の内容を上から順に読めるよう、{}枚のスライドにまとめました。",
        "overview_heading": "先に押さえると読みやすいこと", "source_note": "スライド画像と文字起こしをもとに再構成しています。",
        "update": "更新版があります · 同じ位置で再読み込み", "pair": "（{}・{}）",
    },
    "en": {
        "copy": "Copy {}", "copy_line": "Copy this line", "copied": "Copied", "copy_failed": "Couldn't copy",
        "no_transcript": "No transcript for this part.", "transcript_show": "Show timestamped transcript", "n_transcript": "transcript",
        "n_code": "code", "n_spoken": "what was said", "n_takeaway": "why it matters", "n_question": "question", "n_answer": "answer", "n_point": "added conditions",
        "code": "Code", "slide": "Slide", "label_default": "Note", "open_at": "Open the source video at this time",
        "spoken": "What was said on this slide", "takeaway": "Why it matters", "qa_counter": "Q&A", "question": "Question", "answer": "Answer", "point": "Added conditions",
        "doc": "Documentation", "search_apple": "Search Apple Developer", "not_found": "Not found in the text",
        "glossary": "APIs and terms", "glossary_lead": "Listed in order of first appearance. Tap a slide number to jump to where the term appears.",
        "source_video": "Source video", "resources": "Resources", "related": "Related videos", "links": "Resources and related videos",
        "qa_lead": "Notes from the Q&A after the talk that help with the main content.",
        "nav_glossary": "Index", "nav_links": "Resources", "home": "← Contents", "toc": "Contents",
        "focus_on": "Key slides only", "focus_off": "Show all slides", "tr_open": "Open all transcripts", "tr_close": "Close all transcripts",
        "title_default": "Talk", "lead_default": "The talk in {} slides, so you can read the slides and what was said from top to bottom without playing the video.",
        "overview_heading": "Before you read", "source_note": "Rebuilt from the slide images and the transcript.",
        "update": "Updated · Reload at the same spot", "pair": " ({} / {})",
    },
}
T = UI["ja"]


def cue_list(cues: list[Cue], start: float, end: float, alt_cues: list[Cue] | None = None) -> str:
    matched = [cue for cue in cues if cue.start < end and cue.end > start]
    if not matched:
        return f'<p class="no-transcript">{T["no_transcript"]}</p>'
    # 原文の各行は、その時刻の直前に始まった行の下に置く（字幕ごとに区切りの時刻が少しずれるため）
    below: dict[int, list[str]] = {}
    for alt in alt_cues or []:
        if not (alt.start < end and alt.end > start):
            continue
        owner = 0
        for n, cue in enumerate(matched):
            if cue.start <= alt.start + 0.5:
                owner = n
        below.setdefault(owner, []).append(alt.text)
    rows = []
    for n, cue in enumerate(matched):
        original = f'<span class="utterance-original" lang="en">{html.escape(" ".join(below[n]))}</span>' if n in below else ""
        rows.append(
            f'<li><time>{stamp(cue.start)}</time><div><span class="utterance-text">{html.escape(cue.text)}</span>{original}</div>'
            '<button class="copy-button copy-button-line" type="button" data-copy-line '
            f'aria-label="{T["copy_line"]}">{COPY_ICON}</button></li>'
        )
    return '<ol class="utterances">' + "".join(rows) + "</ol>"


def transcript_block(cues: list[Cue], alt_cues: list[Cue], key: str, start: float, end: float, labels: tuple[str, str]) -> str:
    """時刻つき文字起こし。別の言語の字幕があれば左右に並べる。"""
    button = lambda target, name: (f'<button class="copy-button" type="button" data-copy-target="{target}" '
                                   f'aria-label="{T["copy"].format(name)}"><span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></button>')
    if not alt_cues:
        return (f'<details class="transcript"><summary>{T["transcript_show"]}</summary><div class="transcript-toolbar">'
                f'{button(key + "-transcript", T["n_transcript"])}</div>'
                f'<div class="transcript-content" id="{key}-transcript">{cue_list(cues, start, end)}</div></details>')
    return (f'<details class="transcript"><summary>{T["transcript_show"]}{T["pair"].format(html.escape(labels[0]), html.escape(labels[1]))}</summary>'
            f'<div class="transcript-toolbar">{button(key + "-transcript", T["n_transcript"])}</div>'
            f'<div class="transcript-content" id="{key}-transcript">{cue_list(cues, start, end, alt_cues)}</div></details>')


def glossary_section(spec: dict, cues: list[Cue], alt_cues: list[Cue], main_end: float) -> str:
    """API・用語の索引。出てくるスライドは本文・コード・文字起こしから探す。"""
    entries = spec.get("glossary", [])
    if not entries:
        return ""
    slides = spec["slides"]
    codes = spec.get("code", [])
    texts = []
    for offset, slide in enumerate(slides):
        start = float(slide["start"])
        end = float(slides[offset + 1]["start"]) if offset + 1 < len(slides) else main_end
        parts = [str(slide.get(k, "")) for k in ("title", "spoken", "takeaway")]
        parts += [str(c.get("code", "")) + str(c.get("title", "")) for c in codes if start <= float(c.get("time", 0)) < end]
        parts += [c.text for c in cues + alt_cues if c.start < end and c.end > start]
        texts.append("\n".join(parts))
    rows = []
    for order, entry in enumerate(entries):
        term = str(entry.get("term", ""))
        needles = [term] + [str(a) for a in entry.get("aliases", [])]
        found = [i + 1 for i, text in enumerate(texts) if any(n and n in text for n in needles)]
        rows.append((found[0] if found else 10**6, order, entry, term, found))
    rows.sort()
    items = []
    for _, _, entry, term, found in rows:
        kind = str(entry.get("kind", ""))
        name = f'<code>{html.escape(term)}</code>' if kind.upper() == "API" else html.escape(term)
        url = str(entry.get("url", "")) or f"https://developer.apple.com/search/?q={urllib.parse.quote(term)}"
        doc = T["doc"] if entry.get("url") else T["search_apple"]
        chips = "".join(f'<a class="chip" href="#s{i}">S{i:02d}</a>' for i in found) or f'<span class="none">{T["not_found"]}</span>'
        items.append(
            f'<li><div class="term">{name}{f"<span class=kind>{html.escape(kind)}</span>" if kind else ""}</div>'
            f'<p>{html.escape(str(entry.get("desc", "")))}</p><div class="refs">{chips}'
            f'<a class="doc" href="{html.escape(url)}" target="_blank" rel="noopener">{doc} ↗</a></div></li>'
        )
    return (f'<section class="glossary" id="glossary"><h2>{T["glossary"]}</h2>'
            f'<p class="glossary-lead">{T["glossary_lead"]}</p><ul>{"".join(items)}</ul></section>')


def capture(video: Path, destination: Path, crop: str, at: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(at), "-i", str(video),
            "-vf", f"crop={crop}", "-frames:v", "1", "-q:v", "2", str(destination),
        ],
        check=True,
    )


def dimensions(crop: str) -> tuple[str, str]:
    parts = crop.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return parts[0], parts[1]
    return "1280", "720"


def validate_spec(spec: dict) -> None:
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        raise SystemExit("spec.slides に1枚以上のスライドが必要です")
    starts = [float(slide["start"]) for slide in slides]
    if any(current <= previous for previous, current in zip(starts, starts[1:])):
        raise SystemExit("slide.start は重複せず、時刻順に並べてください")
    main_end = float(spec.get("mainEnd", starts[-1] + 30))
    if main_end <= starts[-1]:
        raise SystemExit("mainEnd は最後の slide.start より後にしてください")
    valid_levels = {"core", "important", "context", "transition"}
    invalid = [slide.get("level") for slide in slides if slide.get("level", "context") not in valid_levels]
    if invalid:
        raise SystemExit(f"未対応のlevelがあります: {invalid}")
    for index, qa in enumerate(spec.get("qa", []), 1):
        if float(qa["end"]) <= float(qa["start"]):
            raise SystemExit(f"qa[{index}] の end は start より後にしてください")


def code_blocks(codes: list[dict], index: int, source_url: str) -> str:
    blocks = []
    for number, code in enumerate(codes, 1):
        at = float(code.get("time", 0))
        when = f'<a href="{html.escape(time_link(source_url, at))}" target="_blank" rel="noopener">{stamp(at)}</a>' if source_url else stamp(at)
        blocks.append(
            f'<details class="code-block"><summary>{T["code"]}: {html.escape(str(code.get("title", "")))}（{when}）</summary>'
            f'<div class="transcript-toolbar"><button class="copy-button" type="button" data-copy-target="s{index}-code{number}" aria-label="{T['copy'].format(T['n_code'])}"><span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></button></div>'
            f'<pre id="s{index}-code{number}"><code>{html.escape(str(code.get("code", "")))}</code></pre></details>'
        )
    return "".join(blocks)


def time_link(source_url: str, at: float) -> str:
    youtube = re.search(r"(?:youtu\.be/|[?&]v=)([\w-]{11})", source_url)
    if youtube:
        return f"https://youtu.be/{youtube.group(1)}?t={int(at)}"
    return f"{source_url.split('?')[0]}?time={int(at)}"


def slide_card(cues: list[Cue], slide: dict, index: int, count: int, end: float, width: str, height: str, source_url: str = "", codes: list[dict] | None = None, alt_cues: list[Cue] | None = None, labels: tuple[str, str] = ("字幕", "English")) -> str:
    title = str(slide.get("title", f"{T['slide']} {index}"))
    level = str(slide.get("level", "context"))
    label = str(slide.get("label", T["label_default"]))
    spoken = str(slide.get("spoken", ""))
    takeaway = str(slide.get("takeaway", ""))
    start = float(slide["start"])
    takeaway_html = f'''<aside class="takeaway"><div class="content-head"><strong>{T["takeaway"]}</strong><button class="copy-button" type="button" data-copy-target="s{index}-takeaway" aria-label="{T["copy"].format(T["n_takeaway"])}"><span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></button></div><p id="s{index}-takeaway">{html.escape(takeaway)}</p></aside>''' if takeaway else ""
    return f'''<article class="slide-card level-{html.escape(level)}" id="s{index}">
<header class="slide-head"><div><span class="counter">{T["slide"]} {index:02d}/{count}</span>{f'<a class="time" href="{html.escape(time_link(source_url, start))}" target="_blank" rel="noopener" title="{T["open_at"]}">{stamp(start)}–{stamp(end)} ↗</a>' if source_url else f'<span class="time">{stamp(start)}–{stamp(end)}</span>'}</div><span class="importance">{html.escape(label)}</span></header>
<h2>{html.escape(title)}</h2>
<figure><img loading="lazy" width="{width}" height="{height}" src="assets/slide-{index:03d}.jpg" alt="{html.escape(title)}"></figure>
<section class="spoken"><div class="content-head"><h3>{T["spoken"]}</h3><button class="copy-button" type="button" data-copy-target="s{index}-spoken" aria-label="{T["copy"].format(T["n_spoken"])}"><span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></button></div><p id="s{index}-spoken">{html.escape(spoken)}</p></section>
{takeaway_html}
{code_blocks(codes or [], index, source_url)}{transcript_block(cues, alt_cues or [], f"s{index}", start, end, labels)}
</article>'''


def qa_card(cues: list[Cue], qa: dict, index: int, total: int, alt_cues: list[Cue] | None = None, labels: tuple[str, str] = ("字幕", "English")) -> str:
    start, end = float(qa["start"]), float(qa["end"])
    return f'''<article class="qa-card" id="qa{index}">
<header><span>{T["qa_counter"]} {index}/{total}</span><time>{stamp(start)}–{stamp(end)}</time></header>
<h2>{html.escape(str(qa.get("title", "Q&A")))}</h2>
<div class="qa-grid"><section><div class="content-head"><h3>{T["question"]}</h3><button class="copy-button" type="button" data-copy-target="qa{index}-question" aria-label="{T["copy"].format(T["n_question"])}"><span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></button></div><p id="qa{index}-question">{html.escape(str(qa.get("question", "")))}</p></section><section><div class="content-head"><h3>{T["answer"]}</h3><button class="copy-button" type="button" data-copy-target="qa{index}-answer" aria-label="{T["copy"].format(T["n_answer"])}"><span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></button></div><p id="qa{index}-answer">{html.escape(str(qa.get("answer", "")))}</p></section></div>
<aside class="takeaway"><div class="content-head"><strong>{T["point"]}</strong><button class="copy-button" type="button" data-copy-target="qa{index}-point" aria-label="{T["copy"].format(T["n_point"])}"><span class="copy-icon" aria-hidden="true"><svg class="i-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><svg class="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span></button></div><p id="qa{index}-point">{html.escape(str(qa.get("point", "")))}</p></aside>
{transcript_block(cues, alt_cues or [], f"qa{index}", start, end, labels)}
</article>'''


def render(spec: dict, cues: list[Cue], alt_cues: list[Cue] | None = None, labels: tuple[str, str] = ("字幕", "English")) -> str:
    global T
    T = UI.get(str(spec.get("lang", "ja")), UI["en"])
    alt_cues = alt_cues or []
    slides = spec["slides"]
    count = len(slides)
    main_end = float(spec.get("mainEnd", slides[-1]["start"] + 30))
    width, height = dimensions(str(spec.get("crop", "iw:ih:0:0")))
    source_url = str(spec.get("sourceUrl", ""))
    codes = sorted(spec.get("code", []), key=lambda item: float(item.get("time", 0)))
    slide_html = []
    for offset, slide in enumerate(slides):
        start = float(slide["start"])
        end = float(slides[offset + 1]["start"]) if offset + 1 < count else main_end
        own = [c for c in codes if (offset == 0 or float(c.get("time", 0)) >= start) and (float(c.get("time", 0)) < end or offset + 1 == count)]
        slide_html.append(slide_card(cues, slide, offset + 1, count, end, width, height, source_url, own, alt_cues, labels))

    def link_list(items: list[dict]) -> str:
        return "".join(f'<li><a href="{html.escape(str(i.get("url", "")))}" target="_blank" rel="noopener">{html.escape(str(i.get("title", "")))}</a></li>' for i in items)

    resources, related = spec.get("resources", []), spec.get("related", [])
    links_section = ""
    if resources or related or source_url:
        parts = []
        if source_url:
            parts.append(f'<section><h3>{T["source_video"]}</h3><ul><li><a href="{html.escape(source_url)}" target="_blank" rel="noopener">{html.escape(source_url)}</a></li></ul></section>')
        if resources:
            parts.append(f'<section><h3>{T["resources"]}</h3><ul>{link_list(resources)}</ul></section>')
        if related:
            parts.append(f'<section><h3>{T["related"]}</h3><ul>{link_list(related)}</ul></section>')
        links_section = f'<section class="links-heading" id="links"><h2>{T["links"]}</h2>{"".join(parts)}</section>'

    qas = spec.get("qa", [])
    qa_html = "".join(qa_card(cues, qa, i, len(qas), alt_cues, labels) for i, qa in enumerate(qas, 1))
    qa_section = f'<section class="qa-heading" id="qa"><h2>Q&amp;A</h2><p>{T["qa_lead"]}</p></section>{qa_html}' if qas else ""
    nav = "".join(
        f'<a href="#s{int(section["slide"])}">{html.escape(str(section["label"]))}</a>'
        for section in spec.get("sections", [])
    )
    if qas:
        nav += '<a href="#qa">Q&amp;A</a>'
    glossary = glossary_section(spec, cues, alt_cues, main_end)
    if glossary:
        nav += f'<a href="#glossary">{T["nav_glossary"]}</a>'
    if links_section:
        nav += f'<a href="#links">{T["nav_links"]}</a>'
    if spec.get("homeUrl"):
        nav = f'<a class="home" href="{html.escape(spec["homeUrl"], quote=True)}">{T["home"]}</a>' + nav
    nav += f'<button class="focus-toggle" type="button">{T["focus_on"]}</button>'
    nav += f'<button class="transcript-toggle" type="button">{T["tr_open"]}</button>'

    overview = spec.get("overview", {})
    meanings = "".join(
        f'<div class="meaning"><b>{html.escape(str(item.get("label", "")))}</b>{html.escape(str(item.get("text", "")))}</div>'
        for item in overview.get("meanings", [])
    )
    meaning_grid = f'<div class="meaning-grid">{meanings}</div>' if meanings else ""
    summary = "".join(
        f'<section><b>{html.escape(str(item.get("label", "")))}</b>{html.escape(str(item.get("text", "")))}</section>'
        for item in overview.get("summary", [])
    )
    summary_grid = f'<div class="summary">{summary}</div>' if summary else ""
    version = str(time.time_ns())
    title = str(spec.get("title", T["title_default"]))
    eyebrow = str(spec.get("eyebrow", ""))
    lead = str(spec.get("lead", T["lead_default"].format(count)))
    overview_heading = str(overview.get("heading", T["overview_heading"]))
    overview_intro = str(overview.get("intro", ""))
    source_note = str(spec.get("sourceNote", T["source_note"]))

    return f'''<!doctype html><html lang="{html.escape(str(spec.get("lang", "ja")))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">
<title>{html.escape(title)}</title><meta name="storyboard-version" content="{version}"><style>{CSS}</style></head><body>
<nav class="toc" aria-label="{T["toc"]}">{nav}</nav>
<header class="hero"><div class="hero-inner">{f'<div class="eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else ""}<h1>{html.escape(title)}</h1><p class="lead">{html.escape(lead)}</p></div></header>
<section class="overview"><div class="interpretation"><h2>{html.escape(overview_heading)}</h2><p>{html.escape(overview_intro)}</p>{meaning_grid}</div>{summary_grid}</section>
<main>{''.join(slide_html)}{qa_section}{glossary}{links_section}</main>
<footer class="footer">{html.escape(source_note)}</footer><div class="update-notice" hidden><button type="button">{T["update"]}</button></div>
<script>const L={json.dumps({k: T[k] for k in ('copied', 'copy_failed', 'focus_on', 'focus_off', 'tr_open', 'tr_close')}, ensure_ascii=False)};{UPDATE_JS}</script></body></html>'''


CSS = r'''
:root{--bg:#fff;--fg:#0d0d0d;--muted:#5d5d5d;--faint:#8f8f8f;--line:#e5e5e5;--soft:#f4f4f4;--softer:#f9f9f9;--chip:#ececec;--accent:#0d0d0d;--accent-fg:#fff;--shadow:0 1px 2px #0000000d}
@media(prefers-color-scheme:dark){:root{--bg:#212121;--fg:#ececec;--muted:#b4b4b4;--faint:#8e8e8e;--line:#383838;--soft:#2f2f2f;--softer:#282828;--chip:#3a3a3a;--accent:#ececec;--accent-fg:#0d0d0d;--shadow:none}}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--fg);font-family:ui-sans-serif,-apple-system,system-ui,"Hiragino Sans","Yu Gothic",sans-serif;line-height:1.8;-webkit-font-smoothing:antialiased}a{color:inherit}
.hero{padding:72px 0 8px}.hero-inner{max-width:760px;margin:auto;padding:0 24px}.eyebrow{font-size:13px;color:var(--muted);font-weight:500}h1{font-size:clamp(28px,4.4vw,40px);line-height:1.3;letter-spacing:-.01em;font-weight:650;margin:.3em 0 .5em}.lead{font-size:16px;color:var(--muted);margin:0}
.overview{max-width:760px;margin:32px auto 0;padding:0 24px}.interpretation{border:1px solid var(--line);border-radius:16px;padding:22px 24px}.interpretation h2{font-size:17px;font-weight:650;margin:0 0 8px}.interpretation p{margin:0;color:var(--fg)}.meaning-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}.meaning{padding:14px 16px;border-radius:12px;background:var(--soft);font-size:14px}.meaning b{display:block;margin-bottom:3px;font-weight:650}.summary{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:14px 0 0}.summary section{border:1px solid var(--line);border-radius:12px;padding:14px 16px;font-size:14px}.summary b{display:block;font-size:12px;color:var(--muted);font-weight:600;margin-bottom:3px}
.toc{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:6px;overflow:auto;white-space:nowrap;justify-content:safe center}.toc a,.toc button{text-decoration:none;background:transparent;border:1px solid var(--line);color:var(--fg);border-radius:999px;padding:6px 12px;font:inherit;font-size:13px;font-weight:500;white-space:nowrap;cursor:pointer}.toc a:hover,.toc button:hover{background:var(--soft)}.toc button{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}.toc button:hover{background:var(--accent);opacity:.85}
.focus-mode .level-context,.focus-mode .level-transition{display:none}.focus-mode .toc a{display:none}.focus-mode .toc a.home{display:block}.focus-mode .toc .focus-toggle{display:block}
main{max-width:760px;margin:0 auto;padding:28px 24px 100px}
.slide-card,.qa-card{padding:22px 24px 24px;margin:0 0 20px;border:1px solid var(--line);border-radius:16px;scroll-margin-top:64px}.slide-card.level-core{border-color:var(--fg)}.slide-head,.qa-card>header{padding-bottom:12px;border-bottom:1px solid var(--line)}.slide-head,.qa-card>header{display:flex;justify-content:space-between;align-items:center;gap:12px}.counter{font-size:13px;font-weight:600;color:var(--muted);font-variant-numeric:tabular-nums}.time{font-size:13px;color:var(--faint);margin-left:10px;font-variant-numeric:tabular-nums}a.time{text-decoration:none}a.time:hover{color:var(--fg);text-decoration:underline}
.importance{font-size:12px;font-weight:600;border-radius:999px;padding:3px 10px;background:var(--soft);color:var(--muted)}.level-core .importance{background:var(--accent);color:var(--accent-fg)}.level-important .importance{background:transparent;color:var(--fg);box-shadow:inset 0 0 0 1px var(--fg)}.level-transition .importance{background:transparent;color:var(--faint)}
.slide-card h2,.qa-card h2{font-size:clamp(21px,2.6vw,25px);line-height:1.45;font-weight:650;letter-spacing:-.005em;margin:14px 0 16px}.level-context h2,.level-transition h2{color:var(--muted)}
figure{margin:0 0 22px}figure img{width:100%;height:auto;display:block;border-radius:12px;border:1px solid var(--line)}
h3{font-size:13px;font-weight:600;margin:0;color:var(--muted)}.content-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 6px}.content-head h3,.content-head strong{margin:0}
.copy-button{appearance:none;display:inline-grid;place-items:center;flex:0 0 auto;width:32px;height:32px;padding:0;border:0;border-radius:8px;background:transparent;color:var(--faint);font:inherit;line-height:1;cursor:pointer;transition:background .15s,color .15s}.copy-button:hover{background:var(--soft);color:var(--fg)}.copy-button:focus-visible{outline:2px solid var(--fg);outline-offset:1px}.copy-button.is-copied{color:var(--fg)}.copy-button.is-error{color:#d33}.copy-icon{display:grid;place-items:center}.copy-icon svg{width:16px;height:16px;display:block}.copy-icon .i-check{display:none}.is-copied .copy-icon .i-copy{display:none}.is-copied .copy-icon .i-check{display:block}
.spoken p,.takeaway p,.qa-grid p{font-size:16.5px;margin:0}.spoken{padding:0 0 18px}.takeaway{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:14px 16px}.takeaway strong{font-size:13px;font-weight:600;color:var(--muted)}.level-core .takeaway{background:transparent;border:1px solid var(--fg)}
details{margin-top:14px;border-top:1px solid var(--line);padding-top:12px}summary{cursor:pointer;font-size:13px;font-weight:500;color:var(--muted);list-style-position:outside}summary:hover{color:var(--fg)}.transcript-toolbar{display:flex;justify-content:flex-end;margin:4px 0 -4px}
.utterances{list-style:none;padding:8px 0 0;margin:0}.utterances li{display:grid;grid-template-columns:48px minmax(0,1fr) 28px;gap:10px;align-items:start;padding:6px 0;border-bottom:1px solid var(--line);font-size:14px;line-height:1.7}.utterances time{color:var(--faint);font-variant-numeric:tabular-nums}.utterance-text{min-width:0;overflow-wrap:anywhere}.utterances li>div{min-width:0}.utterance-original{display:block;margin-top:2px;font-size:13px;line-height:1.6;color:var(--faint);overflow-wrap:anywhere}.copy-button-line{width:28px;height:28px;opacity:0}.utterances li:hover .copy-button-line,.copy-button-line:focus-visible{opacity:1}.copy-button-line .copy-icon svg{width:14px;height:14px}
.code-block pre{margin:8px 0 0;padding:14px 16px;background:var(--softer);border:1px solid var(--line);border-radius:12px;overflow:auto;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--fg)}
.bilingual{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:6px}.transcript-column+.transcript-column{border-left:1px solid var(--line);padding-left:20px}.transcript-column h4{margin:0;font-size:12px;font-weight:600;color:var(--faint);text-transform:none}.no-transcript{font-size:14px;color:var(--muted)}
.qa-heading,.glossary,.links-heading{margin:72px 0 8px;padding-top:0}.qa-heading h2,.glossary h2,.links-heading h2{font-size:24px;font-weight:650;margin:0 0 6px}.qa-heading p,.glossary-lead{color:var(--muted);margin:0 0 14px;font-size:14px}.qa-card>header span{font-size:13px;font-weight:600;color:var(--muted)}.qa-card>header time{font-size:13px;color:var(--faint)}.qa-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}.qa-grid section{background:var(--soft);padding:14px 16px;border-radius:12px}
.glossary ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:10px}.glossary li{border:1px solid var(--line);border-radius:12px;padding:12px 14px}.glossary .term{font-weight:650;font-size:15px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}.glossary code{font:600 14px ui-monospace,SFMono-Regular,Menlo,monospace}.glossary .kind{font-size:11px;font-weight:500;color:var(--muted);background:var(--soft);border-radius:999px;padding:1px 8px}.glossary li p{margin:4px 0 8px;font-size:14px;color:var(--muted)}.glossary .refs{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:12px}.glossary .chip{text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:1px 8px;font-variant-numeric:tabular-nums}.glossary .chip:hover{background:var(--soft)}.glossary .doc{margin-left:auto;color:var(--muted)}.glossary .none{color:var(--faint)}
.links-heading h3{margin:18px 0 4px}.links-heading ul{margin:0;padding-left:1.2em}.links-heading li{margin:3px 0;font-size:14px}.links-heading a{color:var(--muted)}.links-heading a:hover{color:var(--fg)}
.footer{text-align:center;color:var(--faint);font-size:12px;padding:48px 20px}
.update-notice{position:fixed;right:18px;bottom:18px;z-index:40}.update-notice[hidden]{display:none}.update-notice button{appearance:none;border:0;border-radius:999px;background:var(--accent);color:var(--accent-fg);font:inherit;font-size:13px;font-weight:600;padding:10px 16px;box-shadow:0 4px 16px #0003;cursor:pointer}
@media(max-width:700px){.slide-card,.qa-card{padding:16px 14px 18px;border-radius:14px}.transcript-column+.transcript-column{border-left:0;padding-left:0;border-top:1px solid var(--line);padding-top:10px}.hero{padding:44px 0 4px}.hero-inner{padding:0 16px}.overview,main{padding-left:16px;padding-right:16px}.meaning-grid,.summary,.qa-grid,.bilingual,.glossary ul{grid-template-columns:1fr}.toc{justify-content:flex-start}.slide-head{align-items:flex-start}.time{display:block;margin:0}.spoken p,.takeaway p,.qa-grid p{font-size:16px}.utterances li{grid-template-columns:44px minmax(0,1fr) 28px;gap:8px}.copy-button-line{opacity:1}}
@media print{.toc,.update-notice,.copy-button,.transcript-toolbar{display:none}body{background:#fff;color:#000}.slide-card,.qa-card{break-inside:avoid;page-break-inside:avoid}details{display:none}}
'''

UPDATE_JS = r'''
(() => {
  const current=document.querySelector('meta[name="storyboard-version"]').content;
  const notice=document.querySelector('.update-notice');
  const reloadButton=notice.querySelector('button');
  const focusButton=document.querySelector('.focus-toggle');
  const transcriptButton=document.querySelector('.transcript-toggle');
  async function check(){try{const response=await fetch(`index.html?check=${Date.now()}`,{cache:'no-store'});const source=await response.text();const match=source.match(/name="storyboard-version" content="([^"]+)"/);if(match&&match[1]!==current)notice.hidden=false}catch(_){}}
  function textToCopy(target){const rows=[...target.querySelectorAll('.utterances li')];if(rows.length){return rows.map(row=>{const time=row.querySelector('time')?.textContent.trim()||'';const text=row.querySelector('.utterance-text')?.textContent.trim()||'';return `${time} ${text}`.trim()}).join('\n')}return target.innerText.trim()}
  async function writeClipboard(text){if(navigator.clipboard&&window.isSecureContext){try{await navigator.clipboard.writeText(text);return}catch(_){}}const area=document.createElement('textarea');area.value=text;area.readOnly=true;area.style.position='fixed';area.style.top='0';area.style.left='-9999px';area.style.opacity='0';document.body.appendChild(area);area.focus();area.select();area.setSelectionRange(0,area.value.length);const copied=document.execCommand('copy');area.remove();if(!copied)throw new Error('copy failed')}
  document.addEventListener('click',async event=>{const button=event.target.closest('.copy-button');if(!button)return;const target=button.hasAttribute('data-copy-line')?button.closest('li')?.querySelector('.utterance-text'):document.getElementById(button.dataset.copyTarget);if(!target)return;const icon=button.querySelector('.copy-icon');const originalLabel=button.getAttribute('aria-label');clearTimeout(button.copyTimer);button.disabled=true;button.classList.remove('is-copied','is-error');try{await writeClipboard(textToCopy(target));button.setAttribute('aria-label',L.copied);button.classList.add('is-copied')}catch(_){button.setAttribute('aria-label',L.copy_failed);button.classList.add('is-error')}button.copyTimer=setTimeout(()=>{button.setAttribute('aria-label',originalLabel);button.classList.remove('is-copied','is-error');button.disabled=false},1400)});
  function updateTranscriptButton(){const details=[...document.querySelectorAll('details.transcript')];const allOpen=details.length>0&&details.every(item=>item.open);transcriptButton.textContent=allOpen?L.tr_close:L.tr_open;transcriptButton.setAttribute('aria-pressed',allOpen?'true':'false')}
  transcriptButton.addEventListener('click',()=>{const details=[...document.querySelectorAll('details.transcript')];const shouldOpen=details.some(item=>!item.open);details.forEach(item=>{item.open=shouldOpen});updateTranscriptButton()});
  document.addEventListener('toggle',event=>{if(event.target.matches('details.transcript'))updateTranscriptButton()},true);
  reloadButton.addEventListener('click',()=>{sessionStorage.setItem('storyboard-scroll',String(window.scrollY));location.reload()});
  focusButton.addEventListener('click',()=>{const active=document.body.classList.toggle('focus-mode');focusButton.textContent=active?L.focus_off:L.focus_on;sessionStorage.setItem('storyboard-focus',active?'1':'0');scrollTo({top:document.querySelector('main').offsetTop-60,behavior:'smooth'})});
  if(sessionStorage.getItem('storyboard-focus')==='1'){document.body.classList.add('focus-mode');focusButton.textContent=L.focus_off}
  updateTranscriptButton();
  const saved=sessionStorage.getItem('storyboard-scroll');if(saved){sessionStorage.removeItem('storyboard-scroll');requestAnimationFrame(()=>scrollTo(0,Number(saved)))}
  setInterval(check,4000);
})();
'''



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
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--srt-alt", type=Path, help="並べて表示する別の言語の字幕（例: 英語の SRT）")
    parser.add_argument("--labels", default="字幕,English", help="文字起こしの2列の見出し。例: 日本語,English")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--open", action="store_true", help="生成したHTMLをブラウザで開く")
    parser.add_argument("--browser", help="開くブラウザの名前（例: Safari）。省略すると OS の標準ブラウザ")
    parser.add_argument("--skip-capture", action="store_true")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    validate_spec(spec)
    crop = str(spec.get("crop", "iw:ih:0:0"))
    args.out.mkdir(parents=True, exist_ok=True)
    assets = args.out / "assets"
    assets.mkdir(exist_ok=True)
    if not args.skip_capture:
        for index, slide in enumerate(spec["slides"], 1):
            capture(args.video, assets / f"slide-{index:03d}.jpg", str(slide.get("crop", crop)), float(slide.get("capture", slide["start"] + 0.8)))

    cues = parse_srt(args.srt, {str(k): str(v) for k, v in spec.get("replacements", {}).items()})
    page = args.out / "index.html"
    alt_cues = parse_srt(args.srt_alt, {})
    labels = tuple((args.labels.split(",") + ["", ""])[:2])
    page.write_text(render(spec, cues, alt_cues, labels), encoding="utf-8")
    print(page)
    if args.open:
        open_page(page, args.browser)


if __name__ == "__main__":
    main()
