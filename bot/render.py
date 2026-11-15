"""메일 HTML 렌더링 — 초안 마커([요약표] [소제목] [사진N] [그래프] [수식] [표] [인용] [말풍선])를 서식 있는 HTML로.

네이버 블로그 에디터에 붙여넣었을 때 서식이 살아남는 방식으로 실측해서 맞춘 출력이라 **임의로 바꾸지 말 것.**
(원래 PowerShell로 운영하던 봇의 렌더러를 글자 하나까지 똑같이 옮긴 것)

주의: PowerShell의 -replace/-match/-split은 기본이 대소문자 무시라서, 그 의미를 살리려고
대부분의 정규식에 re.I를 건다. 그리스 문자 치환만 PS에서도 대소문자를 가렸으므로 re.I가 없다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

I = re.I


# ---------------------------------------------------------------- 기본 유틸

def esc(text) -> str:
    """Escape-TelegramHtml"""
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bold_to_html(text) -> str:
    """Convert-BoldMarkersToHtml"""
    if not text:
        return ""
    out = ""
    for part in re.split(r"(\*\*.+?\*\*|__.+?__)", text):
        m = re.match(r"^\*\*(.+)\*\*$", part, re.S)
        if m:
            out += f"<b>{esc(m.group(1))}</b>"
            continue
        m = re.match(r"^__(.+)__$", part, re.S)
        if m:
            out += f"<u>{esc(m.group(1))}</u>"
            continue
        out += esc(part)
    return out


# ---------------------------------------------------------------- 수식 평문화

_GREEK = [
    ("varepsilon", "ε"), ("epsilon", "ε"), ("Psi", "Ψ"), ("psi", "ψ"), ("Phi", "Φ"), ("phi", "φ"),
    ("Lambda", "Λ"), ("lambda", "λ"), ("mu", "μ"), ("Omega", "Ω"), ("omega", "ω"),
    ("Pi", "Π"), ("pi", "π"), ("Delta", "Δ"), ("delta", "δ"), ("Sigma", "Σ"), ("sigma", "σ"),
    ("tau", "τ"), ("Theta", "Θ"), ("theta", "θ"), ("alpha", "α"), ("beta", "β"), ("gamma", "γ"),
    ("times", "×"), ("cdot", "·"), ("approx", "≈"), ("propto", "∝"), ("ll", "≪"), ("gg", "≫"),
    ("leq", "≤"), ("geq", "≥"), ("neq", "≠"), ("pm", "±"), ("infty", "∞"),
]
_SUP = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷",
        "8": "⁸", "9": "⁹", "-": "⁻", "+": "⁺"}
_LETTER = "[A-Za-zα-ωΑ-Ω]"


def convert_math_line(text):
    """Convert-MathNotationLine"""
    if not text:
        return text
    t = text
    t = re.sub(r"\$\$([^$]*)\$\$", r"\1", t, flags=I)
    t = re.sub(r"\$([^$\n]{1,120})\$", r"\1", t, flags=I)
    t = re.sub(r"\\left|\\right|\\displaystyle|\\qquad|\\quad|\\,|\\;", " ", t, flags=I)
    t = re.sub(r"\\\[|\\\]|\\\(|\\\)", "", t, flags=I)
    for name, sym in _GREEK:  # 대소문자 구분 (PS도 [regex]::Replace로 구분)
        t = re.sub(r"\\" + name + r"(?![A-Za-z])", sym, t)
    t = re.sub(r"\\text\s*\{([^{}]*)\}", r"\1", t, flags=I)
    for _ in range(3):
        t = re.sub(_LETTER + r"_\{([A-Za-z0-9]+)\}", lambda m: m.group(0)[0] + m.group(1), t, flags=I)
    t = re.sub("(" + _LETTER + r")_([A-Za-z0-9]+)", r"\1\2", t, flags=I)
    for _ in range(3):
        t = re.sub(r"\\d?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2", t, flags=I)
        t = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", t, flags=I)
    t = re.sub(r"\^\s*\{?([-+]?\d+)\}?", lambda m: "".join(_SUP.get(c, c) for c in m.group(1)), t)
    t = re.sub("(" + _LETTER + r")_\{([A-Za-z0-9]+)\}", r"\1\2", t, flags=I)
    t = re.sub("(" + _LETTER + r")_([A-Za-z0-9]+)", r"\1\2", t, flags=I)
    t = re.sub(r"\\([A-Za-z]+)", r"\1", t, flags=I)
    t = re.sub(r"(?<![\[\]])[{}]", "", t, flags=I)
    t = re.sub(r"[ \t]{2,}", " ", t, flags=I)
    return t


def convert_math(text):
    """Convert-MathNotation — [수식] 줄은 LaTeX 원본 유지"""
    if not text:
        return text
    if re.search(r"(?m)^\s*\[수식\]", text, flags=I):
        out = []
        for line in re.split(r"\r?\n", text):
            out.append(line if re.match(r"^\s*\[수식\]", line, flags=I) else convert_math_line(line))
        return "\n".join(out)
    return convert_math_line(text)


# ---------------------------------------------------------------- 문장 분리

SPLIT_SENTENCES = True  # 2026-08-30부터 모든 모드 문장별 줄바꿈


def split_sentences(text) -> list[str]:
    """Split-Sentences — PS의 가변길이 lookbehind를 수동으로 구현"""
    t = re.sub(r"\s{2,}", " ", re.sub(r"\r?\n", " ", text or "")).strip()
    if not t:
        return []
    parts, start = [], 0
    for m in re.finditer(r"\s+", t):
        if re.search(r"[^0-9\s][.!?](?:\*\*|__)?$", t[:m.start()]):
            parts.append(t[start:m.start()])
            start = m.end()
    parts.append(t[start:])
    parts = [p.strip() for p in parts if p.strip()]
    merged, buf = [], ""
    for p in parts:
        buf = f"{buf} {p}" if buf else p
        if buf.count("**") % 2 == 0 and buf.count("__") % 2 == 0:
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)
    return merged


def split_sentences_to_lines(text) -> str:
    sentences = split_sentences(text)
    if not SPLIT_SENTENCES:
        return bold_to_html(" ".join(sentences))
    return "<br/>\n".join(bold_to_html(s) for s in sentences)


# ---------------------------------------------------------------- 이미지 추천

@dataclass
class ImageItem:
    number: int = 0
    label: str = ""
    prompt: str = ""
    style: str = ""
    ratio: str = ""
    source: str = ""
    credit: str = ""
    license: str = ""
    caption: str = ""


def parse_image_suggestions(text) -> list[ImageItem]:
    """Parse-ImageSuggestions"""
    items: list[ImageItem] = []
    if not text:
        return items
    for line in [l for l in re.split(r"\r?\n", text) if l.strip()]:
        m = re.match(r"^\s*(\d+)\.\s*(.+)$", line, flags=I)
        if not m:
            continue
        it = ImageItem(number=int(m.group(1)))
        for seg in m.group(2).split("|"):
            s = seg.strip()
            for pat, attr in ((r"^prompt\s*:\s*(.+)$", "prompt"), (r"^style\s*:\s*(.+)$", "style"),
                              (r"^ratio\s*:\s*(.+)$", "ratio")):
                mm = re.match(pat, s, flags=I)
                if mm:
                    setattr(it, attr, mm.group(1).strip())
                    break
            else:
                for pat, attr in ((r"^(source|url|link|출처링크)\s*:\s*(.+)$", "source"),
                                  (r"^(credit|author|저작자)\s*:\s*(.+)$", "credit"),
                                  (r"^(license|라이선스)\s*:\s*(.+)$", "license"),
                                  (r"^(caption|출처표기)\s*:\s*(.+)$", "caption")):
                    mm = re.match(pat, s, flags=I)
                    if mm:
                        setattr(it, attr, mm.group(2).strip())
                        break
                else:
                    if re.match(r"^keyword\s*:\s*(.+)$", s, flags=I):
                        pass  # 구버전 스톡 키워드는 버림
                    elif not it.label:
                        it.label = s
        if not it.label:
            it.label = f"사진{it.number}"
        if it.source and not re.match(r"^https?://", it.source, flags=I):
            it.source = ""  # 지어낸 설명문일 가능성
        if it.source and not it.caption:
            cp = [x for x in (it.credit, it.license) if x]
            it.caption = ("사진: " + " / ".join(cp)) if cp else f"사진 출처: {it.source}"
        items.append(it)
    return items


def format_image_suggestion_text(item: ImageItem, idx: int) -> str:
    num = item.number or idx
    text = f"[사진{num}] {item.label}"
    if item.source:
        text += f"\n실제 사진: {item.source}"
        meta = ([f"저작자: {item.credit}"] if item.credit else []) + ([f"라이선스: {item.license}"] if item.license else [])
        if meta:
            text += "\n" + " / ".join(meta)
        if item.caption:
            text += f"\n사진 아래 붙일 출처: {item.caption}"
        return text
    if item.prompt:
        text += f"\n(실제 사진 못 찾음 - AI로 생성)\n프롬프트: {item.prompt}"
    meta = ([f"스타일: {item.style}"] if item.style else []) + ([f"비율: {item.ratio}"] if item.ratio else [])
    if meta:
        text += "\n" + " / ".join(meta)
    return text


def image_suggestions_message(items: list[ImageItem]) -> str | None:
    """사진 추천 목록 (세션 답변용)"""
    if not items:
        return None
    blocks = [format_image_suggestion_text(it, i + 1) for i, it in enumerate(items)]
    return ("[이미지 추천]\n링크가 있는 자리는 그 페이지에서 사진을 받아 넣고, 사진 바로 아래에 출처 표기를 붙여줘.\n"
            "링크 없이 프롬프트만 있는 자리는 그 프롬프트를 제미나이(gemini.google.com)에 그대로 넣어서 만들면 돼.\n\n"
            + "\n\n".join(blocks))


# ---------------------------------------------------------------- 텍스트 정리

def remove_trailing_hashtag_lines(text):
    if not text:
        return text
    lines = re.split(r"\r?\n", text)
    end = len(lines) - 1
    while end >= 0:
        last = lines[end].strip()
        if last == "" or re.match(r"^#\S+(\s+#\S+)*$", last, flags=I):
            end -= 1
        else:
            break
    return "" if end < 0 else "\n".join(lines[: end + 1])


def parse_summary_table(text) -> list[tuple[str, str]]:
    rows = []
    if not text:
        return rows
    for line in [l for l in re.split(r"\r?\n", text) if l.strip()]:
        m = re.match(r"^\s*(.+?)\s*\|\s*(.+?)\s*$", line, flags=I)
        if m:
            rows.append((m.group(1).strip(), m.group(2).strip()))
    return rows


def format_markers_for_preview(text):
    """Format-MarkersForPreview — 세션 답변 미리보기용"""
    if not text:
        return text
    t = re.sub(r"(?m)^[ \t]*\[소제목\][ \t]*(.+?)[ \t]*$", r"━━ **\1** ━━", text, flags=I)
    t = re.sub(r"(?m)^[ \t]*\[인용\][ \t]*(.+?)[ \t]*$", r"“ **\1** ”", t, flags=I)
    t = re.sub(r"(?m)^[ \t]*\[(말풍선|포스트잇)\][ \t]*(.+?)[ \t]*$", r"[말풍선] \2", t, flags=I)
    t = re.sub(r"(?m)^[ \t]*\[수식\][ \t]*(.+?)[ \t]*$", r"[수식 자리] \1", t, flags=I)
    t = re.sub(r"(?m)^[ \t]*\[그래프\][ \t]*(.+?)[ \t]*$", r"[그래프 자리] \1", t, flags=I)
    t = re.sub(r"(\r?\n){3,}", "\n\n", re.sub(r"[ \t]*\[사진(\d+)\][ \t]*", r"\n\n[사진\1 자리]\n\n", t, flags=I), flags=I)
    out = []
    for line in re.split(r"\r?\n", t):
        trim = line.strip()
        if (trim == "" or re.match(r"^(\[표\]|━━|“|\[말풍선\]|\[포스트잇|\[수식|\[그래프|\*\*|-\s|\[사진)", trim, flags=I)
                or "|" in trim):
            out.append(line)
            continue
        out.append("\n".join(split_sentences(line)) if SPLIT_SENTENCES else line)
    return "\n".join(out)


# ---------------------------------------------------------------- HTML 블록

PARA_STYLE = "margin:0;line-height:1.9;text-align:center;"


def spacer() -> str:
    return f"<p style='{PARA_STYLE}'>&nbsp;</p>\n"


def centered_box(inner: str, box_style: str) -> str:
    return f"<div style='text-align:center;margin:0;'><div style='display:inline-block;max-width:92%;{box_style}'>{inner}</div></div>\n"


def naver_quote(inner: str, variant: str, block_style: str) -> str:
    cls = f"se-l-quotation_{variant}"
    return (f"<div class='se-component se-quotation {cls}' style='margin:0;'>"
            "<div class='se-component-content'>"
            f"<div class='se-section se-section-quotation {cls}'>"
            f"<blockquote class='se-quotation-container' style='margin:0;{block_style}'>"
            f"<div class='se-module se-module-text se-quote'>{inner}</div>"
            "</blockquote></div></div></div>\n")


def image_block(item: ImageItem | None, idx: int) -> str:
    num = item.number if (item and item.number) else idx
    lbl = esc(item.label) if (item and item.label) else "이 자리에 어울리는 이미지"
    if item and item.source:
        src = esc(item.source)
        h = "<div style='margin:20px 0;padding:14px 16px;border:2px dashed #2f6fdb;border-radius:6px;background:#f5f9ff;text-align:left;'>\n"
        h += f"<div style='font-size:13px;font-weight:bold;color:#2f6fdb;margin-bottom:6px;'>[사진{num}] 이 자리에 아래 실제 사진 넣기</div>\n"
        h += f"<div style='font-size:14px;color:#333;margin-bottom:10px;'>{lbl}</div>\n"
        h += f"<div style='font-size:13px;line-height:1.6;word-break:break-all;'><a href='{src}' style='color:#2f6fdb;'>{src}</a></div>\n"
        meta = ([f"저작자: {item.credit}"] if item.credit else []) + ([f"라이선스: {item.license}"] if item.license else [])
        if meta:
            h += f"<div style='font-size:12px;color:#666;margin-top:8px;'>{esc(' / '.join(meta))}</div>\n"
        if item.caption:
            h += "<div style='font-size:12px;color:#888;margin-top:8px;margin-bottom:4px;'>사진 바로 아래에 이 한 줄을 그대로 넣어줘 (출처 표기)</div>\n"
            h += f"<div style='font-size:13px;color:#111;background:#fff;border:1px solid #ddd;border-radius:4px;padding:8px 10px;'>{esc(item.caption)}</div>\n"
        h += "</div>\n"
        return h + spacer()
    h = "<div style='margin:20px 0;padding:14px 16px;border:2px dashed #03c75a;border-radius:6px;background:#f7fdf9;text-align:left;'>\n"
    h += f"<div style='font-size:13px;font-weight:bold;color:#03c75a;margin-bottom:6px;'>[사진{num}] 이 자리에 AI 이미지 넣기 (쓸 만한 실제 사진을 못 찾은 자리)</div>\n"
    h += f"<div style='font-size:14px;color:#333;margin-bottom:10px;'>{lbl}</div>\n"
    if item and item.prompt:
        h += "<div style='font-size:12px;color:#888;margin-bottom:4px;'>아래 프롬프트를 제미나이(gemini.google.com)에 그대로 복사해서 넣으면 됨</div>\n"
        h += f"<div style='font-family:Consolas,monospace;font-size:13px;line-height:1.6;color:#111;background:#fff;border:1px solid #ddd;border-radius:4px;padding:10px;'>{esc(item.prompt)}</div>\n"
    meta = []
    if item and item.style:
        meta.append(f"스타일: {item.style}")
    if item and item.ratio:
        meta.append(f"비율: {item.ratio}")
    if meta:
        h += f"<div style='font-size:12px;color:#666;margin-top:8px;'>{esc(' / '.join(meta))}</div>\n"
    h += "</div>\n"
    return h + spacer()


def inline_table(para: str) -> str:
    body = re.sub(r"\s*\[/표\]\s*$", "", re.sub(r"^\s*\[표\]\s*", "", para, flags=I), flags=I)
    rows = []
    for line in [l for l in re.split(r"\r?\n", body) if l.strip()]:
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 2:
            rows.append(cells)
    if not rows:
        return ""
    h = "<table style='border-collapse:collapse;width:100%;margin:0 auto;font-size:15px;'>\n<tr>"
    for c in rows[0]:
        h += f"<th style='background:#03c75a;color:#fff;border:1px solid #03c75a;padding:8px 10px;text-align:center;'>{esc(c)}</th>"
    h += "</tr>\n"
    for i in range(1, len(rows)):
        shade = "background:#f7fdf9;" if i % 2 == 0 else ""
        h += "<tr>"
        for c in rows[i]:
            h += f"<td style='border:1px solid #ddd;padding:8px 10px;text-align:center;{shade}'>{bold_to_html(c)}</td>"
        h += "</tr>\n"
    return h + "</table>\n"


def bullet_list(para: str) -> str:
    h = "<ul style='margin:0;padding-left:20px;line-height:1.9;text-align:left;'>\n"
    for line in [l for l in re.split(r"\r?\n", para) if l.strip()]:
        item = re.sub(r"^\s*-\s*", "", line, flags=I)
        h += f"<li style='margin:0 0 8px 0;'>{bold_to_html(item)}</li>\n"
    h += "</ul>"
    return centered_box(h, "text-align:left;")


def heading(text: str) -> str:
    t = re.sub(r"^\s*\[소제목\]\s*", "", text, flags=I).strip()
    if not t:
        return ""
    style = "margin:0;border-left:4px solid #222;padding:6px 0 6px 16px;"
    style += "font-size:19px;font-weight:bold;color:#111;line-height:1.6;text-align:left;"
    return spacer() + f"<p style='{style}'>{bold_to_html(t)}</p>\n" + spacer()


def quote(text: str) -> str:
    t = re.sub(r"^\s*\[인용\]\s*", "", text, flags=I).strip()
    if not t:
        return ""
    inner = "<p class='se-text-paragraph se-text-paragraph-align-center' style='margin:0;font-size:18px;font-weight:bold;color:#111;line-height:1.8;text-align:center;'>"
    inner += (f"<span style='color:#03c75a;font-size:26px;font-weight:bold;'>&#8220;</span> {bold_to_html(t)} "
              "<span style='color:#03c75a;font-size:26px;font-weight:bold;'>&#8221;</span></p>")
    return spacer() + naver_quote(inner, "quote", "border:0;padding:8px 0;text-align:center;") + spacer()


def formula(text: str) -> str:
    latex = re.sub(r"^\s*\[수식\]\s*", "", text, flags=I).strip()
    if not latex:
        return ""
    plain = convert_math_line(latex)
    h = "<div style='margin:0;padding:14px 16px;border:2px dashed #4a7fd4;border-radius:6px;background:#f5f8fd;text-align:center;'>\n"
    h += "<div style='font-size:13px;font-weight:bold;color:#4a7fd4;margin-bottom:8px;'>[수식] 이 자리에 수식 넣기</div>\n"
    h += f"<div style='font-size:18px;color:#111;margin-bottom:10px;'>{esc(plain)}</div>\n"
    h += "<div style='font-size:12px;color:#888;margin-bottom:4px;'>아래 LaTeX을 복사해서 수식 편집기에 넣거나, 렌더러로 이미지를 만들어 이 자리에 넣어줘</div>\n"
    h += f"<div style='font-family:Consolas,monospace;font-size:13px;line-height:1.6;color:#111;background:#fff;border:1px solid #ddd;border-radius:4px;padding:10px;text-align:left;'>{esc(latex)}</div>\n"
    h += "</div>\n"
    return spacer() + h + spacer()


def graph(text: str) -> str:
    spec = re.sub(r"^\s*\[그래프\]\s*", "", text, flags=I).strip()
    if not spec:
        return ""
    parts = [p.strip() for p in spec.split("|")]
    title = parts[0]
    x_axis = parts[1] if len(parts) >= 2 else ""
    y_axis = parts[2] if len(parts) >= 3 else ""
    desc = " | ".join(parts[3:]) if len(parts) >= 4 else ""
    h = "<div style='margin:0;padding:14px 16px;border:2px dashed #d48a4a;border-radius:6px;background:#fdf9f5;text-align:left;'>\n"
    h += "<div style='font-size:13px;font-weight:bold;color:#d48a4a;margin-bottom:8px;text-align:center;'>[그래프] 이 자리에 그래프 넣기</div>\n"
    h += f"<div style='font-size:16px;font-weight:bold;color:#111;margin-bottom:10px;text-align:center;'>{esc(title)}</div>\n"
    if x_axis:
        h += f"<div style='font-size:14px;color:#333;margin:4px 0;'><b>가로축</b> {esc(x_axis)}</div>\n"
    if y_axis:
        h += f"<div style='font-size:14px;color:#333;margin:4px 0;'><b>세로축</b> {esc(y_axis)}</div>\n"
    if desc:
        h += f"<div style='font-size:14px;color:#333;margin:8px 0 0 0;line-height:1.7;'><b>그릴 내용</b> {esc(desc)}</div>\n"
    h += "<div style='font-size:12px;color:#888;margin-top:10px;'>직접 그리거나 검색해서 이 자리에 넣고 이 박스는 지우면 돼</div>\n"
    h += "</div>\n"
    return spacer() + h + spacer()


def bubble(text: str) -> str:
    t = re.sub(r"^\s*\[(말풍선|포스트잇)\]\s*", "", text, flags=I).strip()
    if not t:
        return ""
    return spacer() + f"<p style='{PARA_STYLE}'>{split_sentences_to_lines(t)}</p>\n" + spacer()


def text_paragraph(para: str, images: list[ImageItem]) -> str:
    matches = list(re.finditer(r"\[사진(\d+)\]", para, flags=I))
    if not matches:
        return f"<p style='{PARA_STYLE}'>{split_sentences_to_lines(para)}</p>\n" + spacer()
    h, last = "", 0
    for m in matches:
        before = para[last:m.start()].strip()
        if before:
            h += f"<p style='{PARA_STYLE}'>{split_sentences_to_lines(before)}</p>\n" + spacer()
        idx = int(m.group(1))
        item = images[idx - 1] if (images and len(images) >= idx) else None
        h += image_block(item, idx)
        last = m.end()
    remain = para[last:].strip()
    if remain:
        h += f"<p style='{PARA_STYLE}'>{split_sentences_to_lines(remain)}</p>\n" + spacer()
    return h


def _block(lines: list[str], kind: str, images) -> str:
    text = "\n".join(lines)
    return {
        "heading": lambda: heading(text),
        "formula": lambda: formula(text),
        "graph": lambda: graph(text),
        "quote": lambda: quote(text),
        "bubble": lambda: bubble(text),
        "postit": lambda: bubble(text),  # 포스트잇 폐기 → 말풍선
        "bullet": lambda: bullet_list(text) + spacer(),
    }.get(kind, lambda: text_paragraph(text, images))()


_KINDS = [(r"^\[소제목\]", "heading"), (r"^\[수식\]", "formula"), (r"^\[그래프\]", "graph"),
          (r"^\[인용\]", "quote"), (r"^\[말풍선\]", "bubble"), (r"^\[포스트잇\]", "postit"), (r"^-\s", "bullet")]


def paragraph(para: str, images) -> str:
    para = para.strip()
    if not para:
        return ""
    if re.match(r"^\[표\]", para, flags=I):
        return inline_table(para) + spacer()
    lines = [l for l in re.split(r"\r?\n", para) if l.strip()]
    h, buf, buf_kind = "", [], ""
    for line in lines:
        kind = next((k for pat, k in _KINDS if re.match(pat, line.strip(), flags=I)), "text")
        if buf and (kind != buf_kind or kind not in ("text", "bullet")):
            h += _block(buf, buf_kind, images)
            buf = []
        buf_kind = kind
        buf.append(line)
    if buf:
        h += _block(buf, buf_kind, images)
    return h


def email_body(body: str, images: list[ImageItem]) -> str:
    paragraphs = [p for p in re.split(r"\r?\n\r?\n", body) if p.strip()]
    has_markers = re.search(r"\[사진\d+\]", body, flags=I) is not None
    if not has_markers and images and len(paragraphs) > 1:
        n = len(images)
        step = max(1, math.floor(len(paragraphs) / (n + 1)))
        h, img_idx = "", 0
        for p in range(len(paragraphs)):
            h += paragraph(paragraphs[p], images)
            if img_idx < n and ((p + 1) % step == 0) and p < len(paragraphs) - 1:
                h += image_block(images[img_idx], img_idx + 1)
                img_idx += 1
        while img_idx < n:
            h += image_block(images[img_idx], img_idx + 1)
            img_idx += 1
        return h
    return "".join(paragraph(p, images) for p in paragraphs)


def hashtags_html(tags: list[str]) -> str:
    if not tags:
        return ""
    return f"<p style='margin-top:28px;color:#03c75a;font-size:15px;font-weight:bold;text-align:center;'>{' '.join(esc(t) for t in tags)}</p>\n"


def image_prompt_list(items: list[ImageItem]) -> str:
    if not items:
        return ""
    h = "<div style='margin-top:28px;padding:16px;background:#fafafa;border:1px solid #e5e5e5;border-radius:6px;text-align:left;'>\n"
    h += "<div style='font-size:14px;font-weight:bold;color:#333;margin-bottom:4px;'>이미지 모아보기 (실제 사진 링크 + AI 프롬프트)</div>\n"
    h += "<div style='font-size:12px;color:#888;margin-bottom:12px;'>파란 줄은 그 링크에서 사진을 받아 쓰고 출처 한 줄을 사진 아래에 붙이면 되고, 회색 프롬프트 줄은 제미나이(gemini.google.com)에 그대로 붙여넣으면 돼 (이 블록 자체는 블로그 본문에 붙여넣지 말 것)</div>\n"
    for i, it in enumerate(items):
        num = it.number or (i + 1)
        if it.source:
            src = esc(it.source)
            meta = ([f"저작자: {it.credit}"] if it.credit else []) + ([f"라이선스: {it.license}"] if it.license else [])
            meta_text = (" (" + " / ".join(meta) + ")") if meta else ""
            h += (f"<div style='margin:10px 0;font-size:13px;line-height:1.6;word-break:break-all;'><b>사진{num}</b> "
                  f"{esc(it.label)}{esc(meta_text)}<br/><a href='{src}' style='color:#2f6fdb;'>{src}</a>")
            if it.caption:
                h += f"<br/><span style='color:#666;'>출처 표기: {esc(it.caption)}</span>"
            h += "</div>\n"
            continue
        meta = ([f"스타일: {it.style}"] if it.style else []) + ([f"비율: {it.ratio}"] if it.ratio else [])
        meta_text = (" (" + " / ".join(meta) + ")") if meta else ""
        h += (f"<div style='margin:10px 0;font-size:13px;line-height:1.6;'><b>사진{num}</b> {esc(it.label)}{esc(meta_text)}"
              f"<br/><span style='font-family:Consolas,monospace;color:#111;'>{esc(it.prompt)}</span></div>\n")
    return h + "</div>\n"


_FOOTER = ("<p style=\"color:#999;font-size:12px;margin-top:32px;border-top:1px solid #eee;padding-top:12px;text-align:left;\">"
           "이 본문 전체를 선택해서 복사한 뒤 네이버 블로그 에디터에 붙여넣어줘. 표/굵게/밑줄/해시태그 서식이 그대로 유지돼 "
           "(단, PC에서 복사할 것 — 모바일에서는 표가 깨짐). 점선 박스는 사진 자리표시자니까, 사진을 그 자리에 넣고 박스는 지우면 돼 — "
           "<b>파란 박스</b>는 링크에 있는 실제 사진을 받아서 넣고 <b>사진 바로 아래에 출처 한 줄</b>까지 같이 넣는 자리, "
           "<b>초록 박스</b>는 실제 사진을 못 찾아서 프롬프트로 이미지를 만들어 넣는 자리야 — 프롬프트를 제미나이(gemini.google.com)에 붙여넣으면 무료로 그려줘.<br/><b>붙여넣은 뒤 할 일 하나</b>: "
           "해시태그 바로 위 <b>맨 마지막 문단</b>(오늘 글을 닫는 내 의견)을 선택해서 <b>인용구 → 말풍선</b>으로 바꿔줘. "
           "붙여넣기로는 인용구 종류를 지정할 수가 없어서 이 두 클릭만 수동이야.</p>")


def draft_email(title: str, summary_rows: list[tuple[str, str]], body_html: str,
                tags: list[str], images: list[ImageItem]) -> str:
    """Build-DraftEmailHtml"""
    table = ""
    if summary_rows:
        table = "<table style='border-collapse:collapse;width:100%;margin:0 auto;'>\n"
        table += ("<tr><th style='background:#f2f2f2;border:1px solid #ddd;padding:8px 10px;text-align:center;width:32%;'>이슈</th>"
                  "<th style='background:#f2f2f2;border:1px solid #ddd;padding:8px 10px;text-align:center;'>핵심 포인트</th></tr>\n")
        for item, content in summary_rows:
            table += (f"<tr><td style='border:1px solid #ddd;padding:8px 10px;text-align:center;'>{esc(item)}</td>"
                      f"<td style='border:1px solid #ddd;padding:8px 10px;text-align:center;'>{esc(content)}</td></tr>\n")
        table += "</table>\n" + spacer()
    return ("<html><body style=\"font-family:'Malgun Gothic',-apple-system,sans-serif;font-size:16px;line-height:1.9;"
            "color:#222;max-width:640px;margin:0 auto;padding:16px;text-align:center;\">\n"
            f"<h1 style=\"font-size:22px;margin:0;line-height:1.5;text-align:center;\">{esc(title)}</h1>\n"
            "<p style=\"margin:0;line-height:1.9;\">&nbsp;</p>\n"
            f"{table}\n{body_html}\n{hashtags_html(tags)}\n{_FOOTER}\n{image_prompt_list(images)}\n</body></html>")
