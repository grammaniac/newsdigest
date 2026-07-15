#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
결정론적 파서: '뉴스 요약' Google Doc 평문(plain text) → data/YYYY-MM-DD.json
LLM 없음. GitHub Action 이 매일 아침 Drive에서 Doc 평문을 받아 이 파서로 JSON 을 만들고,
render.py 가 그 JSON 으로 페이지를 만든다.

사용법:  python3 tools/parse_doc.py <doc_text_file> <YYYY-MM-DD>
출력:    data/<YYYY-MM-DD>.json
"""
import sys, json, re, os

TAGS = [
    ("New York Times", "Headlines · World"),
    ("Economist", "World in Brief"),
    ("Wall Street Journal", "Business · World"),
    ("New York Review of Books", "Essays"),
    ("Athletic", "Sports"),
    ("Washington Post", "Politics"),
]


def tag_for(name):
    for key, tag in TAGS:
        if key.lower() in name.lower():
            return tag
    return "News"


def is_divider(ln):
    s = re.sub(r"[—\-─━–]", "", ln).strip()
    return len(ln) >= 3 and s == ""


def parse_story(ln):
    t = ln.lstrip("•").strip()
    cands = []
    for sep in (" — ", " – ", ": "):
        i = t.find(sep)
        if i != -1:
            cands.append((i, sep))
    if cands:
        i, sep = min(cands)
        return {"lead": t[:i].strip(), "body": t[i + len(sep):].strip()}
    return {"lead": t, "body": ""}


def parse_vocab(ln):
    t = ln.lstrip("•").strip()
    m = re.search(r"\s[—–]\s", t)
    if not m:
        return None
    w = t[:m.start()].strip()
    rest = t[m.end():].strip()
    syns = []
    left = rest
    if "동의어:" in rest:
        left, right = rest.split("동의어:", 1)
        left = left.rstrip().rstrip("|").strip()
        syns = [s.strip() for s in re.split(r"[,，]", right) if s.strip()]
    pos = ""
    pm = re.search(r"\(([^)]*)\)\s*$", left)
    if pm:
        pos = pm.group(1).strip()
        defn = left[:pm.start()].strip()
    else:
        defn = left.strip()
    return {"w": w, "pos": pos, "def": defn, "syns": syns, "src": ""}


def parse(text, date):
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln and ln != "\\"]

    blocks, cur = [], []
    for ln in lines:
        if is_divider(ln):
            if cur:
                blocks.append(cur); cur = []
        else:
            cur.append(ln)
    if cur:
        blocks.append(cur)

    hero, big, outlets, vocab = "", "", [], []
    _SECTION_HEADERS = ("오늘의 핵심", "큰 그림", "[큰 그림", "오늘의 고급 어휘")
    for b in blocks:
        # 블록 맨 위에 문서 제목 줄(예: "뉴스 브리핑 — 2026년 7월 16일 (KST)")이
        # 붙는 경우가 있어, 알려진 섹션 헤더를 블록 안에서 찾아 그 지점부터 본문으로 삼는다.
        # (헤더가 없으면 hidx=0 → 매체 블록은 종전대로 제목=매체명.)
        hidx = 0
        for i, ln in enumerate(b):
            if any(ln.startswith(h) for h in _SECTION_HEADERS):
                hidx = i
                break
        title, body = b[hidx], b[hidx + 1:]
        if title.startswith("오늘의 핵심"):
            hero = " ".join(body).strip()
        elif title.startswith("큰 그림") or title.startswith("[큰 그림"):
            big = " ".join(body).strip()
        elif title.startswith("오늘의 고급 어휘"):
            for ln in body:
                if ln.startswith("•"):
                    v = parse_vocab(ln)
                    if v:
                        vocab.append(v)
        else:
            stories = [parse_story(ln) for ln in body if ln.startswith("•")]
            if stories:
                outlets.append({"name": title, "tag": tag_for(title), "stories": stories})

    if not big:
        big = hero
    return {"date": date, "heroSummary": hero, "bigPicture": big,
            "outlets": outlets, "vocab": vocab}


def main():
    if len(sys.argv) < 3:
        sys.exit("사용법: python3 tools/parse_doc.py <doc_text_file> <YYYY-MM-DD>")
    text = open(sys.argv[1], encoding="utf-8").read()
    date = sys.argv[2]
    data = parse(text, date)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(repo, "data", f"{date}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    n_st = sum(len(o["stories"]) for o in data["outlets"])
    print(f"파싱 완료: {os.path.basename(out)} — 매체 {len(data['outlets'])}·기사 {n_st}·어휘 {len(data['vocab'])}")
    if not data["heroSummary"] or not data["outlets"] or not data["vocab"]:
        print("⚠ 경고: 비어 있는 핵심 필드가 있습니다 — Doc 형식 확인 필요"); sys.exit(2)


if __name__ == "__main__":
    main()
