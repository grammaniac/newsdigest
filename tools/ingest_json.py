#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""클라우드 루틴이 직접 만든 JSON(뉴스데이터-YYYY-MM-DD.json) → data/YYYY-MM-DD.json

배경: 루틴이 내놓는 산문 .txt 형식이 계속 바뀌어(7/16·8/11·8/13·8/16·8/17) 파서를
매번 고쳐야 했다. 그래서 루틴이 기계가 읽는 JSON을 함께 내도록 계약을 바꾸고,
이 스크립트가 그 JSON을 받아 검증·정규화한다. 산문 파서(parse_doc.py)는 폴백으로 남는다.

계약(루틴이 만드는 JSON):
  {"date": "YYYY-MM-DD",
   "heroSummary": "...", "bigPicture": "...",
   "outlets": [{"name": "The New York Times",
                "stories": [{"lead": "제목", "body": "본문"}]}],
   "vocab": [{"w": "ostensible", "pos": "형용사", "def": "표면상의",
              "syns": ["apparent", "supposed"], "src": ""}]}

tag 는 루틴에 맡기지 않고 여기서 tag_for() 로 채운다(모델이 지어내지 않도록).
형태가 조금 달라도(문자열 story, 쉼표로 붙인 syns 등) 흡수한다.

사용:  python3 tools/ingest_json.py <json파일> <YYYY-MM-DD>
출력:  data/<YYYY-MM-DD>.json   (검증 통과 시에만 기록)
종료코드: 0=성공, 2=검증 실패(폴백해야 함)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_doc import tag_for, parse_story  # noqa: E402


# 품사를 한국어로 통일한다. 루틴이 날에 따라 "noun"/"adjective"로 보내와(2026-08-17 시험 실행)
# 산문 시절의 "명사"/"형용사"와 섞이는 것을 막는다.
_POS = {
    "noun": "명사", "n": "명사", "n.": "명사",
    "verb": "동사", "v": "동사", "v.": "동사",
    "adjective": "형용사", "adj": "형용사", "adj.": "형용사",
    "adverb": "부사", "adv": "부사", "adv.": "부사",
    "preposition": "전치사", "conjunction": "접속사", "pronoun": "대명사",
    "interjection": "감탄사", "phrase": "구",
}


def _pos(v):
    t = _text(v)
    return _POS.get(t.lower().strip(), t)


def _text(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return " ".join(_text(x) for x in v).strip()
    return "" if v is None else str(v).strip()


def _story(s):
    """story 는 {"lead","body"} 가 정석이지만 문자열로 오는 날도 흡수한다."""
    if isinstance(s, dict):
        lead = _text(s.get("lead") or s.get("title") or s.get("headline"))
        body = _text(s.get("body") or s.get("text") or s.get("summary"))
        if lead and not body:
            return parse_story(lead)
        if not lead and body:
            return parse_story(body)
        return {"lead": lead, "body": body}
    t = _text(s)
    return parse_story(t) if t else None


def _syns(v):
    if isinstance(v, list):
        return [_text(x) for x in v if _text(x)]
    t = _text(v)
    if not t:
        return []
    return [p.strip() for p in t.replace("，", ",").split(",") if p.strip()]


def normalize(raw, date):
    hero = _text(raw.get("heroSummary") or raw.get("hero"))
    big = _text(raw.get("bigPicture") or raw.get("big")) or hero

    outlets = []
    for o in raw.get("outlets") or []:
        if not isinstance(o, dict):
            continue
        name = _text(o.get("name") or o.get("outlet"))
        if not name:
            continue
        stories = [x for x in (_story(s) for s in (o.get("stories") or [])) if x and x["lead"]]
        if stories:
            outlets.append({"name": name, "tag": tag_for(name), "stories": stories})

    vocab = []
    seen = set()
    for v in raw.get("vocab") or []:
        if not isinstance(v, dict):
            continue
        w = _text(v.get("w") or v.get("word"))
        d = _text(v.get("def") or v.get("definition") or v.get("meaning"))
        if not w or not d:
            continue
        k = w.lower()
        if k in seen:
            continue
        seen.add(k)
        vocab.append({"w": w, "pos": _pos(v.get("pos")), "def": d,
                      "syns": _syns(v.get("syns") or v.get("synonyms")),
                      "src": _text(v.get("src") or v.get("source"))})

    return {"date": date, "heroSummary": hero, "bigPicture": big,
            "outlets": outlets, "vocab": vocab}


def main():
    if len(sys.argv) < 3:
        sys.exit("사용법: python3 tools/ingest_json.py <json파일> <YYYY-MM-DD>")
    src, date = sys.argv[1], sys.argv[2]
    try:
        raw = json.load(open(src, encoding="utf-8"))
    except Exception as e:
        print("JSON 읽기 실패: %s" % e)
        sys.exit(2)
    if not isinstance(raw, dict):
        print("JSON 최상위가 객체가 아님")
        sys.exit(2)

    data = normalize(raw, date)
    n_st = sum(len(o["stories"]) for o in data["outlets"])
    print("JSON 수신: 매체 %d·기사 %d·어휘 %d" % (len(data["outlets"]), n_st, len(data["vocab"])))

    # 파서와 같은 기준으로 검증. 실패 시 파일을 쓰지 않는다(빈 JSON이 커밋되는 사고 방지).
    if not data["heroSummary"] or not data["outlets"] or not data["vocab"]:
        print("⚠ JSON 검증 실패 — 비어 있는 핵심 필드 (기록하지 않음)")
        sys.exit(2)

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(repo, "data", "%s.json" % date)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("수신 완료: %s" % os.path.basename(out))


if __name__ == "__main__":
    main()
