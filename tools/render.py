#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
결정론적 렌더러: data/YYYY-MM-DD.json  →  news-digest-YYYY-MM-DD.html
LLM 개입 없음. 내용은 전부 HTML 본문에 박힌다(progressive enhancement) — 절대 빈 페이지가 되지 않는다.
템플릿은 이 파일 안에 박아둔다(외부 파일 의존 금지: 과거에 template.html 삭제로 파이프라인이 깨진 적 있음).

사용법:  python3 tools/render.py data/2026-06-28.json
JSON 스키마:
{
  "date": "2026-06-28",
  "heroSummary": "...",            # 히어로 좌측 인용 박스
  "bigPicture": "...",             # '오늘의 핵심' 본문
  "outlets": [
    {"name": "The New York Times", "tag": "Headlines · World",
     "stories": [{"lead": "미국, 이란 군사 보복 타격", "body": "이란이 ..."}]}
  ],
  "vocab": [
    {"w": "retaliation", "pos": "명사", "def": "보복, 앙갚음",
     "syns": ["reprisal","retribution","requital","vengeance"], "src": "..."}
  ]
}
"""
import sys, json, html, datetime, os

TEMPLATE = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Morning Brief · @@DATE@@ — 뉴스 & GRE 어휘</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700;900&family=Noto+Sans+KR:wght@300;400;500;700&family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;1,9..144,400&family=Newsreader:ital@0;1&display=swap" rel="stylesheet" />
<style>
  :root {
    --bg: #f4f1ea; --bg-soft: #faf8f3; --ink: #1a1714; --ink-soft: #4a443c;
    --line: #ddd6c8; --paper: #fffdf8; --accent: #9a2b2b; --accent-2: #b8863b;
    --shadow: 30,25,20; --hero-grad-1: #2a2622; --hero-grad-2: #4a3b2a; --card-back: #1f1c18;
  }
  html[data-theme="dark"] {
    --bg: #121010; --bg-soft: #1a1715; --ink: #ece6db; --ink-soft: #a89f90;
    --line: #322d27; --paper: #1c1916; --accent: #e0716f; --accent-2: #d9ac5e;
    --shadow: 0,0,0; --hero-grad-1: #0d0b0a; --hero-grad-2: #2a201a; --card-back: #0d0b0a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body {
    background: var(--bg); color: var(--ink);
    font-family: "Noto Sans KR", system-ui, sans-serif; line-height: 1.7;
    -webkit-font-smoothing: antialiased; overflow-x: hidden;
    transition: background .5s ease, color .5s ease;
  }
  .js .reveal { opacity: 0; transform: translateY(22px); transition: opacity .7s cubic-bezier(.2,.7,.2,1), transform .7s cubic-bezier(.2,.7,.2,1); }
  .js .reveal.in { opacity: 1; transform: none; }
  @media (prefers-reduced-motion: reduce) { .js .reveal { opacity: 1 !important; transform: none !important; } }
  #progress { position: fixed; top: 0; left: 0; height: 3px; width: 0%; z-index: 100;
    background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .1s linear; }
  .topbar { position: fixed; top: 0; left: 0; right: 0; z-index: 90;
    display: flex; align-items: center; justify-content: space-between;
    padding: 13px clamp(16px, 5vw, 60px); backdrop-filter: blur(12px);
    background: color-mix(in srgb, var(--bg) 70%, transparent);
    border-bottom: 1px solid transparent; transition: border-color .4s, background .4s; }
  .topbar.scrolled { border-bottom-color: var(--line); }
  .brand { font-family: "Fraunces", serif; font-weight: 600; font-size: 1.05rem; letter-spacing: .5px; }
  .brand b { color: var(--accent); }
  .theme-toggle { background: none; border: 1px solid var(--line); color: var(--ink);
    width: 38px; height: 38px; border-radius: 50%; cursor: pointer; font-size: 1rem;
    display: grid; place-items: center; transition: transform .4s, border-color .25s; }
  .theme-toggle:hover { transform: rotate(20deg); border-color: var(--accent); }
  .hero { min-height: 90vh; display: flex; flex-direction: column; justify-content: center;
    padding: 110px clamp(20px, 6vw, 80px) 70px; position: relative; overflow: hidden;
    background:
      radial-gradient(ellipse 80% 60% at 70% 10%, color-mix(in srgb, var(--accent-2) 22%, transparent), transparent 60%),
      linear-gradient(160deg, var(--hero-grad-1), var(--hero-grad-2));
    color: #f4ede0; }
  .hero::after { content: ""; position: absolute; inset: 0; pointer-events: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='60'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.04'/%3E%3C/svg%3E"); }
  .hero-kicker { font-family: "Fraunces", serif; letter-spacing: 4px; text-transform: uppercase; font-size: .8rem; color: var(--accent-2); margin-bottom: 22px; }
  .hero-date { display: inline-flex; align-items: center; gap: 10px; font-size: .9rem; color: #cbbfa9; margin-bottom: 18px; }
  .hero-date .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent-2); box-shadow: 0 0 12px var(--accent-2); animation: pulse 2s infinite; }
  .hero h1 { font-family: "Noto Serif KR", serif; font-weight: 900; font-size: clamp(2.4rem, 6.5vw, 5rem); line-height: 1.08; letter-spacing: -1px; max-width: 18ch; }
  .hero h1 .accent { color: var(--accent-2); font-style: italic; font-family: "Fraunces", serif; }
  .hero-summary { margin-top: 30px; max-width: 62ch; font-size: clamp(1rem, 1.6vw, 1.15rem); line-height: 1.9; color: #ded3c0; font-weight: 300; border-left: 2px solid var(--accent-2); padding-left: 22px; }
  .hero-stats { margin-top: 44px; display: flex; flex-wrap: wrap; gap: clamp(24px, 5vw, 56px); }
  .stat .num { font-family: "Fraunces", serif; font-size: 2.4rem; font-weight: 600; color: #fff; line-height: 1; }
  .stat .lbl { font-size: .78rem; letter-spacing: 1px; text-transform: uppercase; color: #b3a888; margin-top: 6px; }
  .scroll-cue { position: absolute; bottom: 26px; left: 50%; transform: translateX(-50%); color: #b3a888; font-size: .72rem; letter-spacing: 2px; text-transform: uppercase; display: flex; flex-direction: column; align-items: center; gap: 8px; }
  .scroll-cue .line { width: 1px; height: 34px; background: linear-gradient(var(--accent-2), transparent); animation: cue 1.8s infinite; }
  main { max-width: 1180px; margin: 0 auto; padding: 0 clamp(16px, 5vw, 40px); }
  .section { padding: 70px 0 10px; }
  .section-head { display: flex; align-items: baseline; gap: 16px; margin-bottom: 36px; flex-wrap: wrap; }
  .section-head h2 { font-family: "Noto Serif KR", serif; font-weight: 900; font-size: clamp(1.6rem, 3.5vw, 2.4rem); letter-spacing: -.5px; }
  .section-head .en { font-family: "Fraunces", serif; font-style: italic; color: var(--accent); font-size: clamp(1rem, 2vw, 1.3rem); }
  .section-head .rule { flex: 1; height: 1px; background: var(--line); min-width: 40px; }
  .big-picture { font-size: clamp(1.05rem, 2vw, 1.3rem); line-height: 1.95; max-width: 68ch; color: var(--ink-soft); font-family: "Noto Serif KR", serif; }
  .outlets { display: grid; gap: 26px; }
  .outlet { background: var(--paper); border: 1px solid var(--line); border-radius: 16px; padding: clamp(22px, 4vw, 36px); position: relative; overflow: hidden; box-shadow: 0 1px 2px rgba(var(--shadow),.04); transition: box-shadow .35s, transform .25s, border-color .35s, background .5s; }
  .outlet:hover { box-shadow: 0 18px 50px -22px rgba(var(--shadow),.32); transform: translateY(-3px); border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); }
  .outlet::before { content: ""; position: absolute; top: 0; left: 0; width: 4px; height: 100%; background: linear-gradient(var(--accent), var(--accent-2)); opacity: .85; }
  .outlet-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
  .outlet-name { font-family: "Fraunces", serif; font-weight: 600; font-size: 1.32rem; letter-spacing: .2px; }
  .outlet-tag { font-size: .68rem; letter-spacing: 1.5px; text-transform: uppercase; font-weight: 700; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); padding: 5px 12px; border-radius: 20px; white-space: nowrap; }
  .stories { list-style: none; display: grid; gap: 15px; }
  .story { display: grid; grid-template-columns: auto 1fr; gap: 14px; align-items: start; }
  .story .mark { font-family: "Fraunces", serif; font-weight: 600; color: var(--accent-2); font-size: .95rem; line-height: 1.9; }
  .story p { font-size: .98rem; color: var(--ink-soft); line-height: 1.75; }
  .story p b { color: var(--ink); font-weight: 700; }
  .vocab-intro { color: var(--ink-soft); margin-bottom: 26px; max-width: 60ch; font-weight: 300; }
  .vocab-intro b { color: var(--accent); font-weight: 500; }
  .vocab-tools { display: flex; gap: 12px; margin-bottom: 28px; flex-wrap: wrap; }
  .vbtn { font-family: "Noto Sans KR"; font-size: .82rem; font-weight: 500; cursor: pointer; background: var(--paper); border: 1px solid var(--line); color: var(--ink); padding: 9px 18px; border-radius: 30px; transition: all .25s; }
  .vbtn:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-2px); }
  .vocab-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 20px; perspective: 1600px; }
  .card { position: relative; height: 250px; cursor: pointer; }
  .card-inner { position: absolute; inset: 0; transition: transform .7s cubic-bezier(.4,.2,.2,1); transform-style: preserve-3d; }
  .card:hover .card-inner, .card:focus .card-inner, .card.flipped .card-inner { transform: rotateY(180deg); }
  .face { position: absolute; inset: 0; backface-visibility: hidden; -webkit-backface-visibility: hidden; border-radius: 16px; padding: 24px; display: flex; flex-direction: column; border: 1px solid var(--line); overflow: hidden; }
  .face-front { background: var(--paper); }
  .face-front::after { content: ""; position: absolute; right: -30px; bottom: -30px; width: 120px; height: 120px; background: radial-gradient(circle, color-mix(in srgb, var(--accent-2) 18%, transparent), transparent 70%); border-radius: 50%; }
  .pos { align-self: flex-start; font-size: .66rem; letter-spacing: 1px; text-transform: uppercase; font-weight: 700; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); padding: 4px 11px; border-radius: 20px; margin-bottom: auto; }
  .word { font-family: "Fraunces", serif; font-weight: 600; font-size: 1.8rem; letter-spacing: -.5px; word-break: break-word; }
  .word-sub { color: var(--ink-soft); font-size: .82rem; margin-top: 8px; font-weight: 300; }
  .flip-hint { position: absolute; top: 18px; right: 18px; font-size: .7rem; color: var(--ink-soft); opacity: .55; }
  .face-back { background: var(--card-back); color: #ece6db; transform: rotateY(180deg); border-color: transparent; justify-content: center; }
  .face-back .def { font-family: "Noto Serif KR", serif; font-weight: 600; font-size: 1.2rem; line-height: 1.5; margin-bottom: 16px; color: #fff; }
  .face-back .syn-label { font-size: .66rem; letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent-2); margin-bottom: 8px; }
  .face-back .syns { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 14px; }
  .face-back .syns span { font-family: "Newsreader", serif; font-style: italic; font-size: .9rem; background: rgba(255,255,255,.08); padding: 3px 10px; border-radius: 12px; color: #e6d9c4; }
  .face-back .src { font-size: .73rem; color: #9a9082; line-height: 1.5; border-top: 1px solid rgba(255,255,255,.1); padding-top: 12px; font-style: italic; }
  footer { margin-top: 80px; padding: 56px clamp(16px,5vw,40px); border-top: 1px solid var(--line); text-align: center; color: var(--ink-soft); }
  footer .f-brand { font-family: "Fraunces", serif; font-size: 1.3rem; color: var(--ink); margin-bottom: 10px; }
  footer .f-brand b { color: var(--accent); }
  footer .f-meta { font-size: .82rem; line-height: 1.8; }
  @keyframes pulse { 0%,100%{ transform: scale(1); opacity: 1; } 50%{ transform: scale(1.5); opacity: .5; } }
  @keyframes cue { 0%{ transform: scaleY(0); transform-origin: top; } 50%{ transform: scaleY(1); transform-origin: top; } 51%{ transform-origin: bottom; } 100%{ transform: scaleY(0); transform-origin: bottom; } }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; } }
  @media (max-width: 520px) { .card { height: auto; min-height: 250px; } }
</style>
</head>
<body>
<div id="progress"></div>

<header class="topbar" id="topbar">
  <div class="brand"><b>Morning</b> Brief</div>
  <button class="theme-toggle" id="themeToggle" aria-label="테마 전환" title="다크/라이트 전환">◐</button>
</header>

<section class="hero">
  <div class="hero-kicker">Daily News &amp; Vocabulary Digest</div>
  <div class="hero-date"><span class="dot"></span><span>@@HERO_DATE@@ · 한국 시각 기준</span></div>
  <h1>오늘 아침의 <span class="accent">세계</span>, 그리고 오늘의 <span class="accent">언어</span>.</h1>
  <p class="hero-summary">@@HERO_SUMMARY@@</p>
  <div class="hero-stats">
    <div class="stat"><div class="num" data-target="@@N_OUTLETS@@">@@N_OUTLETS@@</div><div class="lbl">News Outlets</div></div>
    <div class="stat"><div class="num" data-target="@@N_STORIES@@">@@N_STORIES@@</div><div class="lbl">Stories</div></div>
    <div class="stat"><div class="num" data-target="@@N_WORDS@@">@@N_WORDS@@</div><div class="lbl">GRE Words</div></div>
  </div>
  <div class="scroll-cue"><span>Scroll</span><span class="line"></span></div>
</section>

<main>
  <section class="section">
    <div class="section-head"><h2>오늘의 핵심</h2><span class="en">The Big Picture</span><span class="rule"></span></div>
    <p class="big-picture reveal">@@BIG_PICTURE@@</p>
  </section>

  <section class="section">
    <div class="section-head"><h2>매체별 브리핑</h2><span class="en">By Outlet</span><span class="rule"></span></div>
    <div class="outlets">
@@OUTLETS@@
    </div>
  </section>

  <section class="section">
    <div class="section-head"><h2>오늘의 고급 어휘</h2><span class="en">GRE &amp; Academic</span><span class="rule"></span></div>
    <p class="vocab-intro">오늘 브리핑의 주제에서 뽑은 <b>GRE·논문 수준</b> 어휘입니다. 카드에 마우스를 올리거나 클릭하면 뜻·동의어·맥락이 나타납니다. 동의어는 그대로 GRE 동의어 연습에 쓰실 수 있습니다.</p>
    <div class="vocab-tools">
      <button class="vbtn" id="flipAll">전체 뒤집기</button>
      <button class="vbtn" id="resetAll">처음으로</button>
      <button class="vbtn" id="shuffle">섞기 🔀</button>
    </div>
    <div class="vocab-grid" id="vocabGrid">
@@VOCAB@@
    </div>
  </section>
</main>

<footer>
  <div class="f-brand"><b>Morning</b> Brief</div>
  <div class="f-meta">
    뉴스 &amp; GRE 어휘 다이제스트 · @@HERO_DATE@@<br />
    출처: @@SOURCES@@<br />
    GRE Verbal 송종옥
  </div>
</footer>

<script>
(function () {
  var root = document.documentElement;
  root.classList.add("js");
  var reveals = [].slice.call(document.querySelectorAll(".reveal"));
  function showAll() { reveals.forEach(function (el) { el.classList.add("in"); }); }
  if (!("IntersectionObserver" in window)) {
    showAll();
  } else {
    try {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
        });
      }, { threshold: 0.12 });
      reveals.forEach(function (el) { io.observe(el); });
    } catch (err) { showAll(); }
  }
  setTimeout(showAll, 1500);
  try {
    var saved = localStorage.getItem("mb-theme");
    if (saved) root.setAttribute("data-theme", saved);
  } catch (e) {}
  var tgl = document.getElementById("themeToggle");
  if (tgl) tgl.addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("mb-theme", next); } catch (e) {}
  });
  var progress = document.getElementById("progress");
  var topbar = document.getElementById("topbar");
  window.addEventListener("scroll", function () {
    var h = document.documentElement;
    var max = h.scrollHeight - h.clientHeight;
    var sc = max > 0 ? h.scrollTop / max : 0;
    if (progress) progress.style.width = (sc * 100) + "%";
    if (topbar) topbar.classList.toggle("scrolled", h.scrollTop > 40);
  }, { passive: true });
  try {
    var nums = [].slice.call(document.querySelectorAll(".stat .num[data-target]"));
    nums.forEach(function (el) {
      var target = parseInt(el.getAttribute("data-target"), 10) || 0;
      var n = 0, step = Math.max(1, Math.round(target / 30));
      el.textContent = "0";
      var t = setInterval(function () {
        n += step;
        if (n >= target) { n = target; clearInterval(t); }
        el.textContent = String(n);
      }, 28);
    });
  } catch (e) {}
  var cards = [].slice.call(document.querySelectorAll(".card"));
  cards.forEach(function (c) {
    c.addEventListener("click", function () { c.classList.toggle("flipped"); });
  });
  var flipAll = document.getElementById("flipAll");
  var resetAll = document.getElementById("resetAll");
  var shuffle = document.getElementById("shuffle");
  if (flipAll) flipAll.addEventListener("click", function () { cards.forEach(function (c) { c.classList.add("flipped"); }); });
  if (resetAll) resetAll.addEventListener("click", function () { cards.forEach(function (c) { c.classList.remove("flipped"); }); });
  if (shuffle) shuffle.addEventListener("click", function () {
    var grid = document.getElementById("vocabGrid");
    if (!grid) return;
    var items = [].slice.call(grid.children);
    for (var i = items.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      grid.insertBefore(items[j], items[i].nextSibling);
      items = [].slice.call(grid.children);
    }
  });
})();
</script>
</body>
</html>
'''


def esc(s):
    return html.escape(str(s), quote=False)


def render_outlet(o):
    rows = []
    for st in o.get("stories", []):
        lead = esc(st["lead"]).rstrip("。.")
        body = esc(st["body"])
        rows.append(
            '          <li class="story"><span class="mark">▸</span>'
            f'<p><b>{lead}.</b> {body}</p></li>'
        )
    return (
        '      <article class="outlet reveal">\n'
        '        <div class="outlet-top">'
        f'<div class="outlet-name">{esc(o["name"])}</div>'
        f'<div class="outlet-tag">{esc(o["tag"])}</div></div>\n'
        '        <ul class="stories">\n'
        + "\n".join(rows) + "\n"
        '        </ul>\n'
        '      </article>'
    )


def render_card(v):
    syns = "".join(f"<span>{esc(s)}</span>" for s in v.get("syns", []))
    src = esc(v.get("src", ""))
    src_html = f'<div class="src">{src}</div>' if src else ""
    return (
        '      <div class="card reveal" tabindex="0">\n'
        '        <div class="card-inner">\n'
        f'          <div class="face face-front"><span class="pos">{esc(v["pos"])}</span>'
        '<span class="flip-hint">hover ⟳</span>'
        f'<div class="word">{esc(v["w"])}</div>'
        f'<div class="word-sub">{esc(v["def"])}</div></div>\n'
        f'          <div class="face face-back"><div class="def">{esc(v["def"])}</div>'
        '<div class="syn-label">동의어 · Synonyms</div>'
        f'<div class="syns">{syns}</div>{src_html}</div>\n'
        '        </div>\n'
        '      </div>'
    )


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python3 tools/render.py data/YYYY-MM-DD.json")
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    date = data["date"]
    y, mo, d = map(int, date.split("-"))
    hero_date = f"{y}년 {mo}월 {d}일"

    outlets = data.get("outlets", [])
    vocab = data.get("vocab", [])
    n_outlets = len(outlets)
    n_stories = sum(len(o.get("stories", [])) for o in outlets)
    n_words = len(vocab)
    sources = " · ".join(o["name"] for o in outlets)

    out = TEMPLATE
    repl = {
        "@@DATE@@": date,
        "@@HERO_DATE@@": hero_date,
        "@@HERO_SUMMARY@@": esc(data["heroSummary"]),
        "@@BIG_PICTURE@@": esc(data["bigPicture"]),
        "@@N_OUTLETS@@": str(n_outlets),
        "@@N_STORIES@@": str(n_stories),
        "@@N_WORDS@@": str(n_words),
        "@@OUTLETS@@": "\n\n".join(render_outlet(o) for o in outlets),
        "@@VOCAB@@": "\n\n".join(render_card(v) for v in vocab),
        "@@SOURCES@@": esc(sources),
    }
    for k, v in repl.items():
        out = out.replace(k, v)

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fname = os.path.join(repo, f"news-digest-{date}.html")
    open(fname, "w", encoding="utf-8").write(out)
    print(f"렌더 완료: {os.path.basename(fname)} — 매체 {n_outlets}·기사 {n_stories}·어휘 {n_words}")


if __name__ == "__main__":
    main()
