"""解析器与本地向量的单元测试。"""

import pytest

from app.core.errors import ProcessingError
from app.processors import ocr
from app.processors.document_parser import detect_file_type, parse_document
from app.ai.local_embedding import LocalHashingEmbedding


def test_detect_file_type_maps_markdown():
    assert detect_file_type("笔记.MARKDOWN") == "md"
    assert detect_file_type("论文.pdf") == "pdf"
    with pytest.raises(Exception):
        detect_file_type("音频.mp3")


def test_parse_markdown_keeps_headings(tmp_path):
    file = tmp_path / "note.md"
    file.write_text("# 标题\n\n正文第一段。\n\n## 小节\n\n正文第二段。", encoding="utf-8")
    parsed = parse_document(file, "md")
    types = [block.block_type for block in parsed.pages[0].blocks]
    assert "title" in types
    assert parsed.pages[0].page_no == 1
    assert "正文第一段" in parsed.pages[0].content


def test_empty_text_file_raises(tmp_path):
    file = tmp_path / "empty.txt"
    file.write_text("\n\n   \n", encoding="utf-8")
    with pytest.raises(ProcessingError):
        parse_document(file, "txt")


def test_image_without_ocr_is_reported(tmp_path):
    if ocr.is_available():
        pytest.skip("已安装 PaddleOCR，跳过未安装场景")
    file = tmp_path / "x.png"
    file.write_bytes(b"not-a-real-image")
    with pytest.raises(Exception) as exc:
        parse_document(file, "png")
    assert "OCR" in str(exc.value)


@pytest.mark.asyncio
async def test_local_embedding_is_deterministic():
    provider = LocalHashingEmbedding(dim=128)
    first = await provider.embed_query("检索增强生成")
    second = await provider.embed_query("检索增强生成")
    other = await provider.embed_query("财务报表分析")
    assert len(first) == 128
    assert first == second
    assert first != other
