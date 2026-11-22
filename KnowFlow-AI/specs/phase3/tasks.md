# 第三阶段任务清单（封版）

> 依赖顺序执行；每个任务完成即更新状态。测试与打包集中在末尾统一执行。

## T1 后端：知识库管理增强（3.1）

- [x] `schemas/__init__.py`：`DocumentOut` 增 `index_status`、`last_error`；新增 `IndexSummaryOut`、`ReindexProgressOut`。
- [x] `api/documents.py`：列表派生单文档索引状态 + 批量取失败原因；新增 `GET /documents/index-summary`。
- [x] `services/search_service.py`：`_reindex_state` 进度（processed/total/stage/error）+ `reindex_progress()`。
- [x] `api/search.py`：`GET /search/reindex/status`。
- 验证：删除文档后 SQLite/Qdrant 同步；失败文档重处理；重建索引进度可轮询。

## T2 后端：RAG 参数与设置（3.5 后端）

- [x] `core/settings_store.py`：`OVERRIDABLE_KEYS` 增 `rag_top_k/rag_min_score/rag_context_chars`。
- [x] `schemas`：`RagSettings`；`SettingsOut/SettingsUpdate` 增 `rag`。
- [x] `services/settings_service.py`：输出/写入 rag；`current()` 附加索引状态摘要（如需）。
- 验证：`GET/PUT /settings` 往返正确；阈值生效于问答/分析。

## T3 后端：多文档分析与智能总结（3.2/3.3）

- [x] `services/rag_service.py`：`build_context` 增 `document_ids` 可选参数（默认不变）；新增 `validate_citations`。
- [x] `services/analysis_service.py`：`analyze()`/`summarize()`，逐文档检索、预算控制、拒答、sections 解析、引用校验。
- [x] `schemas`：`AnalysisRequest/AnalysisSectionOut/AnalysisResultOut`。
- [x] `api/analysis.py`：`POST /analysis`、`POST /analysis/summary`；注册路由。
- 验证：多文档共同点/差异/知识点；单篇总结；无资料拒答；超长截断提示。

## T4 后端：研究报告（3.4）

- [x] `services/report_service.py`：生成、sections 解析、引用校验、MD/DOCX 落盘、列表/读取/下载（防路径穿越）。
- [x] `schemas`：`ReportRequest/ReportSectionOut/ReportResultOut/ReportSummaryOut`。
- [x] `api/report.py`：`POST /reports/generate`、`GET /reports`、`GET /reports/{id}`、`GET /reports/{id}/download`；注册路由。
- 验证：报告含标题/背景/核心内容/关键发现/综合分析/结论/参考资料；下载文件名与内容正确。

## T5 后端：备份与恢复（3.6）

- [x] `services/backup_service.py`：`create_backup/validate_backup/restore_backup/list_backups/backup_path`；SQLite 一致性快照、Qdrant 本地复制或点导出、settings 脱敏、manifest+sha256、自动预备份、失败回滚。
- [x] `schemas`：`BackupInfo/BackupManifestOut/RestoreResult`。
- [x] `api/backup.py`：创建/列表/下载/校验/恢复；注册路由。
- 验证：损坏备份校验失败；恢复失败不破坏当前数据；恢复后文档/会话/Qdrant 一致。

## T6 前端：类型与 API

- [x] `types.ts`：索引摘要/进度、分析、报告、备份、RAG 设置类型；`DocumentOut` 新字段。
- [x] `api/index.ts`：新增接口与下载 URL。

## T7 前端：页面

- [x] `DocumentsView.vue`：索引概览、索引列、失败重处理、重建进度、确认框、空状态。
- [x] `AnalysisView.vue`（`/analysis`）：文档多选、分析/总结、sections、引用跳转、状态处理。
- [x] `ReportView.vue`（`/reports`）：主题+文档、生成、预览、MD/DOCX 下载、历史报告。
- [x] `SettingsView.vue`：RAG 参数、功能可用性提示、备份与恢复面板。
- [x] `MainLayout.vue` + `router/index.ts`：新增菜单与路由。

## T8 稳定性（3.8）

- [x] `desktop.py`：启动时检测 data 目录可写，不可写给出中文提示并退出。
- [x] 统一错误文案检查：模型/网络/超时/SSE/解析/索引/DB。
- 验证：断网、无效 Key、未配置模型、SSE 主动中断均有可读提示。

## T9 集中测试

- [x] 后端：`pytest`（新增 analysis/report/backup/index-summary 测试）。
- [x] 前端：`npm run type-check`、`npm run build`。
- [x] 真实检索阈值实测记录（命中/弱相关/无关 + 拒答结果）。
- [x] 备份恢复一致性、重启持久化、异常场景。

## T10 打包与 EXE 实测

- [x] `npm run build` → `pyinstaller desktop.spec`。
- [x] 启动 EXE：健康检查、静态资源、导入、检索、问答、引用跳页、备份、重启恢复。
- [x] 确认 EXE 不含真实 API Key。

## T11 交付材料

- [x] 软件使用说明书、功能介绍、技术架构、创新点、安装启动、评委体验流程、演示资料与问题、目录结构、已完成/未完成清单。
- [x] 最终开发报告（功能、文件、测试、真实模型结果、EXE 路径与启动结果、已知问题、未验证内容）。
