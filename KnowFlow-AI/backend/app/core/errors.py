"""统一业务异常：API 层转换为结构化错误响应，避免把异常当成功返回。"""

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file"


class ProcessingError(AppError):
    status_code = 422
    code = "processing_failed"


class OCRUnavailableError(ProcessingError):
    code = "ocr_unavailable"


class AIProviderError(AppError):
    status_code = 502
    code = "ai_provider_error"


class TrainingInProgressError(ConflictError):
    code = "task_running"
