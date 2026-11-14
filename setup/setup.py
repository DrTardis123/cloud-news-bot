"""cloud-news-bot 설치 도우미.

실행:  python setup/setup.py
  - 중간에 멈춰도 다시 실행하면 끝난 단계는 건너뛴다 (기록: setup/.local.json)
  - 처음부터 다시: python setup/setup.py --reset

하는 일
  1. 텔레그램 봇 토큰 확인 + 내 채팅 ID 자동으로 찾기
  2. 메일(네이버/Gmail) 로그인 시험
  3. Cloudflare에 중계 서버 배포 + 비밀값 넣기
  4. claude.ai에 넣을 값을 파일로 정리 (복사용)
  5. 예약 작업 토큰 받아서 연결
  6. 텔레그램 웹훅 연결 + 시험 메시지
"""
from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import smtplib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GATEWAY_DIR = ROOT / "gateway"
STATE_FILE = HERE / ".local.json"
VALUES_FILE = HERE / "내_설정값.txt"
BOT = "news"  # 중계 서버 경로(/news)와 비밀값 접두사(NEWS_)
P = BOT.upper() + "_"
UA = {"User-Agent": "cloud-news-bot-setup/1.0"}
IS_WIN = os.name == "nt"

MAIL_PRESETS = {
    "1": ("네이버", "smtp.naver.com", 587),
    "2": ("Gmail", "smtp.gmail.com", 587),
}


# ---------------------------------------------------------------- 작은 도우미

def say(msg=""):
    print(msg, flush=True)


def title(n, msg):
    say()
    say("=" * 60)
    say(f" {n}단계. {msg}")
    say("=" * 60)


def ask(msg, secret=False):
    while True:
        v = (getpass.getpass(msg) if secret else input(msg)).strip()
        if v:
            return v
        say("  비어 있어요. 다시 입력해 주세요.")


def load_state():
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def http_json(url, data=None, headers=None, method=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    h = {**UA, **({"Content-Type": "application/json"} if body else {}), **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=h, method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": f"HTTP {e.code}"}


def tg(token, method, **params):
    return http_json(f"https://api.telegram.org/bot{token}/{method}", params or None)


def run(cmd, cwd=GATEWAY_DIR, capture=False, input_text=None):
    """npx·npm은 Windows에서 .cmd라 shell=True로 부른다."""
    return subprocess.run(cmd, cwd=cwd, shell=True, text=True, encoding="utf-8", errors="replace",
                          capture_output=capture, input=input_text)


def put_secrets(values: dict):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(values, f)
        path = f.name
    try:
        r = run(f'npx wrangler secret bulk "{path}"', capture=True)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            say(out[-1500:])
            sys.exit("  비밀값을 넣지 못했어요. 위 오류를 확인하고 다시 실행해 주세요.")
    finally:
        os.unlink(path)  # 비밀값이 담긴 임시 파일은 바로 지운다


# ---------------------------------------------------------------- 단계

def step_check():
    title(0, "준비물 확인")
    if sys.version_info < (3, 9):
        sys.exit("  파이썬 3.9 이상이 필요해요. README의 '준비물'을 보고 설치해 주세요.")
    say(f"  파이썬 {sys.version.split()[0]} ✓")
    r = run("node --version", cwd=ROOT, capture=True)
    if r.returncode != 0:
        sys.exit("  Node.js가 없어요. https://nodejs.org 에서 LTS 버전을 설치하고 터미널을 새로 연 뒤 다시 실행해 주세요.")
    say(f"  Node.js {r.stdout.strip()} ✓")


def step_telegram(st):
    title(1, "텔레그램 봇 연결")
    if st.get("tg_token") and st.get("chat_id"):
        say(f"  이미 완료 (봇 @{st.get('bot_username')}) — 건너뜀")
        return
    while True:
        token = ask("  BotFather가 준 봇 토큰을 붙여넣고 Enter: ")
        me = tg(token, "getMe")
        if me.get("ok"):
            break
        say("  ✗ 토큰이 틀렸어요. 숫자:영문 형태 전체를 복사했는지 확인해 주세요.")
    username = me["result"]["username"]
    say(f"  ✓ 봇 확인: @{username}")
    tg(token, "deleteWebhook")  # 예전 웹훅이 있으면 메시지를 못 읽으므로 잠깐 해제
    say()
    say(f"  이제 휴대폰 텔레그램에서 @{username} 을 열고 아무 메시지나 보내 주세요 (예: 안녕).")
    say("  기다리는 중... (최대 3분)")
    chat_id = None
    for _ in range(36):
        res = tg(token, "getUpdates", timeout=0)
        for u in reversed(res.get("result", [])):
            msg = u.get("message") or {}
            if msg.get("chat", {}).get("id"):
                chat_id = msg["chat"]["id"]
                break
        if chat_id:
            break
        time.sleep(5)
    if not chat_id:
        sys.exit("  메시지를 못 찾았어요. 봇에게 메시지를 보낸 뒤 다시 실행해 주세요.")
    say(f"  ✓ 내 채팅 ID 찾음: {chat_id}")
    st.update(tg_token=token, chat_id=str(chat_id), bot_username=username)
    save_state(st)


def step_mail(st):
    title(2, "메일 설정 (초안을 받을 메일)")
    if st.get("mail_user"):
        say(f"  이미 완료 ({st['mail_user']}) — 건너뜀")
        return
    say("  1) 네이버 메일   2) Gmail   3) 기타(직접 입력)")
    choice = ask("  번호를 고르고 Enter: ")
    if choice in MAIL_PRESETS:
        name, host, port = MAIL_PRESETS[choice]
    else:
        name, host, port = "기타", ask("  SMTP 서버 주소 (예: smtp.example.com): "), int(ask("  포트 (보통 587): "))
    user = ask(f"  {name} 메일 주소 전체 (예: myid@naver.com): ")
    say("  앱 비밀번호를 붙여넣고 Enter (입력해도 화면에 안 보이는 게 정상이에요)")
    pw = ask("  앱 비밀번호: ", secret=True).replace(" ", "")
    say("  메일 로그인 시험 중...")
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(user, pw)
    except Exception as e:  # noqa: BLE001
        say(f"  ✗ 로그인 실패: {e}")
        say("  - 네이버: 메일 환경설정 > POP3/IMAP 설정 > 'IMAP/SMTP 사용'을 켰는지,")
        say("            2단계 인증을 켜고 '애플리케이션 비밀번호'를 새로 만들었는지 확인")
        say("  - Gmail: 2단계 인증을 켠 뒤 '앱 비밀번호'(16자리)를 만들었는지 확인")
        sys.exit("  확인 후 다시 실행해 주세요.")
    say("  ✓ 메일 로그인 성공")
    st.update(mail_host=host, mail_port=str(port), mail_user=user, mail_pass=pw)
    save_state(st)


def step_cloudflare(st):
    title(3, "Cloudflare에 중계 서버 올리기")
    if st.get("gateway_url"):
        say(f"  이미 완료 ({st['gateway_url']}) — 건너뜀")
        return
    if not (GATEWAY_DIR / "node_modules").exists():
        say("  필요한 파일 설치 중 (npm install, 1~2분)...")
        if run("npm install --no-audit --no-fund").returncode != 0:
            sys.exit("  npm install 실패. 인터넷 연결을 확인하고 다시 실행해 주세요.")
    r = run("npx wrangler whoami", capture=True)
    if "You are logged in" not in (r.stdout or "") + (r.stderr or ""):
        say("  브라우저가 열리면 Cloudflare에 로그인하고 [Allow]를 눌러 주세요. (몇 분 안에 눌러야 해요)")
        if run("npx wrangler login").returncode != 0:
            sys.exit("  로그인이 끝나지 않았어요. 다시 실행해 주세요. (README '자주 막히는 곳' 참고)")
    say("  중계 서버 배포 중...")
    r = run("npx wrangler deploy", capture=True)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"https://[\w.-]+\.workers\.dev", out)
    if r.returncode != 0 or not m:
        say(out[-2000:])
        if "verify your email" in out:
            sys.exit("  Cloudflare 가입 메일의 인증 링크를 먼저 누른 뒤 다시 실행해 주세요.")
        sys.exit("  배포 실패. 위 메시지를 확인하고 다시 실행해 주세요. (README '자주 막히는 곳' 참고)")
    url = m.group(0)
    say(f"  ✓ 배포 완료: {url}")

    st.setdefault("gateway_key", secrets.token_urlsafe(32))
    st.setdefault("webhook_secret", secrets.token_urlsafe(32))
    say("  비밀값 넣는 중...")
    put_secrets({
        P + "TG_TOKEN": st["tg_token"], P + "CHAT_ID": st["chat_id"],
        P + "WEBHOOK_SECRET": st["webhook_secret"], P + "GATEWAY_KEY": st["gateway_key"],
        P + "MAIL_HOST": st["mail_host"], P + "MAIL_PORT": st["mail_port"],
        P + "MAIL_USER": st["mail_user"], P + "MAIL_PASS": st["mail_pass"],
        P + "BOT_NAME": "뉴스봇",
    })
    say("  새 주소가 인터넷에 퍼지는 중 (보통 1~2분)...")
    for _ in range(30):
        try:
            if http_json(f"{url}/{BOT}/health").get("ok"):
                break
        except Exception:  # noqa: BLE001 - 인증서 발급 전에는 접속 오류가 정상
            pass
        time.sleep(10)
    else:
        sys.exit("  주소가 아직 안 열려요. 5분 뒤 다시 실행해 주세요 (끝난 단계는 건너뜀).")
    r = http_json(f"{url}/{BOT}/tg", {"text": "🔧 설치 중: 중계 서버 → 텔레그램 연결 확인"},
                  {"Authorization": f"Bearer {st['gateway_key']}"})
    if not r.get("ok"):
        sys.exit(f"  텔레그램 발송 시험 실패: {r}")
    say("  ✓ 텔레그램에 시험 메시지가 갔어요")
    st["gateway_url"] = url
    save_state(st)


def step_values_file(st):
    title(4, "claude.ai에 넣을 값 정리")
    host = st["gateway_url"].replace("https://", "")
    VALUES_FILE.write_text(
        "claude.ai 클라우드 환경에 넣을 값 (README 5단계)\n"
        "※ 이 파일은 내 컴퓨터에만 있고 GitHub에 올라가지 않아요. 다 쓰면 지워도 됩니다.\n\n"
        "[환경 변수] 칸에 아래 한 줄을 그대로:\n"
        f"BOT_GATEWAY_URL={st['gateway_url']}/{BOT}\n\n"
        "[시크릿 추가] 창:\n"
        f"  허용된 웹사이트 : {host}\n"
        "  경로 접두사     : (비워 두기)\n"
        "  헤더 이름/접두사: Authorization / Bearer (그대로)\n"
        "  값              : 아래 줄을 복사해서 붙여넣기\n"
        f"{st['gateway_key']}\n",
        encoding="utf-8")
    say(f"  ✓ 값을 이 파일에 정리했어요: {VALUES_FILE}")
    if IS_WIN:
        os.startfile(VALUES_FILE)  # 메모장으로 열기
        say("  메모장 창이 열렸어요. 여기서 복사해서 붙여넣으세요.")
    say("  (터미널 글자를 드래그해서 복사하지 마세요. 줄바꿈·테두리가 섞여서 실패하는 일이 많아요)")


def step_routine(st):
    title(5, "Claude 예약 작업 연결")
    if st.get("routine_url"):
        say("  이미 완료 — 건너뜀")
        return
    say("  README 5~6단계를 따라 claude.ai에서")
    say("   (1) 클라우드 환경 'news-bot'  (2) 예약 작업 'news-message'(API)  (3) 'news-daily'(매일)")
    say("  를 만든 뒤 돌아오세요.")
    input("  다 했으면 Enter...")
    while True:
        rid = ask("  'news-message' 예약 작업 페이지의 주소(또는 trig_로 시작하는 ID)를 붙여넣고 Enter: ")
        m = re.search(r"trig_[A-Za-z0-9]+", rid)
        if m:
            break
        say("  ✗ trig_로 시작하는 부분이 없어요. 브라우저 주소창의 주소를 통째로 복사해 주세요.")
    url = f"https://api.anthropic.com/v1/claude_code/routines/{m.group(0)}/fire"
    token = ask("  API 토큰(sk-ant-oat01-로 시작)을 붙여넣고 Enter (화면에 안 보이는 게 정상): ", secret=True)
    if not token.startswith("sk-ant-"):
        sys.exit("  토큰 모양이 달라요. 토큰을 다시 만들어(Regenerate) 복사해 주세요.")
    put_secrets({P + "ROUTINE_URL": url, P + "ROUTINE_TOKEN": token})
    say("  ✓ 연결 완료")
    st["routine_url"] = url
    save_state(st)


def step_webhook(st):
    title(6, "텔레그램 → 중계 서버 연결")
    r = tg(st["tg_token"], "setWebhook", url=f"{st['gateway_url']}/{BOT}/telegram",
           secret_token=st["webhook_secret"], allowed_updates=["message"], drop_pending_updates=True)
    if not r.get("ok"):
        sys.exit(f"  웹훅 연결 실패: {r}")
    say("  ✓ 연결 완료")
    http_json(f"{st['gateway_url']}/{BOT}/tg",
              {"text": "🎉 설치 끝! 이제 이 채팅에 /오늘뉴스 를 보내 보세요.\n(처음엔 클라우드 준비에 1~3분 걸려요)"},
              {"Authorization": f"Bearer {st['gateway_key']}"})
    say()
    say("  모든 설치가 끝났어요! 텔레그램에서 /오늘뉴스 를 보내 보세요.")
    say(f"  비밀값 기록 파일 {STATE_FILE.name} 은 다시 설치할 때 쓰니 지우지 말고, 남에게 보내지 마세요.")


def main():
    if "--reset" in sys.argv and STATE_FILE.exists():
        STATE_FILE.unlink()
    st = load_state()
    step_check()
    step_telegram(st)
    step_mail(st)
    step_cloudflare(st)
    step_values_file(st)
    step_routine(st)
    step_webhook(st)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\n  중단했어요. 다시 실행하면 이어서 해요.")
