"""봇의 답은 Claude 앱 세션으로, 초안 메일은 (선택) Cloudflare Worker로 보낸다.

- 답(뉴스 요약·안내): work/reply.md에 쌓았다가 `python -m bot reply`로 꺼내서
  클라우드 세션의 마지막 답변으로 보여준다. 사용자는 Claude 앱에서 읽고 그 세션에 바로 답장한다.
- 메일(선택): 클라우드 세션은 HTTP(S)만 나갈 수 있어서 SMTP를 직접 못 쓴다. 메일을 받고 싶으면
  Worker(gateway/)를 올리고 메일 비밀번호는 Worker에만 둔다. 여기서는
  `Authorization: Bearer <GATEWAY_KEY>`로 Worker를 부르는데, 이 헤더는 클라우드의 네트워크
  비밀키 기능이 자동으로 붙이므로 키가 세션 안에 들어오지 않는다.
  BOT_GATEWAY_URL이 비어 있으면 메일 없이 초안을 세션 답변으로 보여준다.

환경변수
- BOT_GATEWAY_URL : (메일을 쓸 때만) Worker 주소 + /news
- BOT_GATEWAY_KEY : 내 PC에서 시험할 때만. 클라우드에서는 비워 둔다 (프록시가 붙임)
- BOT_DRY_RUN=1   : 메일을 실제로 보내지 않고 work/outbox/에 파일로 남긴다 (테스트용)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path


def _work() -> Path:
    return Path(os.environ.get("BOT_WORK_DIR", "work"))


def mail_enabled() -> bool:
    return os.environ.get("BOT_DRY_RUN") == "1" or bool(os.environ.get("BOT_GATEWAY_URL"))


def send_text(text: str) -> bool:
    p = _work() / "reply.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(str(text).rstrip() + "\n\n")
    return True


def take_reply() -> str:
    """쌓인 답을 꺼내고 비운다"""
    p = _work() / "reply.md"
    if not p.exists():
        return "(보낼 답 없음)"
    text = p.read_text(encoding="utf-8").strip()
    p.unlink()
    return text


def _outbox(kind: str, payload: dict) -> bool:
    d = _work() / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("*.json")))
    (d / f"{n:04d}_{kind}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def send_mail(subject: str, html: str) -> bool:
    """받는 사람은 중계 서버에 설정된 내 메일 주소 (나에게 보내기)"""
    payload = {"subject": subject, "html": html}
    if os.environ.get("BOT_DRY_RUN") == "1":
        return _outbox("mail", payload)
    base = os.environ.get("BOT_GATEWAY_URL", "").rstrip("/")
    if not base:
        return False
    req = urllib.request.Request(
        base + "/mail", data=json.dumps(payload).encode("utf-8"), method="POST",
        # 파이썬 기본 User-Agent(Python-urllib)는 Cloudflare가 403(error 1010)으로 막는다
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "cloud-news-bot/1.0"})
    key = os.environ.get("BOT_GATEWAY_KEY")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.loads(r.read().decode("utf-8") or "{}")
                return bool(body.get("ok", r.status == 200))
        except Exception as e:  # noqa: BLE001 - 실패하면 호출한 쪽이 세션 답변으로 대신 보낸다
            print(f"[gateway] /mail 실패({attempt + 1}/3): {e}")
            time.sleep(2 * (attempt + 1))
    return False
