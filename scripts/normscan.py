#!/usr/bin/env python3
"""정규화 스캔 (표현 축용).

폴더 안 텍스트 파일을 여러 층으로 정규화한 뒤 용어를 찾는다. 같은 용어가 전각 문자, 보이지 않는 공백,
줄바꿈 하이픈, 태그 분할, 이스케이프, 이중 인코딩, `[.]`/`(dot)`, 엔티티, base64 같은 모양으로 숨어 있어도 잡는다.
표준 라이브러리만 사용한다.

층(앞에서 뒤로 누적 적용):
  원문 -> 엔티티·전각·보이지 않는 문자 정리 -> 태그 제거 -> 줄바꿈 하이픈 결합
  -> 이스케이프 해독(\\uXXXX, \\xHH, \\/) -> URL 디코딩(최대 3회) -> 난독화 복원([.], (dot), hxxp) -> base64 해독

판정(용어마다 모든 층을 보고 가장 좋은 판정을 채택):
  일치                 도메인 경계가 맞다(접두·접미·다른 TLD·하위 도메인 위장이 아니다)
  비슷한 이름          글자는 있으나 경계가 틀리다 -> 가짜 후보(제외하고 이유를 적을 것)
  용어 일치(문맥 확인)  점이 없는 용어(브랜드, 한글 음역). 같은 서비스인지 문맥으로 판단
호모글리프(키릴 문자 등으로 위장)는 일부러 일치시키지 않는다.

--follow-maps: 폴더 안의 매핑 파일(csv/tsv/json: 짧은 ID,주소 쌍)에서 용어로 이어지는 체인을 거꾸로 따라가,
그 짧은 ID를 쓰는 문서를 '간접(체인)'으로 보고한다. 예: promo.txt(go.example/ap1) -> ap1=r.example/z5 -> z5=acmepay.com.

예:
  normscan.py docs/ --term acmepay.com --term 에이크미페이 --term AcmePay
  normscan.py docs/ --term acmepay.com --follow-maps --files-only
  normscan.py docs/ --term acmepay.com --json
"""
import argparse
import base64
import csv
import html
import json
import os
import re
import sys
import unicodedata
from urllib.parse import unquote

ZW = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"), None)
B64_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
MAX_BYTES = 5_000_000
RANK = {"일치": 3, "비슷한 이름(경계 불일치)": 2, "용어 일치(문맥 확인 필요)": 1}


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


def read_text(path):
    try:
        with open(path, "rb") as f:
            return f.read(MAX_BYTES).decode("utf-8", "replace")
    except OSError:
        return None


def scan_text(text, terms):
    layers = build_layers(text)
    hits = []
    for term in terms:
        low = term.lower()
        found = []
        for name, layer in layers:
            i = layer.lower().find(low)
            if i < 0:
                continue
            if "." in term:
                status = "일치" if boundary_regex(term).search(layer) else "비슷한 이름(경계 불일치)"
            else:
                status = "용어 일치(문맥 확인 필요)"
            found.append((name, status, i, layer))
        if not found:
            continue
        best = max((s for _, s, _, _ in found), key=lambda s: RANK[s])
        name, status, i, layer = next(x for x in found if x[1] == best)
        snippet = layer[max(0, i - 25): i + len(term) + 25].replace("\n", "⏎")
        hits.append({"term": term, "layer": name, "status": status, "snippet": snippet})
    return hits


def load_maps(files):
    """매핑 파일(csv/tsv/json)에서 (파일, 키, 값) 행을 모은다."""
    rows = []
    for p in files:
        low = p.lower()
        if not low.endswith((".csv", ".tsv", ".json")):
            continue
        text = read_text(p)
        if text is None:
            continue
        if low.endswith(".json"):
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if isinstance(data, dict):
                rows += [(p, str(k), str(v)) for k, v in data.items() if isinstance(v, (str, int))]
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and len(item) >= 2:
                        vals = [str(v) for v in item.values()]
                        rows.append((p, vals[0], vals[1]))
        else:
            delim = "\t" if low.endswith(".tsv") else ","
            for cells in csv.reader(text.splitlines(), delimiter=delim):
                if len(cells) >= 2 and cells[0].strip() and cells[1].strip():
                    rows.append((p, cells[0].strip(), cells[1].strip()))
    return rows


def follow_chains(rows, term, depth=3):
    """값에 용어가 든 행에서 시작해, 그 키를 값(주소 끝 조각)으로 쓰는 행을 거꾸로 따라간다."""
    low = term.lower()
    chains = []
    for f, k, v in rows:
        if low not in unquote(unquote(v)).lower():
            continue
        chain, cur = [(k, v)], k
        for _ in range(depth):
            nxt = [(k2, v2) for _, k2, v2 in rows if (v2.rstrip("/").endswith("/" + cur) or v2 == cur) and (k2, v2) not in chain]
            if not nxt:
                break
            chain.append(nxt[0])
            cur = nxt[0][0]
        chains.append(chain)
    return chains


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="스캔할 폴더(또는 파일)")
    ap.add_argument("--term", action="append", required=True, help="찾을 용어(반복 가능). 음역·브랜드명도 따로 넣을 것")
    ap.add_argument("--follow-maps", action="store_true", help="매핑 파일 체인을 따라 간접 언급 문서도 찾기")
    ap.add_argument("--files-only", action="store_true", help="상태별 고유 파일 경로만 출력")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = ap.parse_args()

    files = []
    if os.path.isfile(args.root):
        files = [args.root]
    else:
        for base, dirs, names in os.walk(args.root):
            dirs[:] = [d for d in dirs if d != ".git"]
            files += [os.path.join(base, n) for n in names]
    rel = (lambda p: os.path.relpath(p, args.root)) if os.path.isdir(args.root) else (lambda p: p)

    results = []  # {"file", "term", "layer", "status", "snippet"}
    texts = {}
    for p in sorted(files):
        text = read_text(p)
        if text is None:
            continue
        texts[p] = text
        for h in scan_text(text, args.term):
            results.append({"file": rel(p), **h})

    indirect = []
    if args.follow_maps:
        rows = load_maps(files)
        map_files = {p for p, _, _ in rows}
        seen = set()
        for term in args.term:
            if "." not in term:
                continue
            for chain in follow_chains(rows, term):
                keys = [k for k, _ in chain]
                desc = " <- ".join(f"{k}={v}" for k, v in chain)
                for key in keys:
                    if len(key) < 2:
                        continue
                    # 짧은 ID는 주소 경로 조각(`.../ph1`)으로 쓰인다. 일반 단어와 엮이지 않도록 '/' 뒤만 본다.
                    pat = re.compile(r"/" + re.escape(key) + r"(?![A-Za-z0-9])")
                    for p, text in texts.items():
                        if p in map_files or (rel(p), key) in seen:
                            continue
                        m = pat.search(text)
                        if m:
                            seen.add((rel(p), key))
                            snip = text[max(0, m.start() - 25): m.end() + 25].replace("\n", "⏎")
                            indirect.append({"file": rel(p), "term": term, "status": "간접(체인)", "key": key,
                                             "chain": desc, "snippet": snip})

    if args.json:
        json.dump({"results": results, "indirect": indirect}, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return

    groups = [("일치", "일치"), ("비슷한 이름(경계 불일치)", "비슷한 이름"), ("용어 일치(문맥 확인 필요)", "용어 일치")]
    if args.files_only:
        for status, label in groups:
            fs = sorted({r["file"] for r in results if r["status"] == status})
            print(f"== {label}: {len(fs)}개 ==")
            for f in fs:
                print(f)
        if args.follow_maps:
            fs = sorted({r["file"] for r in indirect})
            print(f"== 간접(체인): {len(fs)}개 ==")
            for f in fs:
                print(f)
    else:
        for r in results:
            print(f"{r['file']} | 용어 {r['term']} | {r['status']} | 층 {r['layer']}\n    …{r['snippet']}…")
        for r in indirect:
            print(f"{r['file']} | 간접(체인) | 짧은 ID {r['key']} | 체인 {r['chain']}\n    …{r['snippet']}…")

    cnt = {label: len({r["file"] for r in results if r["status"] == s}) for s, label in groups}
    print(f"\n스캔 {len(files)}개 파일 | 일치 {cnt['일치']}개 | 비슷한 이름 {cnt['비슷한 이름']}개 | "
          f"용어 일치 {cnt['용어 일치']}개 | 간접(체인) {len({r['file'] for r in indirect})}개", file=sys.stderr)
    if not args.follow_maps:
        print("※ 단축 링크·짧은 ID 체인은 --follow-maps 로 따라갈 수 있다.", file=sys.stderr)


if __name__ == "__main__":
    main()
