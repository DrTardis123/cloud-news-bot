"""cloud-news-bot 메일 설정 도우미 — 초안을 메일로 받고 싶을 때만 (선택).

메일 없이도 봇은 돌아간다 (초안이 Claude 앱 세션 답변으로 온다).
표·사진 박스까지 서식을 살린 메일로 받고 싶을 때 이 스크립트를 한 번 돌린다.

실행:  python setup/setup.py
  - 중간에 멈춰도 다시 실행하면 끝난 단계는 건너뛴다 (기록: setup/.local.json)
  - 처음부터 다시: python setup/setup.py --reset

하는 일
  1. 메일(네이버/Gmail) 로그인 시험
  2. Cloudflare에 메일 중계 서버 배포 + 비밀값 넣기 + 시험 메일 발송
  3. claude.ai 클라우드 환경에 넣을 값을 파일로 정리 (복사용)
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


def step_mail(st):
    title(1, "메일 설정 (초안을 받을 메일)")
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
    title(2, "Cloudflare에 메일 중계 서버 올리기")
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
    say("  비밀값 넣는 중...")
    put_secrets({
        P + "GATEWAY_KEY": st["gateway_key"],
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
    r = http_json(f"{url}/{BOT}/mail",
                  {"subject": "🔧 뉴스봇 메일 연결 확인", "html": "<p>이 메일이 보이면 메일 설정 성공이에요.</p>"},
                  {"Authorization": f"Bearer {st['gateway_key']}"})
    if not r.get("ok"):
        sys.exit(f"  시험 메일 발송 실패: {r}")
    say(f"  ✓ {st['mail_user']} 으로 시험 메일을 보냈어요")
    st["gateway_url"] = url
    save_state(st)


def step_values_file(st):
    title(3, "claude.ai에 넣을 값 정리")
    host = st["gateway_url"].replace("https://", "")
    VALUES_FILE.write_text(
        "claude.ai 클라우드 환경에 넣을 값 (README '메일로 받기' 4~5번)\n"
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


def main():
    if "--reset" in sys.argv and STATE_FILE.exists():
        STATE_FILE.unlink()
    st = load_state()
    step_check()
    step_mail(st)
    step_cloudflare(st)
    step_values_file(st)
    say()
    say("  메일 설정 끝! README '메일로 받기' 4~5번대로 claude.ai 환경에 값을 넣으면 다음 초안부터 메일로 와요.")
    say(f"  비밀값 기록 파일 {STATE_FILE.name} 은 다시 설치할 때 쓰니 지우지 말고, 남에게 보내지 마세요.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\n  중단했어요. 다시 실행하면 이어서 해요.")
