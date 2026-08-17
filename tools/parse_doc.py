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
    s = re.sub(r"[—\-─━–=]", "", ln).strip()
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


_SECTION_HEADERS = ("오늘의 핵심", "큰 그림", "[큰 그림", "오늘의 고급 어휘")

# 제목 판별용 매체명 힌트. TAGS(태그 부여용)와 분리해 둔다 — 여기에 별칭을 넣어도
# 기존 태그 결과가 바뀌지 않도록 하기 위함.
_OUTLET_HINTS = (
    "New York Times", "NYT", "Wall Street Journal", "WSJ", "Economist",
    "New York Review of Books", "NY Review of Books", "NYRB",
    "Athletic", "Washington Post", "Word Smarts", "Word Daily",
    "Word Genius", "All Healthy",
)


def _is_content(s):
    """제목이 될 수 없는 줄 — 불릿·번호 어휘 항목·동의어/어원 부속 줄."""
    return (s.startswith("•") or s.startswith("-")
            or bool(re.match(r"^\d+[.)]\s", s))
            or s.startswith("동의어") or s.startswith("어원"))


def _strip_the(s):
    return re.sub(r"^[Tt]he\s+", "", s).strip()


def _starts_with_outlet(s):
    """줄이 알려진 매체명으로 '시작'하는가. 매체 제목은 뒤에 부제가 길게 붙는 날이 있어
    (예: 'The Economist (August 3rd 2026 — The World in Brief 등)') 길이로는 가를 수 없다."""
    t = _strip_the(s).lower()
    return any(t.startswith(_strip_the(k).lower()) for k in _OUTLET_HINTS)


def _classify_heading(s, nxt, in_vocab):
    """제목 줄이면 (종류, 제목) 을, 아니면 None 을 반환. 구분선·불릿 유무에 의존하지 않는다.
    2026-08-17 형식부터 제목에 번호가 붙는다('1. 오늘의 핵심 뉴스', '2. 세계') — 번호를 뗀
    나머지로도 판정한다. 단 번호 달린 줄은 어휘 항목('N. 단어 (품사) — 뜻')일 수 있으므로,
    vocab 섹션 안이거나 '—' 를 포함하면 제목 후보에서 제외한다."""
    stripped = None
    m = re.match(r"^\d+[.)]\s+(.+)$", s)
    if m:
        stripped = m.group(1).strip()

    for t in ([s] if stripped is None else [s, stripped]):
        if t.startswith("오늘의 핵심"):
            return ("hero", t)
        if t.startswith("큰 그림") or t.startswith("[큰 그림"):
            return ("big", t)
        if t.startswith("오늘의 고급 어휘"):
            return ("vocab", t)
        if t.startswith("오늘의 단어"):
            return ("wod", t)

    for t, numbered in ([(s, False)] if stripped is None else [(s, False), (stripped, True)]):
        if numbered and (in_vocab or " — " in t or " – " in t):
            continue
        if _is_content(t):
            continue
        # 알려진 매체명으로 시작하고 문장으로 끝나지 않는 줄 = 매체 제목
        if _starts_with_outlet(t) and not t.endswith((".", "다", "!", "?")):
            return ("outlet", t)
        # 모르는 매체/주제라도, 짧고 문장으로 끝나지 않으며 바로 다음 줄이 불릿이면 제목으로 본다
        if len(t) <= 40 and not t.endswith((".", "다", "!", "?")) and nxt.startswith("•"):
            return ("outlet", t)
    return None


def parse_wod_lines(lines):
    """'오늘의 단어' 문단형 섹션(2026-08-17 형식) → vocab 항목.
    문단 구조: 표제어 줄 / '품사: …' / '뜻[N]: …' / (예문…) / '출처: …'(문단 끝)."""
    out, cur = [], None
    for ln in lines:
        if cur is None:
            if re.match(r"^(품사|뜻|예문|어원|출처)", ln):
                continue
            w = ln.split("(")[0].strip()
            if w and len(w) <= 40:
                cur = {"w": w, "pos": "", "def": "", "syns": [], "src": ""}
            continue
        if ln.startswith("품사"):
            pm = re.search(r"품사\s*[:：]\s*([^|]+)", ln)
            if pm:
                cur["pos"] = pm.group(1).strip()
        elif ln.startswith("뜻"):
            d = re.sub(r"^뜻\s*\d*\s*[:：]\s*", "", ln).strip()
            cur["def"] = (cur["def"] + "; " + d) if cur["def"] else d
        elif ln.startswith("출처"):
            cur["src"] = re.sub(r"^출처\s*[:：]\s*", "", ln).strip()
            if cur["w"] and cur["def"]:
                out.append(cur)
            cur = None
    return out


def _pick(body):
    """본문 줄 고르기: 불릿이 하나라도 있으면 불릿만(종전 동작 그대로),
    하나도 없으면 모든 줄을 본문으로 본다(2026-08-13처럼 불릿 없이 산문으로 오는 형식)."""
    bullets = [l for l in body if l.startswith("•")]
    return bullets if bullets else body


def parse(text, date):
    """구분선에 의존하지 않는 제목/본문 상태기계.
    각 줄을 '제목'과 '본문'으로 분류해 섹션을 만들고, 섹션 종류에 따라 해석한다.
    구분선·빈 줄은 구조로 쓰지 않고 버린다 — 형식이 바뀌어도(구분선 유무, 불릿 유무,
    어휘 한 줄/두 줄 형식) 같은 결과가 나오도록 하기 위함."""
    raw = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in raw if ln and ln != "\\" and not is_divider(ln)]

    sections = []   # [kind, name, [본문 줄]]
    cur = None
    for i, s in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        hit = _classify_heading(s, nxt, in_vocab=(cur is not None and cur[0] == "vocab"))
        if hit is not None:
            cur = [hit[0], hit[1], []]
            sections.append(cur)
        elif cur is not None:
            cur[2].append(s)
        # cur 가 None 인 줄 = 첫 제목 이전의 문서 제목 줄 → 버린다

    def joined(body):
        return " ".join(l.lstrip("•").strip() for l in body).strip()

    hero, big, outlets, vocab = "", "", [], []
    for kind, name, body in sections:
        if kind == "hero":
            if not hero:
                hero = joined(body)
        elif kind == "big":
            if not big:
                big = joined(body)
        elif kind == "vocab":
            vocab.extend(parse_vocab_lines(_pick(body)))
        elif kind == "wod":
            vocab.extend(parse_wod_lines(body))
        else:
            stories = [parse_story(l) for l in _pick(body)]
            if stories:
                outlets.append({"name": name, "tag": tag_for(name), "stories": stories})

    # 같은 단어가 두 섹션에 겹쳐 오는 날이 있다('오늘의 단어' 문단 + '고급 어휘' 불릿, 2026-08-17).
    # 뒤에 온, 동의어가 있는 쪽을 남긴다.
    seen = {}
    for v in vocab:
        k = v["w"].strip().lower()
        if k not in seen or (not seen[k]["syns"] and v["syns"]):
            seen[k] = v
    vocab = list(seen.values())

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
    n_st = sum(len(o["stories"]) for o in data["outlets"])
    print(f"파싱 결과: {os.path.basename(out)} — 매체 {len(data['outlets'])}·기사 {n_st}·어휘 {len(data['vocab'])}")

    # 검증 실패 시에는 JSON을 쓰지 않는다. 예전엔 깨진 JSON을 그대로 써 두는 바람에
    # 다음날 성공한 실행의 `git add -A`에 딸려 커밋돼 빈 페이지가 발행됐다(2026-08-13 사고).
    if not data["heroSummary"] or not data["outlets"] or not data["vocab"]:
        print("⚠ 경고: 비어 있는 핵심 필드가 있습니다 — Doc 형식 확인 필요 (JSON 미기록)")
        sys.exit(2)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"파싱 완료: {os.path.basename(out)}")


if __name__ == "__main__":
    main()
