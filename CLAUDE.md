# cloud-news-bot

Claude 앱 세션으로 대화하며 원하는 주제의 뉴스를 모으고, 내 의견을 담은 블로그 초안을 받는 봇 (메일은 선택).
Claude Code 클라우드 예약 작업에서 돈다 (PC를 꺼도 됨).

- 예약 작업으로 실행됐거나 그 세션에 주인이 답장했다면: **`prompts/ROUTINE.md`를 읽고 그대로 따른다.**
- 봇의 주제·말투·분량: `config.md` (사람이 고치는 파일)
- 코드: `bot/` (Python 표준 라이브러리만), 메일 중계 서버(선택): `gateway/` (Cloudflare Worker)
- 설치: `README.md`, 문제 해결: `docs/troubleshooting.md`
