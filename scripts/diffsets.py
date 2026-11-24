#!/usr/bin/env python3
"""두 버전의 차이에서 새로 생긴/사라진 항목만 추출한다 (분포, 시간 축용).

파일 두 개(이전, 이후)를 비교하거나, 폴더 두 개를 비교한다. 표준 라이브러리만 사용한다.

항목 추출 방식(파일 비교 시, --by):
  lines     비어 있지 않은 줄 (기본)
  tokens    식별자/경로/URL처럼 보이는 토큰
  strings   바이너리에서 출력 가능한 문자열(strings 명령처럼)
  regex:PAT 정규식 일치(그룹이 있으면 첫 번째 그룹)
폴더 비교는 상대 경로와 내용 해시로 추가/삭제/변경 파일을 구분한다(.git 제외).

예:
  diffsets.py old_list.txt new_list.txt
  diffsets.py old.bin new.bin --by strings --min 8
  diffsets.py patch_v1/ patch_v2/
  diffsets.py a.json b.json --by regex:'"id":\\s*"(\\w+)"' --show 50
"""
import argparse
import hashlib
import os
import re
import sys


def items_from_file(path, by, minlen, ignore_case):
    data = open(path, "rb").read()
    if by == "strings":
        found = [m.decode("ascii", "replace") for m in re.findall(rb"[\x20-\x7e]{%d,}" % minlen, data)]
    else:
        text = data.decode("utf-8", "replace")
        if by == "lines":
            found = [l.strip() for l in text.splitlines() if l.strip()]
        elif by == "tokens":
            found = re.findall(r"[A-Za-z0-9_][A-Za-z0-9_./:@%-]{%d,}" % (max(minlen, 2) - 1), text)
        elif by.startswith("regex:"):
            rx = re.compile(by[6:])
            found = [(m.group(1) if m.groups() else m.group(0)) for m in rx.finditer(text)]
        else:
            raise SystemExit(f"알 수 없는 --by: {by}")
    if ignore_case:
        found = [f.lower() for f in found]
    return set(found)


def tree_hashes(root):
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, root)
            h = hashlib.sha1()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = h.hexdigest()
    return out


def show(title, values, limit):
    values = sorted(values)
    print(f"\n== {title}: {len(values)}개 ==")
    for v in values[:limit]:
        print(f"  {v}")
    if len(values) > limit:
        print(f"  ... 외 {len(values) - limit}개 (--show 로 늘릴 수 있음)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", help="이전 버전(파일 또는 폴더)")
    ap.add_argument("new", help="이후 버전(파일 또는 폴더)")
    ap.add_argument("--by", default="lines", help="항목 추출 방식 (기본 lines)")
    ap.add_argument("--min", type=int, default=6, dest="minlen", help="strings/tokens 의 최소 길이 (기본 6)")
    ap.add_argument("--ignore-case", action="store_true", help="대소문자 무시")
    ap.add_argument("--show", type=int, default=40, help="각 목록에서 보일 최대 개수 (기본 40)")
    ap.add_argument("--only", choices=["added", "removed", "changed"], help="한 종류만 보기")
    args = ap.parse_args()

    old_dir, new_dir = os.path.isdir(args.old), os.path.isdir(args.new)
    if old_dir != new_dir:
        raise SystemExit("둘 다 파일이거나 둘 다 폴더여야 한다.")

    if old_dir:
        a, b = tree_hashes(args.old), tree_hashes(args.new)
        added = set(b) - set(a)
        removed = set(a) - set(b)
        changed = {p for p in set(a) & set(b) if a[p] != b[p]}
        print(f"이전 {len(a)}개 파일 | 이후 {len(b)}개 파일 | 공통 {len(set(a) & set(b))}개")
    else:
        a = items_from_file(args.old, args.by, args.minlen, args.ignore_case)
        b = items_from_file(args.new, args.by, args.minlen, args.ignore_case)
        added, removed, changed = b - a, a - b, set()
        print(f"이전 {len(a)}개 항목 | 이후 {len(b)}개 항목 | 공통 {len(a & b)}개")

    if args.only in (None, "added"):
        show("새로 생김(이후에만 있음)", added, args.show)
    if args.only in (None, "removed"):
        show("사라짐(이전에만 있음)", removed, args.show)
    if old_dir and args.only in (None, "changed"):
        show("내용이 바뀐 파일", changed, args.show)
    print("\n※ 새로 생긴 항목은 후보일 뿐이다. 거꾸로·다각도로 실체를 확인하고 감정을 거칠 것.", file=sys.stderr)


if __name__ == "__main__":
    main()
