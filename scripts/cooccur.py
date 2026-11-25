#!/usr/bin/env python3
"""여러 용어를 모두 포함하는 파일 찾기 (성질·분포 축용).

폴더에서 용어 A와 B(와 C...)가 **함께** 나오는 파일을 찾는다. 대소문자는 무시한다.
예: 두 배우의 활동명이 같이 적힌 문서, 두 키워드가 한 줄에 같이 나온 로그. 표준 라이브러리만 사용한다.

예:
  cooccur.py programs/ --term 박우빈 --term 임예찬
  cooccur.py logs/ --term 'u=' --term acmepay --same-line
  cooccur.py docs/ --term 낚시 --term 지도 --any 1          # 둘 중 하나만 있는 파일은 --any 로
"""
import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="폴더 또는 파일")
    ap.add_argument("--term", action="append", required=True, help="찾을 용어(반복 가능)")
    ap.add_argument("--same-line", action="store_true", help="모든 용어가 같은 줄에 있어야 함")
    ap.add_argument("--any", type=int, default=0, metavar="N", help="최소 N개 용어만 있으면 통과 (기본: 전부)")
    args = ap.parse_args()

    terms = [t.lower() for t in args.term]
    need = args.any or len(terms)
    files = []
    if os.path.isfile(args.root):
        files = [args.root]
    else:
        for base, dirs, names in os.walk(args.root):
            dirs[:] = [d for d in dirs if d != ".git"]
            files += [os.path.join(base, n) for n in names]
    hits = 0
    for p in sorted(files):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read(5_000_000)
        except OSError:
            continue
        low = text.lower()
        if args.same_line:
            ok = [l for l in low.splitlines() if sum(t in l for t in terms) >= need]
            passed = bool(ok)
            note = ok[0].strip()[:100] if ok else ""
        else:
            present = [t for t in terms if t in low]
            passed = len(present) >= need
            note = ", ".join(present)
        if passed:
            hits += 1
            print(f"{os.path.relpath(p, args.root) if os.path.isdir(args.root) else p}  | {note}")
    print(f"\n스캔 {len(files)}개 파일 | 통과 {hits}개", file=sys.stderr)


if __name__ == "__main__":
    main()
