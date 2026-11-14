"""실제 발송 없이(BOT_DRY_RUN) 전체 흐름을 돌려 보는 테스트.  실행: python -m pytest -q"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DRAFT = """제목: 시험용 제목
본문:
내 의견으로 시작하는 첫 문단이다. {pad}

## 첫 번째 이야기
OO에 따르면 이런 일이 있었다. **중요한 부분**은 이것이다. {pad}

## 두 번째 이야기
그래서 이렇게 생각한다. {pad}
태그: #시험 #뉴스 #봇 #테스트 #예시"""


def make_draft(n_pad):
    return DRAFT.format(pad="가" * n_pad)


def bot(tmp, *args, now="2026-11-16T20:05"):
    env = {**os.environ, "BOT_DRY_RUN": "1", "BOT_STATE_DIR": str(tmp / "state"),
           "BOT_WORK_DIR": str(tmp / "work"), "BOT_NOW": now, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-m", "bot", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def result(tmp, text):
    (tmp / "work" / "result.txt").write_text(text, encoding="utf-8")


def outbox(tmp):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((tmp / "work" / "outbox").glob("*.json"))]


def handle(tmp, text, **kw):
    (tmp / "inbox.txt").write_text(text, encoding="utf-8")
    return bot(tmp, "handle", "--file", str(tmp / "inbox.txt"), **kw)


def test_full_flow(tmp_path):
    out = bot(tmp_path, "collect")
    assert out.startswith("TASK facts")
    task = (tmp_path / "work" / "task.md").read_text(encoding="utf-8")
    assert "2026-11-17 (화요일)" in task and "반도체" in task  # 20시 이후 → 다음 날 발행분, config.md 포함

    result(tmp_path, "📰 오늘의 뉴스\n\n1. 첫 이슈\n- 사실 (OO에 따르면)\n- [파고들 지점] 원리")
    assert bot(tmp_path, "continue").startswith("DONE")
    assert json.loads((tmp_path / "state" / "2026-11-17.json").read_text(encoding="utf-8"))["stage"] == "facts_sent"

    assert handle(tmp_path, "첫 이슈가 제일 흥미롭다").startswith("TASK draft")
    result(tmp_path, make_draft(30))  # 너무 짧음 → 늘리기 요청
    assert bot(tmp_path, "continue").startswith("TASK resize")
    result(tmp_path, make_draft(600))
    assert bot(tmp_path, "continue").startswith("DONE")
    mails = [m for m in outbox(tmp_path) if "html" in m]
    assert mails and mails[-1]["subject"] == "[초안] 시험용 제목" and "<b>중요한 부분</b>" in mails[-1]["html"]

    assert handle(tmp_path, "제목 더 짧게").startswith("TASK revise")
    result(tmp_path, make_draft(600).replace("시험용 제목", "짧은 제목"))
    assert bot(tmp_path, "continue").startswith("DONE")
    assert [m for m in outbox(tmp_path) if "html" in m][-1]["subject"] == "[수정본] 짧은 제목"


def test_cancel_and_idle(tmp_path):
    assert "취소할 것 없음" in handle(tmp_path, "/취소")
    assert "진행 중인 글 없음" in handle(tmp_path, "아무 말")
    bot(tmp_path, "collect")
    result(tmp_path, "1. 이슈\n- 사실")
    bot(tmp_path, "continue")
    assert "취소함" in handle(tmp_path, "/ 취소")
    assert bot(tmp_path, "collect").startswith("TASK facts")  # 취소 후 다시 시작 가능


def test_bad_draft_reverts(tmp_path):
    bot(tmp_path, "collect")
    result(tmp_path, "1. 이슈\n- 사실")
    bot(tmp_path, "continue")
    handle(tmp_path, "의견")
    result(tmp_path, "형식이 아닌 응답")
    assert bot(tmp_path, "continue").startswith("DONE: 실패")
    assert handle(tmp_path, "다시 의견").startswith("TASK draft")  # 의견 다시 보내면 재시도
