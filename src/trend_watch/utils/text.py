import re

_MULTI_SPACE = re.compile(r"\s{2,}")
_HTML_TAGS = re.compile(r"<[^>]+>")

_BOILERPLATE_LINE_RE = re.compile(
    "|".join([
        r"※ 發信站:",
        r"※ 文章網址:",
        r"※ 編輯:",
        r"※ 轉錄者:",
        r"※ 引述《",
        r"\(本文已被刪除\)",
        r"（本文已被刪除）",
        r"文章已被刪除",
    ])
)

_BOILERPLATE_INLINE_RE = re.compile(
    r"Sent from \S+PTT[^\n]*"
    r"|Sent from MindyCute[^\n]*"
    r"|Sent from .{0,20}iPhone[^\n]*"
)


def strip_boilerplate(text: str) -> str:
    text = _BOILERPLATE_INLINE_RE.sub("", text)
    lines = text.splitlines()
    clean = [ln for ln in lines if not _BOILERPLATE_LINE_RE.search(ln)]
    return "\n".join(clean).strip()


def clean_text(text: str) -> str:
    text = _HTML_TAGS.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()
