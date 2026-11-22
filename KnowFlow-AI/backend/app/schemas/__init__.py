"""Pydantic 请求与响应模型，统一 API 数据格式。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 系统 ----------
class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    database: bool
    qdrant: bool


class VectorIndexStatusOut(BaseModel):
    provider: str
    model: str
    dimension: int
    status: str
    chunk_count: int
    error: str | None = None
    updated_at: datetime


class SystemInfoOut(BaseModel):
    app_name: str
    version: str
    api_prefix: str
    data_dir: str
    data_dir_custom: bool
    database: str
    qdrant_mode: str
    qdrant_collection: str
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    embedding_degraded: bool
    retrieval_mode: str
    index_status: VectorIndexStatusOut
    llm_configured: bool
    ocr_available: bool
    supported_extensions: list[str]
    python_version: str


class StorageLocationOut(BaseModel):
    data_dir: str
    default_data_dir: str
    custom: bool
    exists: bool
    restart_required: bool = False
    message: str = ""


class StorageLocationUpdate(BaseModel):
    data_dir: str
    migrate: bool = True


class StatsOut(BaseModel):
    document_count: int
    chunk_count: int
    storage_bytes: int
    task_running: int
    task_failed: int
    by_file_type: dict[str, int]
    by_status: dict[str, int]


# ---------- 文档 ----------
class DocumentOut(ORMModel):
    id: str
    name: str
    original_name: str
    file_type: str
    file_size: int
    status: str
    page_count: int
    chunk_count: int
    summary: str | None = None
    index_status: str = "unknown"
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class IndexSummaryOut(BaseModel):
    total_documents: int
    completed_documents: int
    failed_documents: int
    pending_index: int
    total_chunks: int
    indexed_chunks: int
    index_status: VectorIndexStatusOut
    running_tasks: int


class ReindexProgressOut(BaseModel):
    running: bool
    processed: int
    total: int
    stage: str
    error: str | None = None
    finished_at: datetime | None = None


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class BlockOut(ORMModel):
    id: str
    block_type: str
    block_order: int
    content: str
    bbox: list[float] | None = None
    confidence: float


class PageOut(ORMModel):
    id: str
    page_no: int
    width: float | None = None
    height: float | None = None
    content: str
    parse_method: str
    confidence: float
    blocks: list[BlockOut] = Field(default_factory=list)


class DocumentContentOut(BaseModel):
    document: DocumentOut
    pages: list[PageOut]


class UploadItem(BaseModel):
    document_id: str
    task_id: str
    name: str


class BatchUploadOut(BaseModel):
    succeeded: list[UploadItem]
    failed: list[dict[str, str]]


# ---------- 任务 ----------
class TaskOut(ORMModel):
    id: str
    document_id: str
    task_type: str
    status: str
    progress: int
    current_step: str
    error_message: str | None = None
    retry_count: int
    document_name: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class TaskListOut(BaseModel):
    items: list[TaskOut]
    total: int


# ---------- 检索 ----------
class SearchFilters(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    file_types: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=50)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    file_type: str
    page_from: int | None = None
    page_to: int | None = None
    content: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]
    took_ms: int
    retrieval_mode: str
    embedding_model: str
    index_status: VectorIndexStatusOut


class SearchHistoryItem(BaseModel):
    query: str
    top_k: int
    result_count: int
    at: datetime


# ---------- 智能问答 ----------
class CitationOut(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    file_type: str
    page_from: int | None = None
    page_to: int | None = None
    snippet: str
    score: float
    cited: bool = False


class ChatMessageOut(ORMModel):
    id: str
    session_id: str
    role: str
    content: str
    citations: list[CitationOut] | None = None
    created_at: datetime


class ChatSessionOut(ORMModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSessionListOut(BaseModel):
    items: list[ChatSessionOut]
    total: int
    page: int
    page_size: int


class ChatSessionCreateRequest(BaseModel):
    title: str = Field(default="新会话", max_length=255)


class ChatSessionDetailOut(BaseModel):
    session: ChatSessionOut
    messages: list[ChatMessageOut]


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    stream: bool = True


class ChatAnswerOut(BaseModel):
    message: ChatMessageOut
    citations: list[CitationOut]
    retrieval_count: int
    context_truncated: bool
    refusal: bool
    took_ms: int


# ---------- 设置 ----------
class ModelSettingsOut(BaseModel):
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_has_key: bool
    llm_configured: bool
    embedding_provider: str
    embedding_base_url: str
    embedding_model: str
    embedding_dim: int
    embedding_has_key: bool
    embedding_configured: bool
    embedding_degraded: bool


class ModelSettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    embedding_provider: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_dim: int | None = Field(default=None, ge=64, le=8192)


class ProcessingSettings(BaseModel):
    chunk_size: int = Field(ge=200, le=4000)
    chunk_overlap: int = Field(ge=0, le=1000)
    default_top_k: int = Field(ge=1, le=50)
    max_upload_mb: int = Field(ge=1, le=2048)


class RagSettings(BaseModel):
    rag_top_k: int = Field(ge=1, le=20)
    rag_min_score: float = Field(ge=0, le=1)
    rag_context_chars: int = Field(ge=1000, le=30000)


class SettingsOut(BaseModel):
    models: ModelSettingsOut
    processing: ProcessingSettings
    rag: RagSettings


class SettingsUpdate(BaseModel):
    models: ModelSettingsUpdate | None = None
    processing: ProcessingSettings | None = None
    rag: RagSettings | None = None


class ModelTestRequest(BaseModel):
    target: Literal["llm", "embedding"] = "llm"
    # 允许直接测试页面当前填写值，避免「未保存的新配置测的是旧配置」
    models: ModelSettingsUpdate | None = None


class ModelTestResult(BaseModel):
    ok: bool
    target: str
    message: str
    latency_ms: int = 0
    detail: dict[str, Any] = Field(default_factory=dict)


# ---------- 多文档分析与智能总结 ----------
class AnalysisRequest(BaseModel):
    mode: Literal["compare", "summary"] = "compare"
    document_ids: list[str] = Field(min_length=1, max_length=8)
    topic: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=8)


class AnalysisSectionOut(BaseModel):
    title: str
    content: str


class AnalysisResultOut(BaseModel):
    mode: str
    topic: str
    sections: list[AnalysisSectionOut] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    retrieval_count: int = 0
    truncated: bool = False
    refusal: bool = False
    message: str = ""
    model: str = ""
    took_ms: int = 0


# ---------- 研究报告 ----------
class ReportRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    document_ids: list[str] = Field(min_length=1, max_length=8)
    top_k: int = Field(default=4, ge=1, le=8)


class ReportSectionOut(BaseModel):
    title: str
    content: str


class ReportResultOut(BaseModel):
    report_id: str
    title: str
    topic: str
    sections: list[ReportSectionOut] = Field(default_factory=list)
    citations: list[CitationOut] = Field(default_factory=list)
    markdown: str = ""
    retrieval_count: int = 0
    truncated: bool = False
    refusal: bool = False
    message: str = ""
    model: str = ""
    created_at: datetime
    formats: list[str] = Field(default_factory=list)


class ReportSummaryOut(BaseModel):
    report_id: str
    title: str
    topic: str
    created_at: datetime
    citation_count: int = 0
    formats: list[str] = Field(default_factory=list)


# ---------- 数据备份与恢复 ----------
class BackupInfoOut(BaseModel):
    name: str
    size: int
    created_at: datetime
    secrets_included: bool = False
    format_version: int = 1


class BackupManifestOut(BaseModel):
    name: str
    format_version: int
    app_version: str
    created_at: datetime
    secrets_included: bool
    qdrant_mode: str
    collection: str
    dimension: int = 0
    document_count: int
    chunk_count: int
    file_count: int


class BackupCreateRequest(BaseModel):
    include_secrets: bool = False


class RestoreResultOut(BaseModel):
    restored: bool
    message: str
    pre_restore_backup: str
    document_count: int = 0
    chunk_count: int = 0
    qdrant_mode: str = ""
