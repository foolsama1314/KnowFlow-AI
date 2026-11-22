"""切块策略：按版面块累积切块，保留页码来源，块间重叠固定长度。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])")


@dataclass
class ChunkData:
    content: str
    page_from: int | None
    page_to: int | None
    token_count: int


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """把超长段落按句子切分；仍超长的句子硬切并保留重叠。"""
    pieces: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_END.split(text):
        if not sentence:
            continue
        if len(sentence) > size:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            step = max(1, size - overlap)
            for start in range(0, len(sentence), step):
                pieces.append(sentence[start : start + size])
            continue
        if len(buffer) + len(sentence) > size and buffer:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer += sentence
    if buffer:
        pieces.append(buffer)
    return [p for p in pieces if p.strip()]


def build_chunks(
    units: list[tuple[str, int]],
    *,
    size: int = 800,
    overlap: int = 120,
) -> list[ChunkData]:
    """units 为 (文本, 页码) 序列，已按阅读顺序排列。"""
    chunks: list[ChunkData] = []
    buffer: list[str] = []
    buffer_len = 0
    pages: list[int] = []

    def flush(seed_overlap: bool) -> None:
        nonlocal buffer, buffer_len, pages
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(
                ChunkData(
                    content=text,
                    page_from=min(pages),
                    page_to=max(pages),
                    token_count=len(text),
                )
            )
            if seed_overlap and overlap > 0 and len(text) > overlap:
                tail = text[-overlap:]
                buffer = [tail]
                buffer_len = len(tail)
                pages = [pages[-1]]
                return
        buffer = []
        buffer_len = 0
        pages = []

    for text, page_no in units:
        text = text.strip()
        if not text:
            continue
        if len(text) > size:
            flush(seed_overlap=False)
            for piece in _split_long(text, size, overlap):
                chunks.append(
                    ChunkData(
                        content=piece.strip(),
                        page_from=page_no,
                        page_to=page_no,
                        token_count=len(piece.strip()),
                    )
                )
            continue
        if buffer_len + len(text) + 1 > size and buffer:
            flush(seed_overlap=True)
        buffer.append(text)
        buffer_len += len(text) + 1
        pages.append(page_no)

    flush(seed_overlap=False)
    return chunks
