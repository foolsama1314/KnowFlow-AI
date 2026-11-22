"""切块策略的单元测试。"""

from app.processors.chunker import build_chunks


def test_short_text_produces_single_chunk():
    chunks = build_chunks([("第一段内容", 1), ("第二段内容", 1)], size=800, overlap=120)
    assert len(chunks) == 1
    assert chunks[0].page_from == 1
    assert "第一段内容" in chunks[0].content
    assert chunks[0].token_count == len(chunks[0].content)


def test_long_text_is_split_and_keeps_pages():
    units = [(f"第{i}段" + "内容" * 120, i) for i in range(1, 6)]
    chunks = build_chunks(units, size=400, overlap=40)
    assert len(chunks) > 1
    assert all(chunk.page_from is not None for chunk in chunks)
    assert chunks[0].page_from == 1
    assert chunks[-1].page_to == 5


def test_overlap_creates_shared_text():
    units = [("甲" * 300, 1), ("乙" * 300, 1)]
    chunks = build_chunks(units, size=400, overlap=100)
    assert len(chunks) == 2
    tail = chunks[0].content[-100:]
    assert tail in chunks[1].content


def test_empty_units_are_ignored():
    assert build_chunks([("", 1), ("   ", 2)], size=400, overlap=40) == []
