"""文档解析：把不同格式资料统一为 ParsedDocument（页面 + 版面块）。

输出结构是后续切块、检索、问答、图谱共用的数据底座。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import SUPPORTED_DOCUMENT_TYPES, SUPPORTED_IMAGE_TYPES
from app.core.errors import ProcessingError, UnsupportedFileError
from app.processors import ocr
from app.processors.cleaner import clean_text, strip_page_number_lines

logger = logging.getLogger(__name__)


@dataclass
class ParsedBlock:
    block_type: str
    content: str
    block_order: int
    bbox: list[float] | None = None
    confidence: float = 1.0


@dataclass
class ParsedPage:
    page_no: int
    content: str
    parse_method: str = "text"
    confidence: float = 1.0
    width: float | None = None
    height: float | None = None
    blocks: list[ParsedBlock] = field(default_factory=list)


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    warnings: list[str] = field(default_factory=list)

    @property
    def text_length(self) -> int:
        return sum(len(page.content) for page in self.pages)


def detect_file_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix == "markdown":
        suffix = "md"
    if suffix not in SUPPORTED_DOCUMENT_TYPES + SUPPORTED_IMAGE_TYPES:
        raise UnsupportedFileError(
            f"暂不支持 .{suffix or '未知'} 格式，当前支持："
            + "、".join(SUPPORTED_DOCUMENT_TYPES + SUPPORTED_IMAGE_TYPES)
        )
    return suffix


def parse_document(path: Path, file_type: str) -> ParsedDocument:
    if not path.exists():
        raise ProcessingError("原始文件不存在，可能已被移动或删除")

    if file_type == "pdf":
        result = _parse_pdf(path)
    elif file_type == "docx":
        result = _parse_docx(path)
    elif file_type in ("txt", "md", "markdown"):
        result = _parse_plain_text(path, file_type)
    elif file_type in SUPPORTED_IMAGE_TYPES:
        result = _parse_image(path)
    else:
        raise UnsupportedFileError(f"暂不支持 {file_type} 格式")

    if result.text_length == 0:
        raise ProcessingError(
            "未能从文件中提取到文本：可能是纯图片扫描件（需安装 PaddleOCR）、"
            "空文件或文件已损坏"
        )
    return result


# ---------------- PDF ----------------
def _parse_pdf(path: Path) -> ParsedDocument:
    import pymupdf

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ProcessingError(f"PDF 打开失败：{exc}") from exc

    warnings: list[str] = []
    pages: list[ParsedPage] = []
    try:
        if doc.needs_pass:
            raise ProcessingError("PDF 已加密，请先解除密码保护后再上传")
        if doc.page_count == 0:
            raise ProcessingError("PDF 没有可用页面")

        for index, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            text = strip_page_number_lines(clean_text(raw))
            width, height = float(page.rect.width), float(page.rect.height)

            if len(text.strip()) >= 10:
                blocks: list[ParsedBlock] = []
                order = 0
                for block in page.get_text("blocks"):
                    x0, y0, x1, y1, block_text, _no, block_kind = block[:7]
                    if block_kind != 0:
                        continue
                    content = strip_page_number_lines(clean_text(str(block_text)))
                    if not content:
                        continue
                    blocks.append(
                        ParsedBlock(
                            block_type="paragraph",
                            content=content,
                            block_order=order,
                            bbox=[round(float(x0), 1), round(float(y0), 1), round(float(x1), 1), round(float(y1), 1)],
                        )
                    )
                    order += 1
                if not blocks:
                    blocks = [ParsedBlock("paragraph", text, 0)]
                pages.append(
                    ParsedPage(
                        page_no=index,
                        content=text,
                        parse_method="text",
                        confidence=1.0,
                        width=width,
                        height=height,
                        blocks=blocks,
                    )
                )
                continue

            # 无文本层：尝试 OCR
            if ocr.is_available():
                pix = page.get_pixmap(dpi=200)
                result = ocr.ocr_image(pix.tobytes("png"))
                ocr_blocks = [
                    ParsedBlock(
                        block_type="paragraph",
                        content=line.text,
                        block_order=i,
                        bbox=line.bbox,
                        confidence=line.confidence,
                    )
                    for i, line in enumerate(result.lines)
                ]
                pages.append(
                    ParsedPage(
                        page_no=index,
                        content=clean_text(result.text),
                        parse_method="ocr",
                        confidence=result.confidence,
                        width=width,
                        height=height,
                        blocks=ocr_blocks,
                    )
                )
            else:
                warnings.append(f"第 {index} 页无文本层，未安装 PaddleOCR，已跳过")
                pages.append(
                    ParsedPage(
                        page_no=index,
                        content="",
                        parse_method="none",
                        confidence=0.0,
                        width=width,
                        height=height,
                        blocks=[],
                    )
                )
    finally:
        doc.close()

    if all(not page.content.strip() for page in pages):
        raise ProcessingError(
            "PDF 全部页面均无文本层。若为扫描件，请安装 PaddleOCR 后重试："
            "pip install paddleocr paddlepaddle"
        )
    return ParsedDocument(pages=pages, warnings=warnings)


# ---------------- DOCX ----------------
def _parse_docx(path: Path) -> ParsedDocument:
    from docx import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = DocxDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ProcessingError(f"DOCX 打开失败：{exc}") from exc

    blocks: list[ParsedBlock] = []
    order = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, doc)
            content = clean_text(paragraph.text)
            if not content:
                continue
            style_name = (paragraph.style.name or "").lower() if paragraph.style else ""
            block_type = "title" if ("heading" in style_name or "标题" in style_name) else "paragraph"
            blocks.append(ParsedBlock(block_type, content, order))
            order += 1
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            rows = [
                " | ".join(clean_text(cell.text) for cell in row.cells)
                for row in table.rows
            ]
            content = "\n".join(row for row in rows if row.strip())
            if content:
                blocks.append(ParsedBlock("table", content, order))
                order += 1

    full_text = "\n\n".join(block.content for block in blocks)
    page = ParsedPage(page_no=1, content=full_text, parse_method="text", blocks=blocks)
    return ParsedDocument(pages=[page])


# ---------------- TXT / Markdown ----------------
def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _parse_plain_text(path: Path, file_type: str) -> ParsedDocument:
    text = clean_text(_read_text_file(path))
    blocks: list[ParsedBlock] = []

    if file_type in ("md", "markdown"):
        order = 0
        buffer: list[str] = []
        in_code = False
        code_buffer: list[str] = []

        def flush_paragraph() -> None:
            nonlocal order, buffer
            paragraph = "\n".join(buffer).strip()
            if paragraph:
                blocks.append(ParsedBlock("paragraph", paragraph, order))
                order += 1
            buffer = []

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                if in_code:
                    code = "\n".join(code_buffer).strip()
                    if code:
                        blocks.append(ParsedBlock("code", code, order))
                        order += 1
                    code_buffer = []
                    in_code = False
                else:
                    flush_paragraph()
                    in_code = True
                continue
            if in_code:
                code_buffer.append(line)
                continue
            if stripped.startswith("#"):
                flush_paragraph()
                blocks.append(ParsedBlock("title", stripped.lstrip("#").strip(), order))
                order += 1
                continue
            if not stripped:
                flush_paragraph()
                continue
            buffer.append(stripped)
        if in_code and code_buffer:
            blocks.append(ParsedBlock("code", "\n".join(code_buffer), order))
        flush_paragraph()
    else:
        for order, paragraph in enumerate(p for p in text.split("\n\n") if p.strip()):
            blocks.append(ParsedBlock("paragraph", paragraph.strip(), order))

    full_text = "\n\n".join(block.content for block in blocks)
    page = ParsedPage(page_no=1, content=full_text, parse_method="text", blocks=blocks)
    return ParsedDocument(pages=[page])


# ---------------- 图片 ----------------
def _parse_image(path: Path) -> ParsedDocument:
    width = height = None
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = float(image.width), float(image.height)
    except Exception:  # noqa: BLE001
        logger.debug("读取图片尺寸失败，忽略", exc_info=True)

    result = ocr.ocr_image(path)
    blocks = [
        ParsedBlock(
            block_type="paragraph",
            content=line.text,
            block_order=index,
            bbox=line.bbox,
            confidence=line.confidence,
        )
        for index, line in enumerate(result.lines)
    ]
    page = ParsedPage(
        page_no=1,
        content=clean_text(result.text),
        parse_method="ocr",
        confidence=result.confidence,
        width=width,
        height=height,
        blocks=blocks,
    )
    return ParsedDocument(pages=[page])
