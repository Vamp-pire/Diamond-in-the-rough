#!/usr/bin/env python3
"""집계기 (분포 축용).

로그, 유입(referrer) 목록, 줄 단위 텍스트에서 항목을 뽑아 빈도를 세고
드물거나 예상 밖인 항목을 표시한다. 표준 라이브러리만 사용한다.

추출 방식(--extract):
  host        줄 안의 URL/호스트명에서 호스트만 (기본)
  host+path1  호스트 + 첫 번째 경로 조각 (예: blog.naver.com/someid)
  url         호스트 + 전체 경로(쿼리 제외) (예: dev.to/sam/small-tools-3f2a)
  urlq        호스트 + 전체 경로 + 쿼리 (예: news.ycombinator.com/item?id=123, 글 ID가 쿼리에 있을 때)
  domain      등록 도메인으로 합치기 (m.blog.naver.com -> naver.com)
  col:N       N번째 열 (1부터, --sep 으로 구분자 지정)
  regex:PAT   정규식의 첫 번째 그룹

줄 전처리:
  --field N   따옴표로 묶인 N번째 필드만 본다. nginx/apache combined 로그는
              1=요청, 2=referrer, 3=User-Agent. referrer 가 "-" 이면 '직접 방문'으로 따로 센다.
  --unwrap    리다이렉터·공유 링크가 감싼 주소(google.com/url?q=URL, l.facebook.com/l.php?u=URL)를
              안쪽 주소로 풀어서 센다. 풀지 않으면 안쪽 출처가 겉 도메인으로 뭉개진다.

키 정리(집계 전):
  --collapse-digits        호스트의 숫자열을 #으로 바꿔 'word-word-123.xyz' 같은 스팸을 한 묶음으로 센다(경로는 그대로)
  --normalize 'PAT=>REPL'  정규식 치환(여러 번 지정 가능)
  --ignore a,b             제외할 항목. 호스트 기준 접미 일치(google.com 은 www.google.com 도, google.com/search 도 제외).
                           하위 도메인까지 모두 제외되므로 naver.com 대신 search.naver.com 처럼 구체적으로 쓸 것
                           (naver.com 을 넣으면 blog.naver.com 의 글도 사라진다)
  --ignore-regex PAT       정규식과 일치하는 항목 제외(여러 번 지정 가능)
  --expect a,b             예상 항목(같은 규칙으로 비교). 목록에 없는 항목에 NEW 를 붙인다
  --ignore-known           흔한 검색엔진·소셜 공유·SEO 봇 호스트를 미리 제외(KNOWN_NOISE 목록 참고)
  --examples               집계 키는 정규화(소문자, 스킴·www 제거)돼 있으므로, 보고용 원본 URL을 항목마다 한 줄 보여 준다

출력:
  기본은 상위 20개 + 꼬리 중 눈여겨볼 항목 30개. 꼬리를 끝까지 보려면 --all,
  건수가 적은 것부터 보려면 --sort asc.

예:
  tally.py access.log --field 2 --unwrap --extract urlq --collapse-digits --ignore-known --all --sort asc --examples
  tally.py referrers.txt --ignore google.com,bing.com --ignore-regex 'news-portal-#'
  tally.py ref.csv --extract col:3 --sep , --expect google.com,bing.com
"""
import argparse
import re
import sys
from collections import Counter
from urllib.parse import unquote

TWO_LEVEL = {
    "co.kr", "or.kr", "go.kr", "ac.kr", "ne.kr", "re.kr",
    "co.jp", "or.jp", "ne.jp", "co.uk", "org.uk", "ac.uk",
    "com.au", "net.au", "org.au", "com.cn", "com.tw", "com.br", "co.in", "co.nz",
}

# 스킴(http/https)이 붙은 URL을 우선한다. localhost, IP도 스킴이 있으면 허용.
SCHEME_RE = re.compile(r"https?://([A-Za-z0-9][A-Za-z0-9.-]*)(?::\d+)?(/[^\s\"'<>)]*)?")
# 스킴이 없을 때의 대비책: 점이 있고 끝이 글자인 호스트명.
BARE_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?::\d+)?(/[^\s\"'<>)]*)?")

# 리다이렉터가 안쪽 주소를 담는 흔한 쿼리 파라미터 이름
REDIR_KEYS = ("u", "url", "q", "target", "redirect", "redirect_uri", "dest", "destination", "to", "link", "href", "r", "l")
URL_TOKEN = re.compile(r"https?://[^\s\"'<>]+")
REDIR_PARAM = re.compile(r"[?&](?:%s)=([^&#\s]+)" % "|".join(REDIR_KEYS))
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
DIRECT = "(직접 방문)"
# --ignore-known 이 걷어내는 흔한 노이즈. 하위 도메인까지 제외되므로 글 URL이 있는 블로그·커뮤니티는 넣지 않았다.
KNOWN_NOISE = [
    "google.com", "google.co.kr", "bing.com", "search.naver.com", "search.daum.net", "duckduckgo.com",
    "search.yahoo.com", "ecosia.org", "l.facebook.com", "lm.facebook.com", "t.co", "l.instagram.com",
    "semrush.com", "ahrefs.com", "majestic.com", "translate.goog", "mail.google.com", "localhost", "127.0.0.1",
]


def unwrap_url(u):
    """감싼 주소를 최대 3겹까지 풀어 가장 안쪽 http(s) 주소를 돌려준다. 풀 게 없으면 그대로."""
    for _ in range(3):
        m = REDIR_PARAM.search(u)
        if not m:
            return u
        inner = unquote(m.group(1))
        if not re.match(r"https?://", inner):
            inner = unquote(inner)  # 이중 인코딩
            if not re.match(r"https?://", inner):
                return u
        u = inner
    return u


def unwrap_line(line):
    return URL_TOKEN.sub(lambda m: unwrap_url(m.group(0)), line)


def reg_domain(host):
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def extract_host(line, mode="host"):
    m = SCHEME_RE.search(line) or BARE_RE.search(line)
    if not m:
        return None
    host = m.group(1).lower()
    if host.startswith("www."):
        host = host[4:]
    path_q = (m.group(2) or "").split("#")[0]
    path = path_q.split("?")[0]
    if mode == "urlq":
        return host + path_q.rstrip("/")
    if mode == "url":
        return host + path.rstrip("/")
    if mode == "path1":
        seg = [s for s in path.split("/") if s]
        return host + ("/" + seg[0] if seg else "")
    return host


def make_extractor(spec, sep):
    if spec == "host":
        return lambda l: extract_host(l)
    if spec == "host+path1":
        return lambda l: extract_host(l, "path1")
    if spec == "url":
        return lambda l: extract_host(l, "url")
    if spec == "urlq":
        return lambda l: extract_host(l, "urlq")
    if spec == "domain":
        return lambda l: (lambda h: reg_domain(h) if h else None)(extract_host(l))
    if spec.startswith("col:"):
        n = int(spec[4:])
        if n < 1:
            raise SystemExit("col:N 은 1 이상")

        def col(l):
            cols = l.rstrip("\n").split(sep) if sep else l.split()
            return cols[n - 1].strip() if len(cols) >= n and cols[n - 1].strip() else None
        return col
    if spec.startswith("regex:"):
        rx = re.compile(spec[6:])

        def rgx(l):
            m = rx.search(l)
            return (m.group(1) if m and m.groups() else None)
        return rgx
    raise SystemExit(f"알 수 없는 --extract: {spec}")


def entry_matches(key, entry):
    """항목 e 가 key 와 맞는지: 호스트 기준 접미 일치, 경로가 있으면 접두 일치."""
    key, e = key.lower(), entry.lower()
    if "/" in e:
        return key == e or key.startswith(e.rstrip("/") + "/")
    host = key.split("/")[0]
    return host == e or host.endswith("." + e)


def parse_list(value):
    return [v.strip().lower() for v in (value or "").split(",") if v.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="입력 파일 ('-' 이면 표준입력)")
    ap.add_argument("--extract", default="host", help="추출 방식 (기본 host)")
    ap.add_argument("--sep", default=None, help="col:N 의 구분자 (기본: 공백)")
    ap.add_argument("--field", type=int, default=0, help="따옴표로 묶인 N번째 필드만 사용 (combined 로그: 2=referrer)")
    ap.add_argument("--unwrap", action="store_true", help="리다이렉터가 감싼 주소를 안쪽 주소로 풀어서 집계")
    ap.add_argument("--collapse-digits", action="store_true", help="키의 숫자열을 #으로 바꿔 군집화")
    ap.add_argument("--normalize", action="append", default=[], help="키 정규식 치환 'PAT=>REPL' (반복 가능)")
    ap.add_argument("--top", type=int, default=20, help="상위 몇 개를 보일지 (기본 20)")
    ap.add_argument("--all", action="store_true", help="모든 항목을 끝까지 나열")
    ap.add_argument("--sort", choices=["count", "asc"], default="count", help="꼬리 목록 정렬: count(많은 순) / asc(적은 순)")
    ap.add_argument("--rare", type=int, default=2, help="이 횟수 이하를 '드묾'으로 표시 (기본 2)")
    ap.add_argument("--rare-limit", type=int, default=30, help="꼬리에서 눈여겨볼 항목을 최대 몇 개 보일지")
    ap.add_argument("--expect", default="", help="예상 항목(쉼표). 목록에 없는 항목에 NEW 표시")
    ap.add_argument("--expect-file", default=None, help="예상 항목 목록 파일(줄 단위)")
    ap.add_argument("--ignore", default="", help="제외할 항목(쉼표, 호스트 접미 일치)")
    ap.add_argument("--ignore-regex", action="append", default=[],
                    help="제외할 정규식(반복 가능). --collapse-digits/--normalize 가 끝난 뒤의 키에 적용된다")
    ap.add_argument("--ignore-known", action="store_true",
                    help="흔한 검색엔진·소셜 공유·SEO 봇 호스트를 미리 제외(KNOWN_NOISE 목록)")
    ap.add_argument("--examples", action="store_true", help="항목마다 원본 URL 예시 한 줄을 함께 출력")
    args = ap.parse_args()

    extractor = make_extractor(args.extract, args.sep)
    expect = parse_list(args.expect)
    if args.expect_file:
        with open(args.expect_file, encoding="utf-8") as f:
            expect += [l.strip().lower() for l in f if l.strip()]
    ignore = parse_list(args.ignore) + (KNOWN_NOISE if args.ignore_known else [])
    ignore_rx = [re.compile(p) for p in args.ignore_regex]
    norm = []
    for spec in args.normalize:
        if "=>" not in spec:
            raise SystemExit("--normalize 는 'PAT=>REPL' 형식")
        pat, repl = spec.split("=>", 1)
        norm.append((re.compile(pat), repl))

    src = sys.stdin if args.file == "-" else open(args.file, encoding="utf-8", errors="replace")
    total = skipped = ignored = n_unwrapped = direct = 0
    counter = Counter()
    examples = {}
    with src:
        for line in src:
            if not line.strip():
                continue
            total += 1
            if args.field:
                fields = QUOTED.findall(line)
                if len(fields) < args.field:
                    skipped += 1
                    continue
                line = fields[args.field - 1]
                if line.strip() in ("-", ""):
                    direct += 1
                    continue
            if args.unwrap:
                unwrapped_line = unwrap_line(line)
                if unwrapped_line != line:
                    n_unwrapped += 1
                line = unwrapped_line
            item = extractor(line)
            if not item:
                skipped += 1
                continue
            url_example = URL_TOKEN.search(line)
            key = item if args.extract.startswith("regex:") else item.lower()
            if args.collapse_digits:  # 호스트 부분만 군집화한다(경로 속 글 ID는 그대로 둔다)
                host_part, slash, rest = key.partition("/")
                key = re.sub(r"\d+", "#", host_part) + slash + rest
            for rx, repl in norm:
                key = rx.sub(repl, key)
            if any(entry_matches(key, e) for e in ignore) or any(rx.search(key) for rx in ignore_rx):
                ignored += 1
                continue
            counter[key] += 1
            examples.setdefault(key, url_example.group(0) if url_example else line.strip()[:120])

    counted = sum(counter.values())
    notes = []
    if args.field:
        notes.append(f"직접 방문 {direct}")
    if args.unwrap:
        notes.append(f"풀어낸 감싼 주소 {n_unwrapped}줄")
    if not args.field:
        notes.append("추출 실패에는 referrer 가 '-'(직접 방문)인 줄이 포함될 수 있음. --field 2 로 구분")
    print(f"입력 {total}줄 | 추출 {counted} | 추출 실패 {skipped} | 제외 {ignored} | 고유 항목 {len(counter)}"
          + ("".join(f" | {n}" for n in notes[:2]) if args.field else ""))
    if not args.field:
        print("  (" + notes[-1] + ")")
    if not counter:
        print("집계할 항목이 없음. --extract 방식을 바꿔 볼 것.")
        return

    def is_new(k):
        return bool(expect) and not any(entry_matches(k, e) for e in expect)

    def flag(k, c):
        tags = []
        if is_new(k):
            tags.append("NEW")
        if c <= args.rare:
            tags.append("드묾")
        return ",".join(tags)

    top_n = len(counter) if args.all else args.top
    rare_limit = len(counter) if args.all else args.rare_limit
    # --sort asc 이면 목록 자체를 적은 것부터 정렬한다(--all 과 함께 써도 효과가 나도록).
    ranked = sorted(counter.items(), key=lambda x: (x[1], x[0])) if args.sort == "asc" else counter.most_common()
    title = "적은 것부터" if args.sort == "asc" else "상위"
    print(f"\n== {title} {min(top_n, len(ranked))} ==")
    for k, c in ranked[:top_n]:
        print(f"{c:>7} {c / counted:>6.1%}  {k}  {flag(k, c)}".rstrip())
        if args.examples:
            print(f"          예: {examples.get(k, '')}")

    top_keys = {k for k, _ in ranked[:top_n]}
    tail = [(k, c) for k, c in counter.items() if k not in top_keys]
    print(f"\n== 상위 밖 꼬리: {len(tail)}개 항목, {sum(c for _, c in tail)}건 ==")
    flagged = [(k, c) for k, c in tail if is_new(k) or c <= args.rare]
    flagged.sort(key=(lambda x: (x[1], x[0])) if args.sort == "asc" else (lambda x: (-x[1], x[0])))
    if flagged:
        print(f"-- 꼬리 중 눈여겨볼 항목 (NEW 또는 드묾, {args.sort}, 최대 {rare_limit}개) --")
        for k, c in flagged[:rare_limit]:
            print(f"{c:>7}  {k}  {flag(k, c)}".rstrip())
            if args.examples:
                print(f"          예: {examples.get(k, '')}")
        if len(flagged) > rare_limit:
            print(f"   ... 외 {len(flagged) - rare_limit}개 (--all 로 전부 보기)")

    if expect:
        new_in_top = [k for k, _ in ranked[:top_n] if is_new(k)]
        if new_in_top:
            print(f"\n※ 예상 목록에 없는 상위 항목: {', '.join(new_in_top)}")

    sys.stdout.flush()
    print("\n※ 봇, 내부 트래픽, 스팸 패턴은 --ignore / --ignore-regex / --collapse-digits 로 걷어낸 뒤 다시 볼 것.", file=sys.stderr)


if __name__ == "__main__":
    main()
