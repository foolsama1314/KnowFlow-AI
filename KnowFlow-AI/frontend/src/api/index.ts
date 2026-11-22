import axios, { type AxiosProgressEvent } from 'axios'
import type {
  AnalysisRequest,
  AnalysisResult,
  BackupInfo,
  BackupManifest,
  BatchUploadResult,
  ChatSession,
  ChatSessionDetail,
  ChatSessionList,
  ChatStreamEventDone,
  ChatStreamEventMeta,
  Citation,
  DocumentContent,
  DocumentList,
  DocumentOut,
  Health,
  IndexSummary,
  ModelSettings,
  ModelTestResult,
  RagSettings,
  ReindexProgress,
  ReportRequest,
  ReportResult,
  ReportSummary,
  RestoreResult,
  SearchFilters,
  SearchHistoryItem,
  SearchResponse,
  SettingsPayload,
  Stats,
  StorageLocation,
  SystemInfo,
  TaskList,
  TaskOut,
} from '@/types'

const http = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error?.response?.data?.detail
    let message = '请求失败，请稍后重试'
    if (typeof detail === 'string') {
      message = detail
    } else if (Array.isArray(detail)) {
      message = detail.map((item: { msg?: string }) => item.msg ?? '参数不合法').join('；')
    } else if (error?.message) {
      message = error.message
    }
    return Promise.reject(new Error(message))
  },
)

export interface ChatStreamHandlers {
  onMeta?: (data: ChatStreamEventMeta) => void
  onSources?: (citations: Citation[]) => void
  onDelta?: (text: string) => void
  onDone?: (data: ChatStreamEventDone) => void
  onError?: (message: string) => void
}

function dispatchSse(block: string, handlers: ChatStreamHandlers): void {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return
  let payload: {
    citations?: Citation[]
    text?: string
    message?: string
  } & Partial<ChatStreamEventMeta> &
    Partial<ChatStreamEventDone>
  try {
    payload = JSON.parse(dataLines.join('\n'))
  } catch {
    return
  }
  if (event === 'meta') handlers.onMeta?.(payload as ChatStreamEventMeta)
  else if (event === 'sources') handlers.onSources?.(payload.citations ?? [])
  else if (event === 'delta') handlers.onDelta?.(payload.text ?? '')
  else if (event === 'done') handlers.onDone?.(payload as ChatStreamEventDone)
  else if (event === 'error') handlers.onError?.(payload.message ?? '生成回答失败')
}

async function streamChat(
  sessionId: string,
  question: string,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, stream: true }),
    signal,
  })

  if (!response.ok || !response.body) {
    let message = `请求失败（${response.status}）`
    try {
      const data = await response.json()
      if (typeof data?.detail === 'string') message = data.detail
      else if (Array.isArray(data?.detail)) {
        message = data.detail.map((item: { msg?: string }) => item.msg ?? '').join('；')
      }
    } catch {
      // 保持默认提示
    }
    handlers.onError?.(message)
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      dispatchSse(buffer.slice(0, boundary), handlers)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
    }
  }
  if (buffer.trim()) dispatchSse(buffer, handlers)
}

export const api = {
  // 系统
  health: () => http.get<Health>('/system/health').then((r) => r.data),
  systemInfo: () => http.get<SystemInfo>('/system/info').then((r) => r.data),
  stats: () => http.get<Stats>('/system/stats').then((r) => r.data),
  getStorage: () => http.get<StorageLocation>('/system/storage').then((r) => r.data),
  updateStorage: (data_dir: string, migrate = true) =>
    http
      .put<StorageLocation>('/system/storage', { data_dir, migrate }, { timeout: 600000 })
      .then((r) => r.data),
  resetStorage: (migrate = true) =>
    http
      .delete<StorageLocation>('/system/storage', { params: { migrate }, timeout: 600000 })
      .then((r) => r.data),

  // 文档
  listDocuments: (params: {
    page?: number
    page_size?: number
    status?: string
    file_type?: string
    keyword?: string
  }) => http.get<DocumentList>('/documents', { params }).then((r) => r.data),
  getDocument: (id: string) => http.get<DocumentOut>(`/documents/${id}`).then((r) => r.data),
  getDocumentContent: (id: string) =>
    http.get<DocumentContent>(`/documents/${id}/content`).then((r) => r.data),
  deleteDocument: (id: string) => http.delete(`/documents/${id}`),
  reprocessDocument: (id: string) =>
    http.post<TaskOut>(`/documents/${id}/reprocess`).then((r) => r.data),
  previewUrl: (id: string) => `/api/v1/documents/${id}/preview`,
  uploadFiles: (files: File[], onProgress?: (percent: number) => void) => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    return http
      .post<BatchUploadResult>('/documents/batch-upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600000,
        onUploadProgress: (event: AxiosProgressEvent) => {
          if (onProgress && event.total) {
            onProgress(Math.round((event.loaded / event.total) * 100))
          }
        },
      })
      .then((r) => r.data)
  },

  // 任务
  listTasks: (params: { status?: string; limit?: number; offset?: number }) =>
    http.get<TaskList>('/tasks', { params }).then((r) => r.data),
  getTask: (id: string) => http.get<TaskOut>(`/tasks/${id}`).then((r) => r.data),
  retryTask: (id: string) => http.post<TaskOut>(`/tasks/${id}/retry`).then((r) => r.data),
  cancelTask: (id: string) => http.delete(`/tasks/${id}`),
  taskEventsUrl: (id: string) => `/api/v1/tasks/${id}/events`,

  // 检索
  search: (query: string, topK: number, filters: SearchFilters) =>
    http
      .post<SearchResponse>('/search', { query, top_k: topK, filters })
      .then((r) => r.data),
  searchHistory: () => http.get<SearchHistoryItem[]>('/search/history').then((r) => r.data),
  reindex: () => http.post<{ chunks: number; dimension: number; elapsed_ms: number }>(
    '/search/reindex',
    {},
    { timeout: 600000 },
  ).then((r) => r.data),
  reindexStatus: () => http.get<ReindexProgress>('/search/reindex/status').then((r) => r.data),
  indexSummary: () => http.get<IndexSummary>('/documents/index-summary').then((r) => r.data),

  // 智能问答
  createChatSession: (title = '新会话') =>
    http.post<ChatSession>('/chat/sessions', { title }).then((r) => r.data),
  listChatSessions: (page = 1, pageSize = 50) =>
    http
      .get<ChatSessionList>('/chat/sessions', { params: { page, page_size: pageSize } })
      .then((r) => r.data),
  getChatSession: (id: string) =>
    http.get<ChatSessionDetail>(`/chat/sessions/${id}`).then((r) => r.data),
  deleteChatSession: (id: string) => http.delete(`/chat/sessions/${id}`),
  streamChat,

  // 设置
  getSettings: () => http.get<SettingsPayload>('/settings').then((r) => r.data),
  updateModelSettings: (payload: Record<string, unknown>) =>
    http.put<ModelSettings>('/settings/models', { models: payload }).then((r) => r.data),
  updateProcessing: (payload: Record<string, number>) =>
    http.put<SettingsPayload>('/settings', { processing: payload }).then((r) => r.data),
  updateRag: (payload: RagSettings) =>
    http.put<SettingsPayload>('/settings', { rag: payload }).then((r) => r.data),
  testModel: (target: 'llm' | 'embedding', models?: Record<string, unknown>) =>
    http
      .post<ModelTestResult>('/settings/models/test', { target, models })
      .then((r) => r.data),

  // 多文档分析与智能总结
  analyze: (payload: AnalysisRequest) =>
    http.post<AnalysisResult>('/analysis', payload, { timeout: 180000 }).then((r) => r.data),
  summarize: (payload: AnalysisRequest) =>
    http
      .post<AnalysisResult>('/analysis/summary', payload, { timeout: 180000 })
      .then((r) => r.data),

  // 研究报告
  generateReport: (payload: ReportRequest) =>
    http.post<ReportResult>('/reports/generate', payload, { timeout: 240000 }).then((r) => r.data),
  listReports: (limit = 20) =>
    http.get<ReportSummary[]>('/reports', { params: { limit } }).then((r) => r.data),
  getReport: (id: string) => http.get<ReportResult>(`/reports/${id}`).then((r) => r.data),
  reportDownloadUrl: (id: string, format: 'md' | 'docx') =>
    `/api/v1/reports/${id}/download?format=${format}`,

  // 数据备份与恢复
  listBackups: () => http.get<BackupInfo[]>('/backup').then((r) => r.data),
  createBackup: (includeSecrets = false) =>
    http
      .post<BackupInfo>('/backup', { include_secrets: includeSecrets }, { timeout: 600000 })
      .then((r) => r.data),
  backupDownloadUrl: (name: string) => `/api/v1/backup/${encodeURIComponent(name)}/download`,
  validateBackup: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http
      .post<BackupManifest>('/backup/validate', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600000,
      })
      .then((r) => r.data)
  },
  restoreBackup: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http
      .post<RestoreResult>('/backup/restore', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 900000,
      })
      .then((r) => r.data)
  },
}
