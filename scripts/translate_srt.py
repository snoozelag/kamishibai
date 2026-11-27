#!/usr/bin/env python3
"""読み手の言語の字幕が無い動画のために、原文の字幕を1行ずつ訳す手伝いをする。訳すのは Claude。

  split  <原文.srt> <作業フォルダ> [--size 300]
      原文の字幕を「番号<TAB>原文」の TSV に分けて書き出す（<作業フォルダ>/part-01.src.tsv …）。
      Claude は同じ番号で「番号<TAB>訳」を part-01.tr.tsv … に書く。
  join   <原文.srt> <作業フォルダ> <出力.srt>
      訳の TSV を集め、原文と同じ時刻の字幕を書き出す。抜けた番号・余った番号・空の訳があれば止まる。
"""
import argparse
import glob
import html
import re
import sys
from pathlib import Path

CUE = re.compile(r"\d+\n([\d:,]+ --> [\d:,]+)\n(.*?)(?:\n\n|\Z)", re.S)


def cues(path: Path) -> list[tuple[str, str]]:
    return [(time, html.unescape(" ".join(text.split()))) for time, text in CUE.findall(path.read_text(encoding="utf-8"))]


def split(src: Path, work: Path, size: int) -> None:
    rows = cues(src)
    work.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(rows), size):
        part = work / f"part-{start // size + 1:02d}.src.tsv"
        part.write_text("".join(f"{n}\t{text}\n" for n, (_, text) in enumerate(rows[start:start + size], start + 1)), encoding="utf-8")
    print(f"{len(rows)} 行を {(len(rows) + size - 1) // size} 個に分けた: {work}")


def join(src: Path, work: Path, out: Path) -> None:
    rows = cues(src)
    done: dict[int, str] = {}
    for part in sorted(glob.glob(str(work / "part-*.tr.tsv"))):
        for line in Path(part).read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                number, text = line.split("\t", 1)
                done[int(number)] = text.strip()
    missing = [n for n in range(1, len(rows) + 1) if not done.get(n)]
    extra = [n for n in done if n > len(rows)]
    if missing or extra:
        sys.exit(f"訳がそろっていない: 抜け {missing[:20]} 余り {extra[:5]}")
    out.write_text("".join(f"{n}\n{time}\n{done[n]}\n\n" for n, (time, _) in enumerate(rows, 1)), encoding="utf-8")
    print(f"{len(rows)} 行の訳を書いた: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("split")
    s.add_argument("src", type=Path)
    s.add_argument("work", type=Path)
    s.add_argument("--size", type=int, default=300)
    j = sub.add_parser("join")
    j.add_argument("src", type=Path)
    j.add_argument("work", type=Path)
    j.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.command == "split":
        split(args.src, args.work, args.size)
    else:
        join(args.src, args.work, args.out)


if __name__ == "__main__":
    main()
