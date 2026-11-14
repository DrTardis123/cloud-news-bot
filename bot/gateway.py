"""바깥으로 나가는 통신(텔레그램·메일)은 전부 Cloudflare Worker(중계 서버)를 거친다.

클라우드 세션은 HTTP(S)만 나갈 수 있어서 메일(SMTP)을 직접 못 보내고, 텔레그램 토큰은 URL에
들어가서 네트워크 비밀키로 숨길 수 없다. 그래서 토큰·메일 비밀번호는 Worker에만 두고, 여기서는
`Authorization: Bearer <GATEWAY_KEY>`로 Worker를 부른다. 클라우드에서는 이 헤더를 네트워크
비밀키 기능이 자동으로 붙이므로 키가 세션 안에 들어오지 않는다.

환경변수
- BOT_GATEWAY_URL : Worker 주소 + /news (예: https://news-bot-gateway.<이름>.workers.dev/news)
- BOT_GATEWAY_KEY : 내 PC에서 시험할 때만. 클라우드에서는 비워 둔다 (프록시가 붙임)
- BOT_DRY_RUN=1   : 실제로 보내지 않고 work/outbox/에 파일로 남긴다 (테스트용)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

MAX_TG = 4000


def _outbox(kind: str, payload: dict) -> bool:
    d = Path(os.environ.get("BOT_WORK_DIR", "work")) / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("*.json")))
    (d / f"{n:04d}_{kind}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _post(path: str, payload: dict) -> bool:
    if os.environ.get("BOT_DRY_RUN") == "1":
        return _outbox(path.strip("/"), payload)
    base = os.environ.get("BOT_GATEWAY_URL", "").rstrip("/")
    if not base:
        print(f"[gateway] BOT_GATEWAY_URL이 비어 있음 — {path} 전송 생략")
        return False
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"), method="POST",
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
        except Exception as e:  # noqa: BLE001 - 실패는 호출한 쪽에서 대체 경로로 처리
            print(f"[gateway] {path} 실패({attempt + 1}/3): {e}")
            time.sleep(2 * (attempt + 1))
    return False


def send_text(text: str) -> bool:
    text = str(text)
    chunks = [text[i:i + MAX_TG] for i in range(0, len(text), MAX_TG)] or [""]
    return all([_post("/tg", {"text": c}) for c in chunks])


def send_mail(subject: str, html: str) -> bool:
    """받는 사람은 중계 서버에 설정된 내 메일 주소 (나에게 보내기)"""
    return _post("/mail", {"subject": subject, "html": html})
