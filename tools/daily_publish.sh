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

# 원격과 먼저 동기화한다(로컬이 뒤처져 push가 거부되는 것 방지).
# 반드시 파일을 만들기 '전'에 — 뒤에서 하면 ingest/parse가 만든 변경 때문에
# "cannot pull with rebase: You have unstaged changes"로 실패한다.
git pull --rebase --quiet 2>>"$LOG" || log "git pull 경고(무시하고 진행)"

LOCAL_TXT="$REPO/.today.txt"
LOCAL_JSON="$REPO/.today.json"
JSON="$SYNC/뉴스데이터-$DATE.json"

# 파일 확보 전략 (2026-08-18 개정): Drive API를 '먼저' 쓴다.
#
# 이유 — 동기화 폴더의 파일은 온라인 전용 placeholder 일 수 있고, 그것을 launchd 백그라운드
# 프로세스가 읽으려 하면 materialize 를 트리거하지 못해 EDEADLK("Resource deadlock avoided")로
# 죽는다(2026-07-01에 진단, 오프라인 고정 설정으로 우회했으나 2026-08-18 재발). API 다운로드는
# 파일시스템 placeholder를 건드리지 않고 네트워크로 받으므로 이 계열 장애 전체가 무력화된다.
# 동기화 폴더 복사는 API가 실패했을 때의 폴백으로만 남긴다(네트워크 장애 등).
fetch() {   # fetch <출력경로> <Drive파일명> <동기화폴더경로>
  local out="$1" name="$2" synced="$3"
  rm -f "$out"
  if python3 tools/fetch_from_drive.py "$DATE" "$out" "$name" >>"$LOG" 2>&1; then
    return 0
  fi
  if [ -f "$synced" ] && cp "$synced" "$out" 2>>"$LOG"; then
    log "API 실패 → 동기화 폴더 복사로 확보: $name"
    return 0
  fi
  rm -f "$out"
  return 1
}

# 1순위: 루틴이 만든 JSON 계약 파일. 산문 형식이 계속 바뀌어(7/16~8/17) 파서를 매번
# 고쳐야 했기에, 기계가 읽는 JSON을 주 경로로 삼는다. 실패하면 아래 .txt 경로로 폴백한다.
INGESTED=0
fetch "$LOCAL_JSON" "뉴스데이터-$DATE.json" "$JSON" || true
if [ -s "$LOCAL_JSON" ]; then
  if python3 tools/ingest_json.py "$LOCAL_JSON" "$DATE" >>"$LOG" 2>&1; then
    INGESTED=1
    log "✅ JSON 계약으로 수신 완료 (산문 파서 우회)"
  else
    log "⚠ JSON 수신 실패 — 산문 .txt 파서로 폴백"
  fi
fi

if [ "$INGESTED" != "1" ]; then
  # 2순위: 산문 .txt 파서 경로 (JSON이 없거나 검증에 실패한 날).
  if ! fetch "$LOCAL_TXT" "뉴스요약-$DATE.txt" "$TXT"; then
    log "아직 .txt 없음 (루틴 미실행): $TXT"
    exit 0
  fi
  # Drive 앱 본체가 죽어 있으면 되살려 둔다(2026-07-24 장애). 파이프라인 자체는
  # 이미 API로 받았으므로 여기에 의존하지 않는다.
  if ! pgrep -f "Google Drive.app/Contents/MacOS/Google Drive" >/dev/null 2>&1; then
    open -a "Google Drive" 2>>"$LOG" && log "⚠ Google Drive 앱이 죽어 있어 재기동함 (동기화 복구)"
  fi
fi

if [ "$INGESTED" != "1" ]; then
  python3 tools/parse_doc.py "$LOCAL_TXT" "$DATE" >>"$LOG" 2>&1 || { log "파싱 실패 — 중단"; exit 1; }
fi
python3 tools/render.py "data/$DATE.json" >>"$LOG" 2>&1 || { log "렌더 실패 — 중단"; exit 1; }

git add -A
if git diff --cached --quiet; then
  log "변경 없음 — 이미 최신"
  # 이전 실행에서 push는 됐는데 GitHub Pages 배포 단계만 일시 실패했을 수 있다
  # (예: 2026-07-05, "deploy Failed in 8 seconds"). 라이브 URL이 404면 빈 커밋으로 재배포 트리거.
  LIVE_URL="https://grammaniac.github.io/newsdigest/news-digest-$DATE.html"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$LIVE_URL" || echo 000)"
  if [ "$code" = "404" ]; then
    log "⚠ 라이브 페이지 404 — Pages 배포 실패로 판단, 빈 커밋으로 재배포 트리거"
    git commit --allow-empty -m "Retrigger Pages deploy ($DATE)" >>"$LOG" 2>&1
    if git push >>"$LOG" 2>&1; then
      log "🔁 재배포 트리거 push 완료 → $LIVE_URL"
    else
      log "❌ 재배포 트리거 push 실패"
      exit 1
    fi
  else
    log "라이브 확인: HTTP $code — 정상"
  fi
  exit 0
fi
git commit -m "Digest $DATE (Mac auto-publish)" >>"$LOG" 2>&1
if ! git push >>"$LOG" 2>&1; then
  # 그 사이 GitHub Action이 커밋을 올려 로컬이 뒤처졌을 수 있다 → rebase 후 한 번 더.
  log "push 거부됨 — pull --rebase 후 재시도"
  git pull --rebase --quiet >>"$LOG" 2>&1 || true
  if ! git push >>"$LOG" 2>&1; then
    log "❌ push 실패"
    exit 1
  fi
fi
log "✅ push 완료 → https://grammaniac.github.io/newsdigest/news-digest-$DATE.html"
