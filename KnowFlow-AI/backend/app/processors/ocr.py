"""OCR 适配：惰性加载 PaddleOCR，未安装时给出明确可执行的错误，不产生假成功。"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import OCRUnavailableError

logger = logging.getLogger(__name__)


@dataclass
class OCRLine:
    text: str
    confidence: float
    bbox: list[float]


@dataclass
class OCRResult:
    text: str
    confidence: float
    lines: list[OCRLine] = field(default_factory=list)


_engine: Any = None


def is_available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


def _get_engine() -> Any:
    global _engine
    if _engine is not None:
        return _engine
    if not is_available():
        raise OCRUnavailableError(
            "未安装 PaddleOCR，无法识别扫描件或图片文字。"
            "请执行：pip install paddleocr paddlepaddle"
        )
    try:
        from paddleocr import PaddleOCR  # type: ignore

        _engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    except Exception as exc:  # noqa: BLE001
        raise OCRUnavailableError(f"PaddleOCR 初始化失败：{exc}") from exc
    return _engine


def ocr_image(source: str | Path | bytes) -> OCRResult:
    """识别单张图片，返回整页文本、平均置信度与逐行结果。"""
    engine = _get_engine()
    try:
        raw = engine.ocr(str(source) if isinstance(source, (str, Path)) else source, cls=True)
    except Exception as exc:  # noqa: BLE001
        raise OCRUnavailableError(f"OCR 识别失败：{exc}") from exc

    lines: list[OCRLine] = []
    # PaddleOCR 2.x 返回 [[ [box, (text, score)], ... ]]，3.x 结构不同，这里做宽松兼容
    for page in raw or []:
        if not page:
            continue
        for item in page:
            try:
                box, payload = item[0], item[1]
                text, score = payload[0], float(payload[1])
            except (IndexError, TypeError, ValueError):
                continue
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            lines.append(
                OCRLine(
                    text=str(text),
                    confidence=score,
                    bbox=[min(xs), min(ys), max(xs), max(ys)],
                )
            )

    if not lines:
        from app.core.errors import ProcessingError

        raise ProcessingError("未能从图片中识别出文字，请确认图片清晰度")

    text = "\n".join(line.text for line in lines)
    confidence = sum(line.confidence for line in lines) / len(lines)
    logger.info("OCR 完成：%d 行，平均置信度 %.3f", len(lines), confidence)
    return OCRResult(text=text, confidence=confidence, lines=lines)
