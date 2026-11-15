"""사용법 (클라우드의 Claude가 실행):
  python -m bot collect                   # 매일 자동 수집 (또는 /오늘뉴스)
  python -m bot handle --file work/inbox.txt  # 앱 세션 메시지 처리
  python -m bot continue                  # work/result.txt 를 받아 다음 단계로
  python -m bot fail "<사유>"              # 작업을 끝내지 못했을 때
  python -m bot sync "<설명>"              # 상태(state/)를 main에 커밋·푸시
  python -m bot reply                     # 쌓인 답을 출력하고 비움 (세션 답변으로 보여줌)
출력이 `TASK ...`면 work/task.md 를 수행하고 continue, `DONE: ...`이면 sync → reply 후 종료.
"""
import subprocess
import sys

from . import gateway, pipeline


def sync(msg: str) -> str:
    def git(*a):
        return subprocess.run(["git", *a], cwd=pipeline.ROOT, capture_output=True, text=True)

    git("add", "-A", "state")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return "SYNC: 변경 없음"
    git("-c", "user.name=cloud-news-bot", "-c", "user.email=bot@localhost", "commit", "-m", f"state: {msg}")
    for _ in range(3):
        git("pull", "--rebase", "origin", "main")
        if git("push", "origin", "HEAD:main").returncode == 0:
            # 세션 브랜치가 origin/main을 따라가게 해서 "푸시 안 된 커밋" 경고가 안 뜨게 한다
            git("fetch", "-q", "origin", "main")
            git("branch", "--set-upstream-to=origin/main")
            return "SYNC: main에 푸시함"
    return "SYNC 실패: 저장소 상태를 확인해 줘"


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, arg = argv[0], " ".join(argv[1:])
    if len(argv) == 3 and argv[1] == "--file":  # 따옴표·줄바꿈이 섞인 메시지는 파일로 받는다
        with open(argv[2], encoding="utf-8") as f:
            arg = f.read().strip()
    actions = {
        "collect": pipeline.collect,
        "handle": lambda: pipeline.handle(arg),
        "continue": pipeline.resume,
        "fail": lambda: pipeline.fail(arg or "알 수 없는 오류"),
        "sync": lambda: sync(arg or "update"),
        "reply": lambda: gateway.take_reply(),
    }
    print(actions.get(cmd, lambda: __doc__)())


if __name__ == "__main__":
    main(sys.argv[1:])
