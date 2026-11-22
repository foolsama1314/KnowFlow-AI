"""文本清洗工具。"""

from __future__ import annotations

import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_PAGE_NUMBER_LINE = re.compile(r"^\s*(第?\s*\d{1,4}\s*页?|[-—]?\s*\d{1,4}\s*[-—]?|[ivxlcdm]{1,6})\s*$", re.I)
_MULTI_BLANK = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """统一空白与非法字符，去除连续空行。"""
    if not text:
        return ""
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = _CONTROL_CHARS.sub("", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return _MULTI_BLANK.sub("\n\n", text).strip()


def strip_page_number_lines(text: str) -> str:
    """去掉页首/页尾的纯页码行（常见于论文与扫描件）。"""
    lines = text.splitlines()
    while lines and (not lines[0].strip() or _PAGE_NUMBER_LINE.match(lines[0])):
        lines.pop(0)
    while lines and (not lines[-1].strip() or _PAGE_NUMBER_LINE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines)
