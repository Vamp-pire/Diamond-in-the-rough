#!/usr/bin/env python3
"""git 이력에서 함수·클래스의 삭제 → 이동 → 이름 변경 체인을 따라간다 (시간 축용).

심볼의 정의가 사라진 커밋을 찾고, 같은 커밋에서 추가된 코드 중 내용이 가장 비슷한 것(이동·이름 변경 후보)을
이어서 따라가 HEAD의 현재 위치까지 보여 준다. 이름이 비슷한 가짜(다른 기능)는 내용 유사도로 구분한다.
표준 라이브러리와 git 만 사용한다.

예:
  gittrace.py REPO --find csv                       # 이름에 csv 가 든 '삭제된 정의' 목록(후보 찾기)
  gittrace.py REPO --symbol export_csv_legacy       # 삭제 -> 이동 -> 이름 변경 체인
"""
import argparse
import difflib
import re
import subprocess
import sys

DEF = re.compile(r"\b(?:def|function|func|fn|class|sub)\s+([A-Za-z_]\w*)")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, errors="replace").stdout


def commit_hunks(repo, h):
    """커밋의 (파일, 삭제 블록, 추가 블록) 목록."""
    out = git(repo, "show", "-M", "--unified=0", "--format=", h)  # 이름 변경(-M)만 감지. 복사 감지(-C)는 삭제를 어긋나 보이게 한다
    hunks, old, cur, rem, add = [], None, None, [], []

    def flush():
        nonlocal rem, add
        if cur and (rem or add):
            hunks.append((cur, "\n".join(rem), "\n".join(add)))
        rem, add = [], []

    for line in out.splitlines():
        if line.startswith("--- "):
            flush()
            p = line[4:]
            old = p[2:] if p.startswith("a/") else p
        elif line.startswith("+++ "):
            p = line[4:]
            new = p[2:] if p.startswith("b/") else p
            cur = new if new != "/dev/null" else old
        elif line.startswith("@@"):
            flush()
        elif line.startswith("-"):
            rem.append(line[1:])
        elif line.startswith("+"):
            add.append(line[1:])
    flush()
    return hunks


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def history(repo, sym, since=None):
    rng = [f"{since}..HEAD"] if since else []
    out = git(repo, "log", "--all", "--reverse", "-G", rf"\b{sym}\b", "--format=%H|%h|%ad|%s", "--date=short", *rng)
    return [l.split("|", 3) for l in out.splitlines() if l.count("|") >= 3]


def head_location(repo, sym):
    out = git(repo, "grep", "-n", "-E", rf"(def|function|func|fn|class|sub)\s+{sym}\b", "HEAD")
    return [l.replace("HEAD:", "", 1) for l in out.splitlines()]


def find_removed_defs(repo, word, limit=300):
    out = git(repo, "log", "--all", "--reverse", "-G", word, "--format=%H|%h|%ad|%s", "--date=short")
    rows = []
    for l in out.splitlines()[:limit]:
        h, short, date, subj = l.split("|", 3)
        for f, rem, add in commit_hunks(repo, h):
            for name in DEF.findall(rem):
                if word.lower() in name.lower() and not re.search(rf"\b(?:def|function|func|fn|class|sub)\s+{name}\b", add):
                    rows.append((short, date, f, name, subj))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="git 저장소 경로")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="따라갈 함수·클래스 이름")
    g.add_argument("--find", help="이름에 이 글자가 든 삭제된 정의 목록")
    ap.add_argument("--min-sim", type=float, default=0.55, help="이동·이름 변경 후보로 볼 최소 유사도 (기본 0.55)")
    ap.add_argument("--max-steps", type=int, default=6)
    args = ap.parse_args()

    if args.find:
        rows = find_removed_defs(args.repo, args.find)
        print(f"이름에 '{args.find}' 가 든 삭제된 정의: {len(rows)}개 (오래된 순)")
        for short, date, f, name, subj in rows:
            print(f"  {short} {date} {f}::{name}  \"{subj}\"")
        print("\n※ 이름이 비슷해도 내용이 다른 기능일 수 있다. --symbol 로 체인을 따라가 유사도와 현재 위치를 비교할 것.", file=sys.stderr)
        return

    sym = args.symbol
    now = head_location(args.repo, sym)
    print(f"[시작] {sym}  HEAD에서: {', '.join(now) if now else '정의 없음(삭제·이름 변경 가능성)'}")
    since = None
    for step in range(1, args.max_steps + 1):
        found = None
        for h, short, date, subj in history(args.repo, sym, since):
            hunks = commit_hunks(args.repo, h)
            for f, rem, add in hunks:
                if re.search(rf"\b(?:def|function|func|fn|class|sub)\s+{sym}\b", rem) and \
                        not re.search(rf"\b(?:def|function|func|fn|class|sub)\s+{sym}\b", add):
                    found = (h, short, date, subj, f, rem, hunks)
                    break
            if found:
                break
        if not found:
            print(f"[끝] '{sym}' 정의가 사라진 커밋이 더 없다.")
            break
        h, short, date, subj, f, rem, hunks = found
        best, best_r = None, 0.0
        for f2, rem2, add2 in hunks:
            if not add2.strip():
                continue
            r = difflib.SequenceMatcher(None, norm(rem), norm(add2)).ratio()
            if r > best_r:
                best, best_r = (f2, add2), r
        print(f"[{step}] {short} {date} \"{subj}\"\n     삭제: {f}::{sym}")
        if best and best_r >= args.min_sim:
            names = [n for n in DEF.findall(best[1]) if n != sym] or DEF.findall(best[1])
            new = names[0] if names else sym
            print(f"     이동·이름 변경 후보: {best[0]}::{new}  (내용 유사도 {best_r:.2f})")
            sym, since = new, h
            continue
        print(f"     같은 커밋에서 비슷한 추가 코드를 못 찾음(최고 유사도 {best_r:.2f}) -> 단순 삭제로 보임")
        break
    now = head_location(args.repo, sym)
    print(f"\n[현재 위치] {sym}: {', '.join(now) if now else 'HEAD에 정의 없음'}")


if __name__ == "__main__":
    main()
