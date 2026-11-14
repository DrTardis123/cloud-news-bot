"""뉴스봇 흐름.

  수집(collect) → 텔레그램으로 뉴스 사실 전송 → 주인이 의견 답장(handle)
  → 초안 작성 → 분량 확인(필요하면 한 번 늘리기/줄이기) → 메일 발송
  → 이후 메시지는 수정 요청으로 처리

글을 쓰는 건 클라우드의 Claude다. 이 모듈은 Claude에게 줄 지시서(work/task.md)를 만들고,
Claude가 쓴 결과(work/result.txt)를 받아 다음 단계로 넘긴다. 출력이 `TASK ...`면 Claude가
지시를 수행하고 `python -m bot continue`, `DONE: ...`이면 끝.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import gateway as gw
from . import render

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("BOT_STATE_DIR", ROOT / "state"))
WORK = Path(os.environ.get("BOT_WORK_DIR", ROOT / "work"))
CONFIG = Path(os.environ.get("BOT_CONFIG", ROOT / "config.md"))
PROMPTS = ROOT / "prompts"
TZ = ZoneInfo(os.environ.get("BOT_TZ", "Asia/Seoul"))
WEEKDAYS = "월화수목금토일"

HELP = ("사용법\n"
        "/오늘뉴스 — 지금 바로 뉴스 모으기 (매일 정해진 시각에는 자동으로 해)\n"
        "/취소 — 진행 중인 글 취소\n"
        "뉴스를 받은 뒤 아무 말이나 보내면 → 그게 내 의견이 돼서 초안을 써서 메일로 보내\n"
        "초안을 받은 뒤 보내는 말은 → 수정 요청으로 처리해 (예: '제목 더 짧게')\n"
        "주제·말투·분량은 저장소의 config.md에서 바꿔.")


# ---------------------------------------------------------------- 설정·시간

def config_text() -> str:
    return CONFIG.read_text(encoding="utf-8-sig") if CONFIG.exists() else "(config.md 없음 — 일반 시사 뉴스)"


def config_value(name: str, default: str = "") -> str:
    m = re.search(rf"^\s*-\s*{re.escape(name)}\s*[:：]\s*(.+?)\s*$", config_text(), re.M)
    return m.group(1) if m else default


def _range(name: str, default: tuple[int, int]) -> tuple[int, int]:
    nums = [int(n) for n in re.findall(r"\d+", config_value(name, ""))]
    if not nums:
        return default
    lo, hi = (nums[0], nums[1]) if len(nums) >= 2 else (nums[0], nums[0])
    return (min(lo, hi), max(lo, hi))


def length_range() -> tuple[int, int]:
    return _range("글 길이", (1500, 2500))


def photo_range() -> tuple[int, int]:
    return _range("사진 개수", (4, 6))


def now() -> datetime:
    fake = os.environ.get("BOT_NOW")  # 테스트용: 2026-11-16T20:00
    return datetime.fromisoformat(fake).replace(tzinfo=TZ) if fake else datetime.now(TZ)


def publish_day() -> datetime:
    """오전 7시 전이면 오늘 올릴 글, 그 뒤면 내일 올릴 글로 본다 (저녁에 모아 다음 날 아침 발행)."""
    t = now()
    d = t.replace(hour=0, minute=0, second=0, microsecond=0)
    return d if t.hour < 7 else d + timedelta(days=1)


def ymd(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 상태 파일 (state/YYYY-MM-DD.json)

def state_path(date: str) -> Path:
    return STATE_DIR / f"{date}.json"


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def save(p: Path, s: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    s["updatedAt"] = now().isoformat(timespec="seconds")
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def recent_states(stages: tuple[str, ...]) -> list[Path]:
    """어제·오늘·내일 날짜 파일 중 해당 단계인 것, 최근 수정순"""
    base = now().replace(hour=0, minute=0, second=0, microsecond=0)
    found = []
    for k in (-1, 0, 1):
        p = state_path(ymd(base + timedelta(days=k)))
        if p.exists():
            s = load(p)
            if s.get("stage") in stages:
                found.append((s.get("updatedAt", ""), p))
    return [p for _, p in sorted(found, reverse=True)]


def history_block(exclude: str) -> str:
    files = sorted(STATE_DIR.glob("????-??-??.json"), reverse=True) if STATE_DIR.exists() else []
    items = []
    for p in files[:10]:
        if p.stem == exclude:
            continue
        titles = re.findall(r"^\s*\d+\.\s*(.+)$", load(p).get("facts", ""), re.M)
        items += [f"- ({p.stem}) {t.strip()}" for t in titles]
    if not items:
        return ""
    return ("## 최근에 이미 다룬 뉴스 (같은 사안은 새 진전이 없으면 고르지 마)\n\n" + "\n".join(items[:30]))


# ---------------------------------------------------------------- 지시서 주고받기

def template(name: str, **kw) -> str:
    s = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    lo, hi = length_range()
    pmin, pmax = photo_range()
    kw.setdefault("CONFIG", config_text())
    kw.setdefault("LEN_MIN", lo)
    kw.setdefault("LEN_MAX", hi)
    kw.setdefault("TRIM_FLOOR", int(hi * 0.9))
    kw.setdefault("PHOTO_MIN", pmin)
    kw.setdefault("PHOTO_MAX", pmax)
    for k, v in kw.items():
        s = s.replace("{{" + k + "}}", str(v))
    return s


def write_task(step: str, prompt: str, **ctx) -> str:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "task.md").write_text(prompt, encoding="utf-8")
    (WORK / "ctx.json").write_text(json.dumps({"step": step, **ctx}, ensure_ascii=False), encoding="utf-8")
    (WORK / "result.txt").unlink(missing_ok=True)
    return (f"TASK {step}: work/task.md 의 지시를 그대로 수행하고, 지시가 요구한 출력 텍스트만 "
            "work/result.txt 에 저장한 뒤 `python -m bot continue` 를 실행해.")


def done(msg: str) -> str:
    (WORK / "ctx.json").unlink(missing_ok=True)
    return f"DONE: {msg}"


def resume() -> str:
    ctx_p, res_p = WORK / "ctx.json", WORK / "result.txt"
    if not ctx_p.exists():
        return "DONE: 이어서 할 작업 없음"
    if not res_p.exists():
        return "TASK 대기: work/result.txt 가 아직 없어. work/task.md 를 수행해서 결과를 저장한 뒤 다시 continue."
    ctx = json.loads(ctx_p.read_text(encoding="utf-8"))
    result = res_p.read_text(encoding="utf-8").strip()
    step = ctx["step"]
    if step == "facts":
        return facts_done(ctx, result)
    if step == "draft":
        return draft_done(ctx, result)
    if step in ("expand", "trim"):
        return resize_done(ctx, result)
    if step == "revise":
        return revise_done(ctx, result)
    return done(f"알 수 없는 단계 {step}")


def fail(reason: str) -> str:
    ctx_p = WORK / "ctx.json"
    if ctx_p.exists():
        ctx = json.loads(ctx_p.read_text(encoding="utf-8"))
        orig = WORK / "original_draft.txt"
        if ctx.get("step") in ("expand", "trim") and orig.exists():  # 늘리기/줄이기 실패는 원래 초안으로 발송
            return finalize(Path(ctx["state"]), parse_draft(orig.read_text(encoding="utf-8")))
        if ctx.get("step") == "draft" and ctx.get("state"):
            p = Path(ctx["state"])
            s = load(p)
            s["stage"] = "facts_sent"  # 의견을 다시 보내면 처음부터 다시 쓴다
            save(p, s)
    gw.send_text(f"⚠️ 작업을 끝내지 못했어: {reason}\n같은 메시지를 다시 보내면 다시 시도할게.")
    return done(f"실패: {reason}")


# ---------------------------------------------------------------- 1) 수집

def collect() -> str:
    pday = publish_day()
    date = ymd(pday)
    p = state_path(date)
    if p.exists():
        st = load(p).get("stage")
        if st in ("facts_sent", "drafting"):
            gw.send_text("이미 진행 중인 글이 있어. 뉴스에 대한 의견을 보내거나, 새로 하려면 먼저 /취소를 보내줘.")
            return done("이미 진행 중")
        if st == "approved":
            gw.send_text("이 날짜 글은 이미 메일로 보냈어. 고칠 점을 말로 보내면 수정할게. 새로 하려면 /취소 후 /오늘뉴스.")
            return done("이미 발송함")
    gw.send_text(f"🔎 {config_value('주제', '뉴스')} 뉴스 찾는 중... 몇 분 걸려.")
    prompt = template("facts", DATE=ymd(now()), PUB_DATE=date, WEEKDAY=WEEKDAYS[pday.weekday()],
                      HISTORY=history_block(date))
    return write_task("facts", prompt, date=date)


def facts_done(ctx: dict, result: str) -> str:
    result = result or "(검색 결과 없음)"
    p = state_path(ctx["date"])
    save(p, {"stage": "facts_sent", "date": ctx["date"], "facts": result, "opinion": "", "draft": ""})
    gw.send_text(result)
    gw.send_text("---\n이 뉴스에 대한 네 생각을 답장으로 보내줘. 짧아도 돼 (예: '2번이 제일 흥미로움, 왜 지금 이런지 궁금').")
    return done("뉴스 전송, 의견 기다리는 중")


# ---------------------------------------------------------------- 2) 메시지

def handle(text: str) -> str:
    text = (text or "").strip()
    cmd = re.sub(r"\s+", "", text)
    if cmd in ("/start", "/도움", "/help"):
        gw.send_text(HELP)
        return done("도움말")
    if cmd == "/오늘뉴스":
        return collect()
    if cmd == "/취소":
        return cancel()

    waiting = recent_states(("facts_sent",))
    if waiting:
        p = waiting[0]
        s = load(p)
        s.update(stage="drafting", opinion=text)
        save(p, s)
        gw.send_text("✍️ 의견 받았어. 초안 쓰는 중... (5분 안팎)")
        return write_task("draft", template("draft", FACTS=s["facts"], OPINION=text), state=str(p))

    sent = recent_states(("approved",))
    if sent:
        p = sent[0]
        s = load(p)
        gw.send_text("🛠 수정 요청으로 받았어. 고치는 중...")
        summary = "\n".join(f"{r['item']} | {r['content']}" for r in s.get("summaryTable", []))
        return write_task("revise", template("revise", TITLE=s.get("title", ""), SUMMARY=summary,
                                             DRAFT=s.get("draft", ""), IMAGES=s.get("imageSuggestions", ""),
                                             HASHTAGS=" ".join(s.get("hashtags", [])), REQUEST=text),
                          state=str(p))

    if recent_states(("drafting",)):
        gw.send_text("지금 초안을 쓰는 중이야. 메일이 오면 그때 수정할 점을 보내줘.")
        return done("작성 중이라 무시")
    gw.send_text("진행 중인 글이 없어. /오늘뉴스 를 보내면 시작할게.\n\n" + HELP)
    return done("진행 중인 글 없음")


def cancel() -> str:
    active = recent_states(("facts_sent", "drafting"))
    if not active:
        gw.send_text("취소할 것이 없어.")
        return done("취소할 것 없음")
    for p in active:
        s = load(p)
        s["stage"] = "cancelled"
        save(p, s)
    gw.send_text("취소했어. 새로 하려면 /오늘뉴스.")
    return done("취소함")


# ---------------------------------------------------------------- 3) 초안 → 분량 → 메일

def parse_draft(result: str) -> dict:
    """제목 / [요약표] / 본문 / [이미지 추천] / [해시태그] 로 나눈다."""
    result = (result or "").strip()
    m = re.search(r"(?m)^제목:", result)
    if m and m.start() > 0:
        result = result[m.start():]
    hashtags = ""
    m = re.search(r"(?s)\r?\n\r?\n\[해시태그\]\r?\n(.+)$", result)
    if m:
        hashtags = m.group(1).strip()
        result = result[: len(result) - len(m.group(0))].rstrip()
    out = {"title": "", "body": result, "images": "", "summary": "", "hashtags": hashtags}
    m = re.search(r"(?s)^제목:\s*(.+?)\r?\n\r?\n\[요약표\]\r?\n(.+?)\r?\n\r?\n(.+?)\r?\n\r?\n\[이미지 추천\]\r?\n(.+)$", result)
    if m:
        out.update(title=m.group(1).strip(), summary=m.group(2).strip(), body=m.group(3).strip(),
                   images=m.group(4).strip())
        return out
    m = re.search(r"(?s)^제목:\s*(.+?)\r?\n\r?\n(.+?)\r?\n\r?\n\[이미지 추천\]\r?\n(.+)$", result)
    if m:
        out.update(title=m.group(1).strip(), body=m.group(2).strip(), images=m.group(3).strip())
        return out
    m = re.search(r"(?s)^제목:\s*(.+?)\r?\n\r?\n(.+)$", result)
    if m:
        out.update(title=m.group(1).strip(), body=m.group(2).strip())
    return out


def prose_len(body: str) -> int:
    """분량 — [그래프]/[수식] 줄과 [사진N] 마커는 빼고 센다"""
    if not body:
        return 0
    kept = [l for l in re.split(r"\r?\n", body) if not re.match(r"^\s*\[(그래프|수식)\]", l)]
    return len(re.sub(r"\[사진\d+\]", "", "\n".join(kept)))


def section_count(body: str) -> int:
    return len(re.findall(r"\[소제목\]", body or ""))


def draft_done(ctx: dict, result: str) -> str:
    p = Path(ctx["state"])
    parsed = parse_draft(result)
    if not parsed["title"].strip():  # 제목 없는 안내문은 발송하지 않는다
        gw.send_text(result[:3500] or "(빈 응답)")
        return fail("초안 형식이 아니라서 메일로 못 보냈어 (위 내용 참고)")
    lo, hi = length_range()
    n = prose_len(parsed["body"])
    if n < lo or n > int(hi * 1.1):
        step = "expand" if n < lo else "trim"
        (WORK / "original_draft.txt").write_text(result, encoding="utf-8")
        return write_task(step, template(step, BODY_LEN=n, RESULT=result), state=str(p))
    return finalize(p, parsed)


def resize_done(ctx: dict, result: str) -> str:
    """늘리기/줄이기 결과가 더 나쁘면 원래 초안으로 발송한다."""
    orig = parse_draft((WORK / "original_draft.txt").read_text(encoding="utf-8"))
    new = parse_draft(result)
    if not new["title"].strip():
        return finalize(Path(ctx["state"]), orig)
    if ctx["step"] == "expand":
        chosen = new if prose_len(new["body"]) > prose_len(orig["body"]) else orig
    else:
        lo, _ = length_range()
        lost = section_count(new["body"]) < section_count(orig["body"])  # 섹션이 사라지면 의견도 사라진다
        ok = not lost and prose_len(orig["body"]) > prose_len(new["body"]) >= lo
        chosen = new if ok else orig
    return finalize(Path(ctx["state"]), chosen)


def revise_done(ctx: dict, result: str) -> str:
    parsed = parse_draft(result)
    if not parsed["title"].strip():
        gw.send_text(result[:3500] or "(빈 응답)")
        return done("수정본 형식 아님 — 텔레그램으로만 전달")
    return finalize(Path(ctx["state"]), parsed, revised=True)


def finalize(p: Path, parsed: dict, revised: bool = False) -> str:
    s = load(p)
    title = render.convert_math(parsed["title"])
    body = render.convert_math(render.remove_trailing_hashtag_lines(parsed["body"]))
    images = render.parse_image_suggestions(parsed["images"])
    rows = render.parse_summary_table(parsed["summary"])
    tags = [t for t in re.split(r"\s+", parsed["hashtags"]) if re.match(r"^#\S+", t)]
    s.update(title=title, draft=body, imageSuggestions=parsed["images"],
             summaryTable=[{"item": a, "content": b} for a, b in rows], hashtags=tags, stage="approved")
    save(p, s)

    html = render.draft_email(title, rows, render.email_body(body, images), tags, images)
    label = "수정본" if revised else "초안"
    sent = gw.send_mail(f"[블로그 {label}] {title}", html)
    real = sum(1 for i in images if i.source)
    if sent:
        gw.send_text(
            f"✅ {label}을 메일로 보냈어!\n\n제목: {title}\n본문 {prose_len(body)}자 · 사진 {len(images)}장"
            f" (실제 사진 {real} / AI 그림 프롬프트 {len(images) - real})\n\n"
            "메일의 파란 박스는 링크에서 실제 사진을 받아 넣고 출처 한 줄을 사진 아래에, "
            "초록 박스는 프롬프트를 제미나이(gemini.google.com)에 붙여넣어 그림을 만들어 넣으면 돼.\n"
            "고칠 점이 있으면 그냥 말로 보내줘 (예: '제목 더 짧게').")
    else:
        gw.send_text("⚠️ 메일 발송에 실패해서 여기로 보낼게. 제목·본문을 블로그에 붙여넣고 사진은 아래 목록대로 넣어줘.")
        gw.send_text(f"[제목]\n{title}\n\n[본문]\n{render.format_markers_for_preview(body)}")
        msg = render.image_suggestions_message(images)
        if msg:
            gw.send_text(msg)
        if tags:
            gw.send_text(" ".join(tags))
    return done(f"{label} 확정 ({'메일 발송' if sent else '메일 실패 → 텔레그램'}): {title}")
