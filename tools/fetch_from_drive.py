#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""동기화 폴더에 그날 .txt가 없을 때의 폴백: Drive API에서 직접 내려받는다.

배경(2026-07-24 장애): Google Drive 데스크톱 앱 본체가 크래시해 동기화가 멈추면,
클라우드 루틴이 파일을 만들어도 Mac에 안 내려와 파이프라인이 선 채로 기다린다.
이 폴백은 ~/hermes-sdk/google_api.py(토큰 자동 갱신)를 재사용해 동기화를 우회한다.
시스템 파이썬(3.9, launchd의 PATH 기준)에서 돌아야 한다.

사용: python3 tools/fetch_from_drive.py YYYY-MM-DD <출력경로>
종료코드: 0=다운로드 성공, 1=Drive에도 없음(루틴 미실행) 또는 실패
"""
import json
import sys
import urllib.parse

sys.path.insert(0, "/Users/john/hermes-sdk")
import google_api  # noqa: E402

FOLDER_ID = "1aVtstx5EjCEsKlTEALNk2OcYUahhS9RJ"  # "📰 매일 뉴스 요약" Drive 폴더


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 1
    date, out_path = sys.argv[1], sys.argv[2]
    name = "뉴스요약-%s.txt" % date
    q = urllib.parse.quote(
        "name = '%s' and '%s' in parents and trashed=false" % (name, FOLDER_ID)
    )
    r = json.loads(google_api.call("GET", "drive/v3/files?q=%s&fields=files(id)" % q))
    files = r.get("files") or []
    if not files:
        print("Drive에 %s 없음 — 루틴 미실행으로 판단" % name, file=sys.stderr)
        return 1
    content = google_api.call("GET", "drive/v3/files/%s?alt=media" % files[0]["id"])
    if not content.strip() or content.lstrip().startswith('{"error"'):
        print("다운로드 실패: %s" % content[:200], file=sys.stderr)
        return 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("API 다운로드 성공: %s → %s (%d chars)" % (name, out_path, len(content)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
