#!/usr/bin/env python3
"""표기 변형 생성기 (표현 축용).

식별자, 문구, 도메인/URL 하나를 받아 검색에 쓸 만한 표기 변형을 한 줄씩 출력한다.
동의어, 번역, 약어는 도구가 알 수 없으므로 에이전트가 따로 보탠다.

예:
  variants.py getUserName
  variants.py "my site"
  variants.py https://www.example.co.kr/blog/post
  variants.py example.com --json
  variants.py partnerhub.io --regex     # 모양 변형을 모두 허용하는 정규식 한 줄
"""
import argparse
import base64
import json
import re
import sys
from urllib.parse import quote, urlsplit

# 2단계 공개 접미사 (간이 목록). 완전하지 않다.
TWO_LEVEL = {
    "co.kr", "or.kr", "go.kr", "ac.kr", "ne.kr", "re.kr",
    "co.jp", "or.jp", "ne.jp", "co.uk", "org.uk", "ac.uk",
    "com.au", "net.au", "org.au", "com.cn", "com.tw", "com.br", "co.in", "co.nz",
}


def split_words(text):
    """camelCase, snake_case, kebab-case, 점, 공백으로 단어를 나눈다."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    parts = re.split(r"[\s_\-./]+", text)
    return [p for p in parts if p]


def word_variants(text):
    words = split_words(text)
    if not words:
        return {}
    low = [w.lower() for w in words]
    out = {
        "snake_case": "_".join(low),
        "kebab-case": "-".join(low),
        "camelCase": low[0] + "".join(w.capitalize() for w in low[1:]),
        "PascalCase": "".join(w.capitalize() for w in low),
        "SCREAMING_SNAKE": "_".join(low).upper(),
        "dot.case": ".".join(low),
        "공백 구분": " ".join(low),
        "붙여쓰기": "".join(low),
        "Title Case": " ".join(w.capitalize() for w in low),
    }
    if len(words) > 1:
        out["약어(첫 글자)"] = "".join(w[0] for w in low)
    return out


def registrable(host):
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_LEVEL:
        return ".".join(labels[-3:]), labels[-3]
    if len(labels) >= 2:
        return ".".join(labels[-2:]), labels[-2]
    return host, host


def looks_like_url(text):
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        return True
    return bool(re.match(r"^[\w-]+(\.[\w-]+)+(/.*)?$", text)) and " " not in text


def url_variants(text):
    raw = text if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I) else "https://" + text
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    base = host[4:] if host.startswith("www.") else host
    reg, brand = registrable(base)

    out = {}
    out["도메인(www 없음)"] = base
    out["도메인(www)"] = "www." + base
    out["모바일(m.)"] = "m." + base
    out["https"] = "https://" + base + path
    out["http"] = "http://" + base + path
    out["https+www"] = "https://www." + base + path
    if path and path != "/":
        out["슬래시 토글"] = (
            "https://" + base + path.rstrip("/")
            if path.endswith("/")
            else "https://" + base + path + "/"
        )
        out["경로 인코딩"] = "https://" + base + quote(path, safe="/")
    if reg != base:
        out["등록 도메인"] = reg
    out["브랜드명(도메인 제외)"] = brand
    if brand:
        out["브랜드 공백/하이픈 변형"] = " / ".join(
            sorted({brand.replace("-", " "), brand.replace("-", ""), brand.replace("-", "_")})
        )
    try:
        puny = base.encode("idna").decode("ascii")
        if puny != base:
            out["punycode"] = puny
    except UnicodeError:
        pass
    out["검색 연산자(링크)"] = f"link:{base}  /  inurl:{brand}  /  \"{base}\""
    # 인코딩·난독화 표기: 기록, 로그, 설정 파일 속에 이런 형태로 숨어 있을 수 있다.
    out["URL 인코딩(전체)"] = quote("https://" + base, safe="")
    out["URL 인코딩(www)"] = quote("https://www." + base, safe="")
    out["난독화 [.]"] = base.replace(".", "[.]")
    out["난독화 (dot)"] = base.replace(".", " (dot) ")
    out["HTML 엔티티"] = base.replace(".", "&#46;")
    for label, raw in (("https://", "https://" + base), ("http://", "http://" + base), ("도메인만", base)):
        out[f"base64({label})"] = base64.b64encode(raw.encode()).decode()
    # 목록 밖에서 자주 나오는 모양들(사람이 눈으로는 같아 보이는 것)
    cut = max(1, len(brand) // 2)
    out["이중 URL 인코딩"] = quote(quote("https://" + base, safe=""), safe="")
    out["점만 인코딩(%2E)"] = base.replace(".", "%2E")
    out["전각 문자"] = to_fullwidth(base)
    out["보이지 않는 공백 삽입"] = base[:cut] + "<U+200B>" + base[cut:] + "   (실제로는 보이지 않는 문자)"
    out["태그 분할(<wbr>)"] = base[:cut] + "<wbr>" + base[cut:]
    out["줄 끝 하이픈 분할"] = base[:cut] + "-⏎" + base[cut:] + "   (⏎ = 줄바꿈)"
    out["이스케이프(\\x, \\u)"] = f"\\x{ord(base[0]):02x}{base[1:]}  /  \\u{ord(base[0]):04x}{base[1:]}"
    out["(가짜 구분용) 호모글리프"] = base.replace("a", "а", 1) + "   (키릴 문자 — 같은 대상이 아님)"
    return out


def to_fullwidth(s):
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s).replace("．", "．")


def tolerant_regex(term):
    """글자 사이에 보이지 않는 문자·태그·줄바꿈 하이픈이 끼거나 문자가 인코딩돼도 맞는 정규식 한 줄(Python re, grep -P)."""
    sep = r"(?:[\s​-‏­﻿]|<[^>]{0,12}>|-[ \t]*\r?\n|&shy;){0,6}"
    parts = []
    for ch in term:
        if ch == ".":
            parts.append(r"(?:\.|\[\.\]|\(dot\)|&#46;|%2[eE]|\\x2[eE]|\\u002[eE]|．)")
        elif ch.isalnum():
            parts.append(
                f"(?:{re.escape(ch)}|&#{ord(ch)};|%{ord(ch):02x}|\\\\x{ord(ch):02x}|\\\\u{ord(ch):04x}|{chr(ord(ch) + 0xFEE0)})"
            )
        else:
            parts.append(re.escape(ch))
    return "(?i)" + sep.join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("term", help="식별자, 문구, 도메인 또는 URL")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--regex", action="store_true",
                    help="변형 목록 대신 모양 변형을 모두 허용하는 정규식 한 줄만 출력(grep -P / Python re)")
    args = ap.parse_args()

    term = args.term.strip()
    if not term:
        ap.error("빈 입력")
    if args.regex:
        host = urlsplit(term if "://" in term else "https://" + term).hostname if looks_like_url(term) else None
        print(tolerant_regex(host or term))
        return

    groups = {}
    if looks_like_url(term):
        groups["url"] = url_variants(term)
    else:
        groups["words"] = word_variants(term)
        if not groups["words"]:
            ap.error("변형을 만들 수 있는 단어가 없음")

    if args.json:
        json.dump(groups, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return

    for name, variants in groups.items():
        print(f"[{name}] 입력: {term}")
        seen = set()
        for label, value in variants.items():
            if value in seen:  # 같은 값이면 앞의 것만 보인다
                continue
            seen.add(value)
            print(f"  {label:<22} {value}")
    print("\n※ 동의어, 번역, 약어, 옛 이름, 현지어 음역(예: PartnerHub -> 파트너허브)은 직접 추가할 것.", file=sys.stderr)


if __name__ == "__main__":
    main()
