#!/usr/bin/env python3
"""여러 파일의 목록 항목 교집합 (분포 축용).

아는 속성마다 후보 집합(예: 출연자별 출연작 목록)을 만들고 공통 항목을 구한다.
불릿(`- `, `* `, `1. `) 줄을 항목으로 본다. 표준 라이브러리만 사용한다.

예:
  intersect.py people/person-000.md people/person-001.md --section 출연작
  intersect.py a.md b.md c.md --min 2          # 2개 이상 파일에 나온 항목
  intersect.py *.txt --regex 'id=(\\w+)'        # 줄에서 정규식 첫 그룹을 항목으로
"""
import argparse
import re
import sys
from collections import defaultdict

BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$")


def items_of(path, section, regex):
    out, in_section = [], section is None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if section is not None and re.match(r"^\s*#+\s", line):
                in_section = section.lower() in line.lower()
                continue
            if not in_section:
                continue
            if regex:
                m = regex.search(line)
                if m:
                    out.append((m.group(1) if m.groups() else m.group(0)).strip())
            else:
                m = BULLET.match(line)
                if m:
                    out.append(m.group(1).strip())
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--section", help="제목 줄에 이 글자가 있는 구획의 항목만 사용 (예: 출연작)")
    ap.add_argument("--regex", help="불릿 대신 줄에서 정규식(첫 그룹)으로 항목 추출")
    ap.add_argument("--min", type=int, default=0, help="몇 개 이상의 파일에 나와야 하는지 (기본: 전부)")
    ap.add_argument("--ignore-case", action="store_true")
    args = ap.parse_args()

    rx = re.compile(args.regex) if args.regex else None
    seen = defaultdict(set)
    for p in args.files:
        for it in items_of(p, args.section, rx):
            seen[it.lower() if args.ignore_case else it].add(p)
    need = args.min or len(args.files)
    rows = sorted(((len(v), k) for k, v in seen.items() if len(v) >= need), key=lambda x: (-x[0], x[1]))
    print(f"파일 {len(args.files)}개 | 항목 {len(seen)}개 | {need}개 이상에 나온 항목 {len(rows)}개")
    for n, k in rows:
        print(f"{n:>3}/{len(args.files)}  {k}")
    if not rows:
        print("교집합이 없다. --min 을 낮추거나 항목 추출 방식(--section, --regex)을 확인할 것.", file=sys.stderr)


if __name__ == "__main__":
    main()
