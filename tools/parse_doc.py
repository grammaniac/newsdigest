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
    ("Word Smarts", "표현·언어"),
    ("All Healthy", "건강"),
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
    # 출처(선택): "| 출처: ..." 를 먼저 떼어낸다 (없으면 기존과 동일 — 하위호환)
    src = ""
    sm = re.search(r"\|?\s*출처\s*:", rest)
    if sm:
        src = rest[sm.end():].strip()
        rest = rest[:sm.start()].rstrip().rstrip("|").strip()
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
    return {"w": w, "pos": pos, "def": defn, "syns": syns, "src": src}


def parse_vocab_numbered(t, nxt):
    """번호 형식 항목(2026-08-11 드리프트): t='단어 (품사) — 뜻[ | 출처: X]',
    nxt='동의어: a, b[ | 출처: X]' 또는 ''. 품사가 단어 바로 뒤에 오고 동의어가 다음 줄이다."""
    src = ""
    sm = re.search(r"\|?\s*출처\s*:", t)
    if sm:
        src = t[sm.end():].strip()
        t = t[:sm.start()].rstrip().rstrip("|").strip()
    m = re.match(r"(.+?)\s*\(([^()]*)\)\s*[—–-]\s*(.+)$", t)
    if m:
        w, pos, defn = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    else:
        dm = re.search(r"\s[—–]\s", t)
        if not dm:
            return None
        w, pos, defn = t[:dm.start()].strip(), "", t[dm.end():].strip()
    syns = []
    if nxt:
        parts = re.split(r"[:：]", nxt, maxsplit=1)
        right = parts[1] if len(parts) > 1 else ""
        sm2 = re.search(r"\|?\s*출처\s*:", right)
        if sm2:
            if not src:
                src = right[sm2.end():].strip()
            right = right[:sm2.start()]
        syns = [s.strip() for s in re.split(r"[,，]", right) if s.strip()]
    return {"w": w, "pos": pos, "def": defn, "syns": syns, "src": src}


def parse_vocab_lines(lines):
    """어휘 블록 본문 → vocab 리스트. 한 줄 불릿 형식(• 단어 — 뜻 (품사) | 동의어: ...)과
    번호 두 줄 형식('N. 단어 (품사) — 뜻' + '동의어: ...')을 모두 흡수한다."""
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        step = 1
        v = None
        if ln.startswith("•"):
            v = parse_vocab(ln)
        else:
            nm = re.match(r"\d+[.)]\s*(.+)$", ln)
            if nm:
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if nxt.startswith("동의어"):
                    step = 2
                else:
                    nxt = ""
                v = parse_vocab_numbered(nm.group(1), nxt)
        if v:
            out.append(v)
        i += step
    return out


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
    # 섹션/매체 제목이 구분선으로 위아래 밑줄 쳐져 제목만의 블록이 되고 본문이 다음 블록으로
    # 분리되는 형식(2026-08-11 드리프트)이 있다. 제목만의 블록은 pending에 기억해 두고
    # 다음 블록을 그 섹션의 본문으로 삼는다. 종전 형식(제목+본문 한 블록)은 그대로 동작.
    pending = None  # ("hero"|"big"|"vocab", None) 또는 ("outlet", 매체명)
    _SECTION_HEADERS = ("오늘의 핵심", "큰 그림", "[큰 그림", "오늘의 고급 어휘")

    def joined(lines):
        return " ".join(ln.lstrip("•").strip() for ln in lines).strip()

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
            if body:
                hero = joined(body)
                pending = None
            else:
                pending = ("hero", None)
        elif title.startswith("큰 그림") or title.startswith("[큰 그림"):
            if body:
                big = joined(body)
                pending = None
            else:
                pending = ("big", None)
        elif title.startswith("오늘의 고급 어휘"):
            if body:
                vocab.extend(parse_vocab_lines(body))
                pending = None
            else:
                pending = ("vocab", None)
        elif pending is not None and pending[0] in ("hero", "big", "vocab"):
            kind = pending[0]
            pending = None
            allv = [title] + body
            if kind == "hero":
                hero = joined(allv)
            elif kind == "big":
                big = joined(allv)
            else:
                vocab.extend(parse_vocab_lines(allv))
        elif title.startswith("•"):
            # 블록 전체가 기사 불릿 — 직전 블록이 매체명 단독 블록이었던 형식
            if pending is not None and pending[0] == "outlet":
                name = pending[1]
                stories = [parse_story(ln) for ln in [title] + body if ln.startswith("•")]
                if stories:
                    outlets.append({"name": name, "tag": tag_for(name), "stories": stories})
            pending = None
        else:
            stories = [parse_story(ln) for ln in body if ln.startswith("•")]
            if stories:
                outlets.append({"name": title, "tag": tag_for(title), "stories": stories})
                pending = None
            elif not body:
                # 제목 한 줄짜리 블록 — 매체명이 구분선 사이에 홀로 온 것으로 보고 다음 블록을 기다린다
                pending = ("outlet", title)

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
