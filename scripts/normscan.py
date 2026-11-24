#!/usr/bin/env python3
"""정규화 스캔 (표현 축용).

폴더 안 텍스트 파일을 여러 층으로 정규화한 뒤 용어를 찾는다. 같은 용어가 전각 문자, 보이지 않는 공백,
줄바꿈 하이픈, 태그 분할, 이스케이프, 이중 인코딩, `[.]`/`(dot)`, 엔티티, base64 같은 모양으로 숨어 있어도 잡는다.
표준 라이브러리만 사용한다.

층(앞에서 뒤로 누적 적용, 처음 일치한 층을 보고):
  원문 -> 엔티티·전각·보이지 않는 문자 정리 -> 태그 제거 -> 줄바꿈 하이픈 결합
  -> 이스케이프 해독(\\uXXXX, \\xHH, \\/) -> URL 디코딩(최대 3회) -> 난독화 복원([.], (dot), hxxp) -> base64 해독

도메인처럼 보이는 용어(점 포함)는 경계도 검사해서 '일치'와 '비슷한 이름'(접두·접미·다른 TLD·하위 도메인 위장)을 구분한다.
점이 없는 용어(브랜드, 한글 음역)는 '용어 일치(문맥 확인 필요)'로 표시한다.
호모글리프(키릴 문자 등으로 위장)는 일부러 일치시키지 않는다.

예:
  normscan.py docs/ --term partnerhub.io
  normscan.py docs/ --term partnerhub.io --term 파트너허브 --term PartnerHub
"""
import argparse
import base64
import html
import os
import re
import sys
import unicodedata
from urllib.parse import unquote

ZW = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"), None)
B64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
MAX_BYTES = 5_000_000


def build_layers(text):
    layers = [("원문", text)]
    t = unicodedata.normalize("NFKC", html.unescape(text).translate(ZW))
    layers.append(("엔티티·전각·보이지 않는 문자 정리", t))
    t = re.sub(r"<[^>]*>", "", t)
    layers.append(("태그 제거", t))
    t = re.sub(r"-[ \t]*\r?\n[ \t]*", "", t)
    layers.append(("줄바꿈 하이픈 결합", t))
    t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), t)
    t = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), t).replace("\\/", "/")
    layers.append(("이스케이프 해독", t))
    for _ in range(3):
        t = unquote(t)
    layers.append(("URL 디코딩", t))
    t = re.sub(r"\s*(?:\[\.\]|\(\.\)|\(dot\)|\[dot\])\s*", ".", t, flags=re.I)
    t = re.sub(r"hxxp", "http", t, flags=re.I)
    layers.append(("난독화 복원", t))
    decoded = []
    for tok in B64_TOKEN.findall(text):
        for off in range(4):  # base64 는 글자 정렬에 따라 시작 위치가 어긋난다
            s = tok[off:].replace("-", "+").replace("_", "/")
            s = s[: len(s) // 4 * 4] if "=" not in s else s
            try:
                raw = base64.b64decode(s + "=" * (-len(s) % 4), validate=False)
            except Exception:
                continue
            txt = raw.decode("utf-8", "ignore")
            if txt.strip():
                decoded.append(txt)
    layers.append(("base64 해독", "\n".join(decoded)))
    return layers


def boundary_regex(term):
    return re.compile(r"(?<![A-Za-z0-9-])" + re.escape(term) + r"(?![A-Za-z0-9-])(?!\.[A-Za-z0-9])", re.I)


def scan_file(path, terms):
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_BYTES)
    except OSError:
        return []
    text = data.decode("utf-8", "replace")
    hits = []
    layers = build_layers(text)
    for term in terms:
        low = term.lower()
        for name, layer in layers:
            i = layer.lower().find(low)
            if i < 0:
                continue
            domainlike = "." in term
            if domainlike:
                status = "일치" if boundary_regex(term).search(layer) else "비슷한 이름(경계 불일치)"
            else:
                status = "용어 일치(문맥 확인 필요)"
            snippet = layer[max(0, i - 25): i + len(term) + 25].replace("\n", "⏎")
            hits.append((term, name, status, snippet))
            break
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="스캔할 폴더(또는 파일)")
    ap.add_argument("--term", action="append", required=True, help="찾을 용어(반복 가능). 음역·브랜드명도 따로 넣을 것")
    ap.add_argument("--only", choices=["일치", "비슷한", "용어"], help="한 종류만 보기")
    args = ap.parse_args()

    files = []
    if os.path.isfile(args.root):
        files = [args.root]
    else:
        for base, dirs, names in os.walk(args.root):
            dirs[:] = [d for d in dirs if d != ".git"]
            files += [os.path.join(base, n) for n in names]
    rows = []
    for p in sorted(files):
        for hit in scan_file(p, args.term):
            rows.append((os.path.relpath(p, args.root) if os.path.isdir(args.root) else p,) + hit)
    shown = 0
    for rel, term, layer, status, snip in rows:
        if args.only and not status.startswith(args.only):
            continue
        shown += 1
        print(f"{rel} | 용어 {term} | 층 {layer} | {status}\n    …{snip}…")
    n_exact = len({r[0] for r in rows if r[3] == "일치"})
    n_like = len({r[0] for r in rows if r[3].startswith("비슷한")})
    n_term = len({r[0] for r in rows if r[3].startswith("용어")})
    print(f"\n스캔 {len(files)}개 파일 | 일치 {n_exact}개 | 비슷한 이름 {n_like}개 | 용어 일치 {n_term}개", file=sys.stderr)
    print("※ 모양 변형은 잡지만 단축 링크 체인은 못 따라간다. 짧은 ID로 매핑 파일을 다시 검색할 것.", file=sys.stderr)


if __name__ == "__main__":
    main()
