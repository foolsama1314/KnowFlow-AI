# 知枢 AI（KnowFlow AI）

面向个人用户的多模态知识管理与智能分析平台。目标是把 PDF、Word、图片、音视频等异构资料，统一转换为**可搜索、可问答、可深度分析**的结构化个人知识库。

当前版本完成**第一阶段：基础知识库**——资料能进、能解析、能搜、能定位来源。

---

## 一、当前已实现能力

| 模块 | 能力 |
| --- | --- |
| 资料导入 | PDF / DOCX / TXT / Markdown / JPG / PNG / BMP / WEBP，支持批量上传、SHA256 去重、大小上限校验 |
| 文档解析 | PDF 文本层与版面块（含页码、坐标）、DOCX 段落/标题/表格、Markdown 标题与代码块、图片 OCR（需 PaddleOCR） |
| 任务中心 | 后台队列、并发控制、分阶段进度、失败原因、重试、SSE 实时推送、重启后中断任务标记为失败 |
| 文本切块 | 按版面块累积切块，块间重叠，保留页码来源 |
| 向量化 | OpenAI 兼容 Embedding 接口，写入 Qdrant（本地嵌入式或服务模式） |
| 语义检索 | 自然语言检索，返回文档名、页码、原文片段、相似度；支持按格式与文档过滤 |
| 系统设置 | 页面内配置 LLM / Embedding、测试连接、调整切块参数、重建向量索引 |
| 数据看板 | 资料总数、文本块、存储占用、任务状态、格式分布 |

高级能力（RAG 对话、知识图谱、报告生成、跨模态检索）按第四阶段路线逐步实现；对话与图谱相关数据库表已在迁移中预留。

---

## 二、技术栈

| 层级 | 选型 | 职责 |
| --- | --- | --- |
| 桌面壳 | pywebview（WebView2）+ PyInstaller | 原生窗口加载界面，内置本地服务，打包为单文件 exe |
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router + ECharts | 页面交互、任务进度、检索结果、图表 |
| 服务层 | Python + FastAPI + Pydantic | REST API、SSE、参数校验 |
| 数据层 | SQLAlchemy 2.x + Alembic + SQLite | 业务数据与迁移 |
| 向量库 | Qdrant（本地嵌入式 / 服务模式） | 向量存储与相似检索 |
| 解析 | PyMuPDF、python-docx、PaddleOCR（可选） | 文本与版面提取、图片文字识别 |
| 模型 | 国内大模型 API（OpenAI 兼容协议） | 摘要、问答、分类、抽取（后续阶段） |

---

## 三、快速开始

### 1. 后端

```powershell
cd backend
python -m pip install fastapi "uvicorn[standard]" pydantic-settings sqlalchemy alembic pymupdf python-docx python-multipart qdrant-client httpx
python -m uvicorn app.main:app --reload --port 8000
```

启动时会自动建目录、执行 Alembic 迁移、初始化 Qdrant 集合。

- 接口文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/system/health

### 2. 前端

```powershell
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 。

### 3. 扫描件 OCR（可选）

```powershell
python -m pip install paddleocr paddlepaddle
```

未安装时，扫描版 PDF 与图片会给出明确失败提示，不会标记为成功。

### 4. 桌面版（一体式 exe）

```powershell
cd frontend
npm install
npm run build
cd ..
python -m pip install pywebview pyinstaller
python -m PyInstaller desktop.spec --noconfirm
```

产物为 `dist/知枢AI.exe`，双击即可使用：程序内部自动启动本地服务并打开原生窗口，无需浏览器，也无需单独启动后端。

- 数据目录：exe 同级的 `data/`（首次启动自动创建，包含数据库、上传文件、Qdrant 与日志）；换机器时连同 `data/` 一起复制即可。
- 运行日志：`data/logs/desktop.log`
- 依赖系统自带的 Microsoft Edge WebView2 运行时（Windows 10/11 默认具备）。
- 调试桌面外壳：`python backend/desktop.py`。
- 想沿用 web 版已有资料时，把 `KnowFlow-AI/data/` 复制到 exe 同级目录即可。

---

## 四、模型配置

配置有两种方式，页面设置会写入 `data/settings.json` 并覆盖 `.env`：

1. 复制 `.env.example` 为 `.env`，填写 `LLM_*` 与 `EMBEDDING_*`；
2. 启动后在「系统设置」页面填写并测试连接。

关键说明：

- **LLM 与 Embedding 必须分开配置**。部分厂商（如 DeepSeek）只提供对话模型，需要另行选择向量服务（如 bge-m3）。
- **未配置 Embedding 时**，系统使用本地降级向量（字符 n-gram 哈希，1024 维），只保证链路可用，检索效果仅供联调，界面会显式提示。
- **向量维度必须与模型实际输出一致**。更换向量模型后必须点击「重建向量索引」，否则相似度不可比较。
- API Key 只保存在后端环境变量或本地 `data/settings.json`，接口返回时仅告知"是否已配置"。

---

## 五、Qdrant 运行模式

| 模式 | 启用方式 | 适用场景 |
| --- | --- | --- |
| 本地嵌入式 | `QDRANT_URL` 留空（默认） | 个人单机使用，数据在 `data/qdrant`，无需 Docker |
| 服务模式 | `docker compose up -d qdrant` 并设置 `QDRANT_URL=http://localhost:6333` | 多客户端访问或更大数据量 |

---

## 六、目录结构

```
KnowFlow-AI/
├─ frontend/                # Vue 3 前端
│  └─ src/{api,components,layouts,router,styles,views}
├─ backend/                 # FastAPI 后端
│  ├─ app/
│  │  ├─ api/               # 路由：system / documents / tasks / search / settings
│  │  ├─ core/              # 配置、数据库、迁移、异常、日志
│  │  ├─ models/            # SQLAlchemy 模型（10 张表）
│  │  ├─ schemas/           # Pydantic 请求响应模型
│  │  ├─ repositories/      # 数据访问
│  │  ├─ services/          # 上传、检索、流水线、统计、设置
│  │  ├─ processors/        # 解析、OCR、清洗、切块
│  │  ├─ ai/                # LLM/Embedding 适配、向量库封装
│  │  └─ tasks/             # 后台任务与进度订阅
│  ├─ alembic/              # 数据库迁移
│  └─ tests/                # 单元测试
├─ samples/                 # 演示资料
├─ data/                    # 运行时数据（已 gitignore）
├─ docker-compose.yml
├─ .env.example
└─ README.md
```

---

## 七、API 一览（统一前缀 `/api/v1`）

| 分组 | 接口 |
| --- | --- |
| 系统 | `GET /system/health`、`GET /system/info`、`GET /system/stats` |
| 设置 | `GET/PUT /settings`、`GET/PUT /settings/models`、`POST /settings/models/test` |
| 文档 | `POST /documents/upload`、`POST /documents/batch-upload`、`GET /documents`、`GET /documents/{id}`、`GET /documents/{id}/content`、`GET /documents/{id}/preview`、`POST /documents/{id}/reprocess`、`DELETE /documents/{id}` |
| 任务 | `GET /tasks`、`GET /tasks/{id}`、`GET /tasks/{id}/events`（SSE）、`POST /tasks/{id}/retry`、`DELETE /tasks/{id}` |
| 检索 | `POST /search`、`GET /search/history`、`POST /search/reindex` |

---

## 八、数据一致性约定

- 删除文档时，同步删除页面、版面块、切块、标签关联、Qdrant 向量与本地原文件。
- 解析、切块、向量化任一步失败，文档状态为 `failed`，不会错误标记为"可检索"。
- 检索命中孤立向量（文档已删除）时直接跳过，返回结果必须可回溯到真实文本块。
- SQLite 启用 WAL 与外键约束；表结构通过 Alembic 管理，启动自动执行 `upgrade head`。

---

## 九、演示流程

1. 打开「资料管理」→「导入资料」，选择 `samples/` 下的 PDF、Markdown、TXT；
2. 在「任务中心」观察解析进度从 0 到 100；
3. 打开资料详情，查看分页解析结果与版面块；
4. 在「语义检索」输入"检索增强生成的核心组成"，查看命中文档、页码与片段；
5. 点击文档名回到详情，核对原文位置；
6. 在「系统设置」说明如何接入真实 Embedding 并重建索引。

---

## 十、测试

```powershell
cd backend
python -m pytest -q
```

覆盖：切块页与块映射、重叠、超长文本切分、Markdown 解析、空文件报错、OCR 未安装提示、本地向量确定性。

---

## 十一、已知限制

- 检索为纯向量召回，混合检索与重排属于第二阶段。
- 扫描件依赖 PaddleOCR；未安装时该部分资料无法解析。
- 长视频、音频处理未实现，相关接口与模型表结构预留。
- 单用户、无鉴权，仅监听本机地址，请勿直接暴露到公网。
- 支持格式以外的文件（PPT、Excel、音视频）会被拒绝并给出提示。
