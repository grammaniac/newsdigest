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

# Google Drive 파일을 직접 읽으면 백그라운드(launchd)에서 'Resource deadlock avoided'(EDEADLK)가
# 날 수 있다 — 온라인 전용 파일을 즉석 materialize 하려다 충돌. 그래서 먼저 로컬로 복사한 뒤
# 그 복사본을 파싱한다. 복사가 곧 강제 다운로드 역할을 하며, 실패 시 재시도.
LOCAL_TXT="$REPO/.today.txt"
copied=0
for try in 1 2 3 4 5; do
  if cp "$TXT" "$LOCAL_TXT" 2>>"$LOG"; then copied=1; break; fi
  log "복사 재시도 $try (Drive materialize 대기)…"; sleep 20
done
if [ "$copied" != "1" ]; then log "❌ Drive .txt 로컬 복사 실패 — 중단"; exit 1; fi

# 원격과 동기화 (로컬이 뒤처져 push 거부되는 일 방지)
git pull --rebase --quiet 2>>"$LOG" || log "git pull 경고(무시하고 진행)"

python3 tools/parse_doc.py "$LOCAL_TXT" "$DATE" >>"$LOG" 2>&1 || { log "파싱 실패 — 중단"; exit 1; }
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
