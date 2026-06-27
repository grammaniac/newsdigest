#!/usr/bin/env bash
# 사용법: ./publish.sh YYYY-MM-DD
#   먼저 repo 폴더에 news-digest-YYYY-MM-DD.html 을 둔 뒤 실행하세요.
#   하는 일: 인덱스(index.html)에 그날 카드 추가 → git commit → git push.
#   결과는 https://grammaniac.github.io/newsdigest/ 에 반영됩니다.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATE="${1:-}"
if [ -z "$DATE" ]; then echo "사용법: ./publish.sh YYYY-MM-DD"; exit 1; fi
FILE="news-digest-${DATE}.html"
if [ ! -f "$FILE" ]; then echo "파일이 없습니다: $FILE (먼저 이 폴더에 두세요)"; exit 1; fi

python3 - "$DATE" "$FILE" <<'PY'
import sys, re, html, datetime
date, fname = sys.argv[1], sys.argv[2]
src = open(fname, encoding='utf-8').read()

outlets = src.count('class="outlet reveal"') or src.count('class="outlet"')
stories = src.count('class="story"')
words   = src.count('class="card reveal"') or src.count('class="card"')

# 요약: hero-summary 첫 문장(태그 제거, 길이 제한)
m = re.search(r'class="hero-summary"[^>]*>(.*?)</p>', src, re.S)
summary = ''
if m:
    text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    summary = text.split('. ')[0].strip()
    if len(summary) > 90:
        summary = summary[:88].rstrip() + '…'

y, mo, d = map(int, date.split('-'))
kdays = ['월요일','화요일','수요일','목요일','금요일','토요일','일요일']
day = kdays[datetime.date(y, mo, d).weekday()]
mmdd = f"{mo:02d} · {d:02d}"

card = (
    f'    <a class="entry reveal" href="news-digest-{date}.html">\n'
    f'      <div class="entry-date">{mmdd}</div>\n'
    f'      <div class="entry-day">{y} · {day}</div>\n'
    f'      <div class="entry-summary">{html.escape(summary)}</div>\n'
    f'      <div class="entry-meta"><span>매체 {outlets}</span><span>기사 {stories}</span><span>어휘 {words}</span></div>\n'
    f'      <div class="entry-go">읽기 →</div>\n'
    f'    </a>'
)

idx = open('index.html', encoding='utf-8').read()
START = '<!-- ENTRIES:START -->'
href = f'href="news-digest-{date}.html"'
if href in idx:
    print(f"이미 인덱스에 있음: {date} (건너뜀)")
else:
    idx = idx.replace(START, START + "\n" + card, 1)  # 최신이 맨 위
    open('index.html', 'w', encoding='utf-8').write(idx)
    print(f"인덱스에 카드 추가: {date} ({day}) — 매체 {outlets}·기사 {stories}·어휘 {words}")
PY

git add -A
if git diff --cached --quiet; then
  echo "커밋할 변경이 없습니다."
  exit 0
fi
git commit -m "Add digest ${DATE}"
git push
echo "푸시 완료 → https://grammaniac.github.io/newsdigest/"
