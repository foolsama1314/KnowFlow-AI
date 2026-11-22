# 知枢 AI 第三阶段（封版）实施规格

> 状态：待确认（Spec Mode）
> 范围：3.1 → 3.8、集中测试、最终 EXE 打包、比赛材料与最终报告
> 硬约束：保持 pywebview + WebView2 / Vue3 + TS + Vite / FastAPI / SQLite / Qdrant / PyInstaller 架构；不重写第一、二阶段已验收逻辑；不新增不必要依赖；不使用假数据或模拟模型冒充真实验收。

## 1. 现状结论（已核对代码）

- 文档上传、去重（file_hash）、空文件拒绝、损坏/解析失败提示均已存在（`app/services/document_service.py`、`app/processors/document_parser.py`）。
- 删除文档已同步清理 Qdrant 向量、SQLite 页面/块/切块，并同步索引计数（`delete_document` + `sync_count_after_delete`）。
- 索引重建为「临时集合完整构建 → 原子切换别名」（`app/services/search_service.py: reindex`），但缺少可轮询进度。
- 文档列表缺少「单文档索引状态 / 失败原因」字段。
- RAG 问答、SSE、服务端引用校验、cited/uncited 区分、页码定位、会话持久化均已完成（`chat_service.py`、`rag_service.py`），不改动其核心行为。
- 设置页已有 LLM/Embedding 配置与连接测试；缺少 RAG 参数（top_k、min_score、context_chars）读写。
- 不存在多文档分析、智能总结、研究报告、备份恢复模块。
- `python-docx`、`pymupdf` 已是依赖，DOCX 导出直接复用 `python-docx`，不新增依赖。

## 2. 总体设计决策

| 主题 | 决策 |
| --- | --- |
| 新增服务 | `analysis_service.py`（多文档分析与智能总结共用）、`report_service.py`、`backup_service.py` |
| 新增 API | `/analysis`、`/reports`、`/backup`、`/documents/index-summary`、`/search/reindex/status` |
| 检索方式 | 逐文档限定 `document_ids` 检索，每篇取 `top_k`（默认 3），绝不拼接全文；统一用 `rag_service.build_context` 做 SQL 校验与字符预算 |
| 引用 | 复用现有编号规则 `[n]`；新增 `rag_service.validate_citations` 供分析/报告使用，`chat_service` 保持原样 |
| 分析/总结结果 | 不新建数据库表（避免迁移）；接口直接返回结构化 sections + citations |
| 报告持久化 | 报告文件落在 `data/exports/reports/<report_id>.{json,md,docx}`，供预览、下载、重启后回看 |
| 备份格式 | ZIP：`manifest.json` + `database/knowflow.db` + `uploads/**` + `qdrant/`（本地模式）或 `qdrant_points.json`（服务模式）+ 脱敏 `settings.json` |
| 备份安全 | 默认剔除 `llm_api_key` / `embedding_api_key`；恢复前自动备份当前数据；先校验 manifest+sha256 再原子替换，失败回滚 |
| 危险操作 | 删除文档、重建索引、恢复备份全部前端二次确认；恢复前提示先备份 |
| 异常 | 统一 `AppError` 中文文案；未配置模型时明确列出不可用功能；不向用户暴露 Python 堆栈 |
| 不新增依赖 | MD 导出用字符串拼接，DOCX 用 `python-docx`，打包仍用 `desktop.spec` |

## 3. 3.1 知识库管理

### 后端

1. `app/schemas/__init__.py`
   - `DocumentOut` 增加可选字段：`index_status: str = "unknown"`、`last_error: str | None = None`。
   - 新增 `IndexSummaryOut`：`total_documents`、`completed_documents`、`failed_documents`、`pending_index`、`total_chunks`、`indexed_chunks`、`index_status`、`running_tasks`。
   - 新增 `ReindexProgressOut`：`running`、`processed`、`total`、`stage`、`error`、`finished_at`。
2. `app/api/documents.py`
   - 列表接口一次性读取全局索引状态；为每个文档派生：
     - `status in {uploaded, processing}` → `processing`
     - `status == failed` → `failed`，`last_error` 取该文档最近失败任务 `error_message`（一次批量查询，不做 N+1）
     - `status == completed` 且全局索引 `completed` → `indexed`
     - `status == completed` 其他情况 → `not_indexed`
   - 新增 `GET /documents/index-summary`：统计已完成/失败/待索引文档数、文本块总数、已索引块数、运行中任务数；数据来自 SQLite 聚合 + `vector_store.count()`。
3. `app/services/search_service.py`
   - 增加模块级 `_reindex_state`（锁保护）：`running/processed/total/stage/error/finished_at`；`reindex()` 每批更新 `processed`，成功/失败写入终态。
   - 新增 `reindex_progress() -> ReindexProgressOut`。
   - `app/api/search.py` 新增 `GET /search/reindex/status`。
4. 删除、失败重处理沿用现有实现；删除前确认由前端负责；后端保证 Qdrant + SQLite 双写一致（已有）。

### 前端 `DocumentsView.vue`

- 顶部新增索引概览条：总数 / 已完成 / 失败 / 待索引 / 文本块，以及「重建索引」按钮。
- 表格新增「索引」列（已索引 / 待索引 / 处理中 / 失败 / 未完成），失败文档显示 `last_error` tooltip。
- 失败文档操作菜单展示「重新处理」；所有删除/重处理/重建均有确认框。
- 重建索引：确认 → 调用 `POST /search/reindex`，同时每 1.5s 轮询 `/search/reindex/status` 展示进度条与阶段文案；完成后刷新列表与概要。
- 空状态：无文档时展示导入引导；加载/错误状态沿用 Element Plus。

## 4. 3.2 多文档分析 & 3.3 智能总结

### 服务 `app/services/analysis_service.py`

- `MODE_COMPARE = "compare"`，`MODE_SUMMARY = "summary"`。
- `async def analyze(db, payload: AnalysisRequest) -> AnalysisResult`：
  1. 校验：`document_ids` 1–8 个且文档存在、`status == completed`；否则 404/400 中文提示。
  2. LLM 未配置 → `AIProviderError`（「请先在系统设置配置大模型」）。
  3. 逐文档调用 `rag_service.build_context(db, topic, top_k=payload.top_k, document_ids=[doc_id], max_chars=per_doc_budget)`；`per_doc_budget = rag_context_chars // len(docs)`。
  4. 合并命中、按 chunk_id 去重、重排序号；总字符超预算时按文档轮转截断并置 `truncated=True`。
  5. 无命中或最大分 < `rag_min_score` → 不调用 LLM，返回 `refusal=True` 与明确说明（区分「无资料」与「资料不足」）。
  6. 提示词按模式固定小节：
     - compare：`共同观点`、`差异分析`、`关键知识点`
     - summary（单篇时标题用「核心观点/关键概念/重要结论/待研究问题」）：`核心观点`、`关键概念`、`重要结论`、`待研究问题`
  7. 调用 `llm.chat`（非流式，超时 90s）；`rag_service.validate_citations` 清洗越界编号；按 `## ` 或 `### ` 标题切分 sections；解析失败则整段作为「分析结果」。
  8. 返回 `sections`、`citations`（含 cited 标记）、`retrieval_count`、`truncated`、`refusal`、`message`、`model`、`took_ms`。
- 上下文超长：通过字符预算 + 文档数上限（8）+ 每篇 top_k 控制；返回 `truncated` 与前端提示，不做全文拼接。
- 同时提供 `async def summarize(...)` 复用 `analyze(mode="summary")`。

### API `app/api/analysis.py`

- `POST /analysis` → `AnalysisResult`。
- `POST /analysis/summary` → 同上，固定 summary 模式。

### Schema

- `AnalysisRequest`：`mode: Literal["compare","summary"]="compare"`、`document_ids: list[str]`（1–8）、`topic: str`（1–500）、`top_k: int=3 (1–8)`。
- `AnalysisSectionOut`：`title`、`content`。
- `AnalysisResultOut`：`mode/topic/sections/citations/retrieval_count/truncated/refusal/message/model/took_ms`。

### 前端 `AnalysisView.vue`（`/analysis`）

- 左侧文档多选（仅 completed），支持搜索；右侧输入主题，切换「联合分析 / 智能总结」页签。
- 生成中展示 loading 与耗时提示；结果按 sections 卡片渲染，正文纯文本保留换行。
- 引用列表显示文件名 + 页码，可点击跳转 `/documents/{id}?page=n`；区分「已引用 / 仅检索到」。
- 空状态：无可用文档时提示先导入；未配置 LLM 时禁用生成并提示。

## 5. 3.4 研究报告

### 服务 `app/services/report_service.py`

- `async def generate(db, payload: ReportRequest) -> ReportResult`：
  1. 校验主题与文档（同 3.2），逐文档限定检索（每篇 top_k=4，总预算 `rag_context_chars`）。
  2. 资料不足 → `refusal=True`，不生成文件。
  3. LLM 未配置 → `AIProviderError`。
  4. 提示词要求固定小节：`研究背景`、`核心内容`、`关键发现`、`综合分析`、`结论`、`参考资料`；要求每个结论带 `[n]`，严禁编造。
  5. 校验引用编号；从未引用的资料不进入最终参考资料列表。
  6. 组装 `title = 主题 + " 研究报告"`、`sections`、`citations`；生成 Markdown 文本（标题 + 各节 + 参考资料文件名/页码）。
  7. 落盘：`data/exports/reports/<report_id>.json`（完整结构 + 引用）、`.md`、`.docx`（`python-docx`：标题、小节、参考资料）。
  8. 返回 `ReportResult`（含 `report_id`、文件是否存在、`created_at`）。
- `list_reports(limit)`：扫描 json sidecar；`get_report(report_id)`：读取 json；`download_path(report_id, fmt)`：严格校验 `report_id` 为 UUID/十六进制，防路径穿越。

### API `app/api/report.py`

- `POST /reports/generate`
- `GET /reports`（列表）
- `GET /reports/{report_id}`
- `GET /reports/{report_id}/download?format=md|docx`（`FileResponse`，UTF-8 文件名）

### 前端 `ReportView.vue`（`/reports`）

- 左栏：主题输入 + 文档多选；右栏：生成按钮、预览区（按 sections 渲染）、下载 MD/DOCX。
- 历史报告列表（最近 20 份），点击预览；空/加载/失败状态齐全。
- 失败提示区分：未配置模型、资料不足、上下文截断、模型请求失败。

## 6. 3.5 系统设置

### 后端

- `app/services/settings_store.py`：`OVERRIDABLE_KEYS` 增加 `rag_top_k`、`rag_min_score`、`rag_context_chars`。
- `app/schemas/__init__.py`：新增 `RagSettings`（`rag_top_k 1–20`、`rag_min_score 0–1`、`rag_context_chars 1000–30000`）；`SettingsOut`/`SettingsUpdate` 增加 `rag` 字段。
- `app/services/settings_service.py`：`current()` 输出 rag；`update()` 写入 rag 覆盖并 `reload_settings()`。
- `GET /settings` 返回模型配置状态、索引状态（新增 `index_status` 摘要）与 RAG 参数。
- API Key 仍只写 `data/settings.json`（已 gitignore），接口仅返回 `has_key`。

### 前端 `SettingsView.vue`

- 新增「RAG 检索参数」面板：top_k、min_score（0–1，步长 0.01，含阈值说明：当前 Embedding 实测命中约 0.69–0.78，弱相关约 0.35–0.42，需按实际测试调整）、上下文长度。
- 新增「功能可用性」提示：Embedding 未配置 → 语义检索/索引不可用；LLM 未配置 → 问答/分析/总结/报告不可用；Key 无效/额度不足 → 测试连接返回可读原因。
- 新增「数据备份与恢复」面板（见 3.6）。

## 7. 3.6 数据备份与恢复

### 服务 `app/services/backup_service.py`

- `create_backup(include_secrets: bool=False) -> BackupInfo`
  - 若有运行中任务 → `ConflictError`。
  - SQLite 使用 `sqlite3.Connection.backup()` 一致性快照到临时目录（不直接复制正在写入的 db）。
  - 本地 Qdrant：复制 `data/qdrant`；服务模式：`client.scroll` 导出全部点（向量 + payload）到 `qdrant_points.json`。
  - `uploads/**` 原样打包；`settings.json` 根据 `include_secrets` 删除 `llm_api_key`/`embedding_api_key`（并标记 `secrets_included=false`）。
  - `manifest.json`：`format_version`、`app_version`、`created_at`、`secrets_included`、`qdrant_mode`、`collection`、`dimension`、`files[{path, sha256, size}]`。
  - 输出到 `data/backups/knowflow-backup-YYYYmmdd-HHMMSS.zip`。
- `validate_backup(zip_path) -> BackupManifest`
  - 校验 ZIP 完整性、`manifest.json` 存在且格式版本匹配、所有文件 sha256 一致、`database/knowflow.db` 可被 SQLite 打开且含 `documents` 表。
  - 不完整/损坏 → `ProcessingError("备份文件校验失败：...")`。
- `restore_backup(zip_path) -> RestoreResult`
  1. 先 `create_backup(include_secrets=True)` 自动生成 `pre-restore-*.zip`。
  2. 校验备份；解压到 `data/.restore_tmp`。
  3. 关闭 Qdrant 客户端、`engine.dispose()`；将当前 `database/`、`uploads/`、`qdrant/` 移动到 `data/.restore_old`。
  4. 原子替换为解压内容；服务模式则重建集合并回灌点。
  5. 任一步失败：回滚 `.restore_old`，返回明确错误，当前数据不丢失。
  6. 成功：`reload_settings()`、`reset_clients()`、`vector_store.reset()`、`get_index_status()`，返回恢复统计（文档数/块数）。
- `list_backups()` 扫描 `data/backups`；`backup_path(name)` 严格文件名白名单。

### API `app/api/backup.py`

- `POST /backup`（body: `{include_secrets: false}`）→ 备份信息
- `GET /backup` → 备份列表
- `GET /backup/{name}/download` → 下载
- `POST /backup/validate`（上传 zip）
- `POST /backup/restore`（上传 zip）→ 恢复结果；恢复前前端二次确认
- 上传大小上限复用 `max_upload_mb`，文件先落 `data/backups/_upload` 再校验。

### 前端 Settings 备份面板

- 展示备份列表（时间、大小、是否含密钥）。
- 「立即备份」默认脱敏；勾选「包含 API Key（仅限本机使用）」需二次确认。
- 「恢复」：选择文件 → 提示「恢复前会先自动备份当前数据」→ 确认 → 显示校验与恢复进度/结果。

## 8. 3.7 / 3.8 UI 与稳定性

- 路由新增 `/analysis`、`/reports`；侧边栏菜单加「多文档分析」「研究报告」（图标 `DataAnalysis`、`Notebook`）。
- 所有新页面具备空状态、加载状态、错误提示、危险操作确认；长任务显示进度或加载文案。
- 后端异常：
  - LLM/Embedding 未配置、Key 无效（401/403）、额度不足（402/429）、网络错误、超时 90s：`AIProviderError` 中文提示。
  - SSE 中途断开：沿用现有 finally 保存已生成内容并追加「（生成已中断）」。
  - 文档解析/索引失败：任务与文档状态置 failed，前端可见原因并可重处理。
  - 数据库异常：备份恢复前 `engine.dispose()`；恢复失败回滚。
  - 退出：沿用 `desktop.py` 的 `should_exit` 与 `runner.shutdown()`。
  - 无写入权限：启动时检测 `data` 可写，失败给出中文提示并退出（不显示堆栈）。
- 前端：`api/index.ts` 补充新接口；`types.ts` 补充新类型；错误统一 `ElMessage.error(Error.message)`。

## 9. 测试计划（集中执行）

1. `pytest` 全量（含新增 `tests/test_analysis.py`、`tests/test_report.py`、`tests/test_backup.py`、`tests/test_index_summary.py`）。
2. `npm run type-check`、`npm run build`。
3. 真实检索阈值实测：对真实知识库问题记录 top1/top3 分数、弱相关问题、无关问题、是否拒答；结果写入最终报告，不伪造。
4. RAG 问答与引用校验回归（现有测试）。
5. 备份 → 修改 → 恢复 → 数据一致性测试（临时 data 目录）。
6. 重启持久化测试（后端进程重启后会话/文档/报告仍在）。
7. 异常测试：未配置 LLM、无效 Key、断网、超时、SSE 断开、损坏备份。
8. 真实 LLM 验收：仅在用户于设置中配置真实模型后进行；未配置则报告标记「真实模型验收未完成」。

## 10. 打包与验收

1. `npm run build` → `pyinstaller desktop.spec`。
2. 启动 EXE，验证：健康检查、静态资源、导入文档、真实检索、问答（无 LLM 时明确提示）、引用跳页、分析/总结/报告（有 LLM 时）、备份恢复、关闭重开数据持久化。
3. 检查 EXE 内不含真实 API Key（搜索 `data/settings.json`、`dist`、`build`）。
4. 交付：EXE 路径、运行环境要求、比赛材料（使用说明、功能介绍、架构说明、创新点、安装启动、评委体验流程、演示资料与问题、目录结构、已完成/未完成清单）、最终开发报告。

## 11. 验收标准

- 所有新增 API 有真实业务实现，非前端占位。
- 分析/总结/报告仅基于知识库检索结果，引用可追溯到文件与页码；资料不足明确拒答。
- 备份恢复可校验、可回滚、默认脱敏。
- 原有第一、二阶段功能回归通过。
- `pytest` 全绿、前端 build 通过、EXE 实际启动验证完成（真实 LLM 部分按实际配置标注）。

## 12. 不做的事

- 不改 Electron、不改纯 Web 架构。
- 不新增数据库表/迁移（报告与分析结果以文件/接口返回）。
- 不改第一、二阶段检索核心逻辑（仅新增进度统计与可选 document_ids 参数）。
- 不引入 Markdown 渲染或新的导出依赖。
