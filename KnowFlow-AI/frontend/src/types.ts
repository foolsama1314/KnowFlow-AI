export interface DocumentOut {
  id: string
  name: string
  original_name: string
  file_type: string
  file_size: number
  status: string
  page_count: number
  chunk_count: number
  summary: string | null
  index_status: 'indexed' | 'not_indexed' | 'processing' | 'failed' | 'unknown'
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface BlockOut {
  id: string
  block_type: string
  block_order: number
  content: string
  bbox: number[] | null
  confidence: number
}

export interface PageOut {
  id: string
  page_no: number
  width: number | null
  height: number | null
  content: string
  parse_method: string
  confidence: number
  blocks: BlockOut[]
}

export interface DocumentContent {
  document: DocumentOut
  pages: PageOut[]
}

export interface DocumentList {
  items: DocumentOut[]
  total: number
  page: number
  page_size: number
}

export interface UploadItem {
  document_id: string
  task_id: string
  name: string
}

export interface BatchUploadResult {
  succeeded: UploadItem[]
  failed: { name: string; message: string }[]
}

export interface TaskOut {
  id: string
  document_id: string
  task_type: string
  status: string
  progress: number
  current_step: string
  error_message: string | null
  retry_count: number
  document_name: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface TaskList {
  items: TaskOut[]
  total: number
}

export interface TaskEvent {
  task_id: string
  document_id: string
  document_name?: string | null
  status: string
  progress: number
  current_step: string
  error_message: string | null
  updated_at?: string
}

export interface Stats {
  document_count: number
  chunk_count: number
  storage_bytes: number
  task_running: number
  task_failed: number
  by_file_type: Record<string, number>
  by_status: Record<string, number>
}

export interface VectorIndexStatus {
  provider: string
  model: string
  dimension: number
  status: 'unconfigured' | 'not_indexed' | 'building' | 'completed' | 'requires_reindex' | 'failed'
  chunk_count: number
  error: string | null
  updated_at: string
}

export interface SystemInfo {
  app_name: string
  version: string
  api_prefix: string
  data_dir: string
  data_dir_custom: boolean
  database: string
  qdrant_mode: string
  qdrant_collection: string
  embedding_provider: string
  embedding_model: string
  embedding_dim: number
  embedding_degraded: boolean
  retrieval_mode: 'semantic' | 'unconfigured'
  index_status: VectorIndexStatus
  llm_configured: boolean
  ocr_available: boolean
  supported_extensions: string[]
  python_version: string
}

export interface Health {
  status: string
  version: string
  database: boolean
  qdrant: boolean
}

export interface StorageLocation {
  data_dir: string
  default_data_dir: string
  custom: boolean
  exists: boolean
  restart_required: boolean
  message: string
}

export interface SearchFilters {
  document_ids: string[]
  file_types: string[]
}

export interface SearchHit {
  chunk_id: string
  document_id: string
  document_name: string
  file_type: string
  page_from: number | null
  page_to: number | null
  content: string
  score: number
}

export interface SearchResponse {
  query: string
  results: SearchHit[]
  took_ms: number
  retrieval_mode: 'semantic'
  embedding_model: string
  index_status: VectorIndexStatus
}

export interface SearchHistoryItem {
  query: string
  top_k: number
  result_count: number
  at: string
}

export interface ModelSettings {
  llm_provider: string
  llm_base_url: string
  llm_model: string
  llm_has_key: boolean
  llm_configured: boolean
  embedding_provider: string
  embedding_base_url: string
  embedding_model: string
  embedding_dim: number
  embedding_has_key: boolean
  embedding_configured: boolean
  embedding_degraded: boolean
}

export interface ProcessingSettings {
  chunk_size: number
  chunk_overlap: number
  default_top_k: number
  max_upload_mb: number
}

export interface RagSettings {
  rag_top_k: number
  rag_min_score: number
  rag_context_chars: number
}

export interface SettingsPayload {
  models: ModelSettings
  processing: ProcessingSettings
  rag: RagSettings
}

export interface ModelTestResult {
  ok: boolean
  target: string
  message: string
  latency_ms: number
  detail: Record<string, unknown>
}

export interface Citation {
  chunk_id: string
  document_id: string
  document_name: string
  file_type: string
  page_from: number | null
  page_to: number | null
  snippet: string
  score: number
  cited: boolean
}

export interface ChatMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | string
  content: string
  citations: Citation[] | null
  created_at: string
}

export interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ChatSessionList {
  items: ChatSession[]
  total: number
  page: number
  page_size: number
}

export interface ChatSessionDetail {
  session: ChatSession
  messages: ChatMessage[]
}

export interface ChatAnswer {
  message: ChatMessage
  citations: Citation[]
  retrieval_count: number
  context_truncated: boolean
  refusal: boolean
  took_ms: number
}

export interface ChatStreamEventMeta {
  model: string
  retrieval_count: number
  max_score: number
  truncated: boolean
  refusal: boolean
}

export interface ChatStreamEventDone {
  message_id: string
  content: string
  citations: Citation[]
  refusal: boolean
  took_ms: number
}

export interface IndexSummary {
  total_documents: number
  completed_documents: number
  failed_documents: number
  pending_index: number
  total_chunks: number
  indexed_chunks: number
  index_status: VectorIndexStatus
  running_tasks: number
}

export interface ReindexProgress {
  running: boolean
  processed: number
  total: number
  stage: string
  error: string | null
  finished_at: string | null
}

export interface AnalysisSection {
  title: string
  content: string
}

export interface AnalysisRequest {
  mode: 'compare' | 'summary'
  document_ids: string[]
  topic: string
  top_k?: number
}

export interface AnalysisResult {
  mode: 'compare' | 'summary'
  topic: string
  sections: AnalysisSection[]
  citations: Citation[]
  retrieval_count: number
  truncated: boolean
  refusal: boolean
  message: string
  model: string
  took_ms: number
}

export interface ReportRequest {
  topic: string
  document_ids: string[]
  top_k?: number
}

export interface ReportResult {
  report_id: string
  title: string
  topic: string
  sections: AnalysisSection[]
  citations: Citation[]
  markdown: string
  retrieval_count: number
  truncated: boolean
  refusal: boolean
  message: string
  model: string
  created_at: string
  formats: string[]
}

export interface ReportSummary {
  report_id: string
  title: string
  topic: string
  created_at: string
  citation_count: number
  formats: string[]
}

export interface BackupInfo {
  name: string
  size: number
  created_at: string
  secrets_included: boolean
  format_version: number
}

export interface BackupManifest {
  name: string
  format_version: number
  app_version: string
  created_at: string
  secrets_included: boolean
  qdrant_mode: string
  collection: string
  dimension: number
  document_count: number
  chunk_count: number
  file_count: number
}

export interface RestoreResult {
  restored: boolean
  message: string
  pre_restore_backup: string
  document_count: number
  chunk_count: number
  qdrant_mode: string
}
