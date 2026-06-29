#!/bin/bash
# 매일 아침 Mac에서 자동 실행(launchd): 동기화 폴더의 그날 .txt → 파싱 → 렌더 → GitHub push.
# 멱등(idempotent): 변경 없으면 아무것도 안 하고 끝. 여러 번 돌려도 안전.
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.14/bin"
export GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new -i /Users/john/.ssh/id_ed25519"
set -uo pipefail

REPO="/Users/john/newsdigest"
SYNC="/Users/john/Library/CloudStorage/GoogleDrive-grammaniac@gmail.com/내 드라이브/📰 매일 뉴스 요약 (Daily News Summaries)"
LOG="$REPO/.daily_publish.log"
DATE="$(TZ=Asia/Seoul date +%Y-%m-%d)"
TXT="$SYNC/뉴스요약-$DATE.txt"

log() { echo "[$(TZ=Asia/Seoul date '+%F %T')] $*" >> "$LOG"; }

cd "$REPO" || { log "repo cd 실패"; exit 1; }
log "=== run for $DATE ==="

if [ ! -f "$TXT" ]; then
  log "아직 .txt 없음 (동기화 대기 또는 루틴 미실행): $TXT"
  exit 0
fi

# 원격과 동기화 (로컬이 뒤처져 push 거부되는 일 방지)
git pull --rebase --quiet 2>>"$LOG" || log "git pull 경고(무시하고 진행)"

python3 tools/parse_doc.py "$TXT" "$DATE" >>"$LOG" 2>&1 || { log "파싱 실패 — 중단"; exit 1; }
python3 tools/render.py "data/$DATE.json" >>"$LOG" 2>&1 || { log "렌더 실패 — 중단"; exit 1; }

git add -A
if git diff --cached --quiet; then
  log "변경 없음 — 이미 최신"
  exit 0
fi
git commit -m "Digest $DATE (Mac auto-publish)" >>"$LOG" 2>&1
if git push >>"$LOG" 2>&1; then
  log "✅ push 완료 → https://grammaniac.github.io/newsdigest/news-digest-$DATE.html"
else
  log "❌ push 실패"
  exit 1
fi
