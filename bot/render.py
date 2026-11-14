"""초안 텍스트 → 메일 HTML. 네이버 블로그 등에 복사·붙여넣기 하기 좋게 단순한 태그만 쓴다."""
from __future__ import annotations

import html
import re


def parse_draft(text: str) -> dict:
    """`제목:` / `본문:` / `태그:` 형식을 나눈다. 형식이 깨졌으면 title이 빈 문자열."""
    text = (text or "").strip()
    m_title = re.search(r"^\s*제목\s*[:：]\s*(.+)$", text, re.M)
    m_body = re.search(r"^\s*본문\s*[:：]\s*\n?(.*?)(?=^\s*태그\s*[:：]|\Z)", text, re.M | re.S)
    m_tags = re.search(r"^\s*태그\s*[:：]\s*(.+)$", text, re.M)
    return {
        "title": m_title.group(1).strip() if m_title else "",
        "body": m_body.group(1).strip() if m_body else "",
        "tags": m_tags.group(1).strip() if m_tags else "",
    }


def body_len(body: str) -> int:
    """분량 = 본문 글자 수(공백 포함). 소제목 표시 `## `와 굵게 표시 `**`는 빼고 센다."""
    return len(re.sub(r"\*\*|^##\s*", "", body or "", flags=re.M))


def section_count(body: str) -> int:
    return len(re.findall(r"^##\s", body or "", re.M))


def _inline(s: str) -> str:
    s = html.escape(s)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def body_html(body: str) -> str:
    out = []
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if lines[0].startswith("## "):
            out.append(f'<h3 style="font-size:19px;margin:28px 0 10px;">{_inline(lines[0][3:].strip())}</h3>')
            lines = lines[1:]
        if lines:
            out.append('<p style="font-size:16px;line-height:1.8;margin:0 0 16px;">'
                       + "<br>".join(_inline(l) for l in lines) + "</p>")
    return "\n".join(out)


def draft_email(title: str, body: str, tags: str, facts: str) -> str:
    facts_html = html.escape(facts or "").replace("\n", "<br>")
    return f"""<div style="max-width:720px;font-family:sans-serif;color:#222;">
<p style="color:#888;font-size:13px;">아래 [제목]부터 [태그]까지 복사해서 블로그에 붙여넣으세요.</p>
<h2 style="font-size:24px;margin:8px 0 20px;">{html.escape(title)}</h2>
{body_html(body)}
<p style="color:#3b6;font-size:15px;margin-top:24px;">{html.escape(tags)}</p>
<hr style="margin:32px 0;border:none;border-top:1px solid #ddd;">
<p style="color:#888;font-size:13px;"><b>참고: 봇이 모은 뉴스 사실</b><br>{facts_html}</p>
</div>"""
