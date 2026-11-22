# 知枢 AI 已配置 API 全面功能测试记录

- 测试时间：2026-11-22T19:58:05 ~ 2026-11-22T19:59:27
- 测试地址：http://127.0.0.1:8011/api/v1
- 应用版本：知枢 AI v0.1.0
- 数据隔离：复制 dist/data 到临时目录后运行，所有写操作均不影响原数据目录
- 用例总数：177，通过 173，未通过 4，通过率 97.74%

## 一、结论

本次测试覆盖了已注册的全部 REST 接口，以及已配置的 DeepSeek 大模型和 Jina Embedding 服务。
OpenAPI 中登记的 36 个路径、45 个方法操作全部纳入用例，未发现遗漏接口。
核心链路（文档上传解析、向量化、语义检索、RAG 问答、多文档分析、研究报告、任务中心、设置管理）均返回真实数据，未发现模拟数据或静默降级。

测试共发现 4 项真实缺陷，其中 1 项 P1（备份恢复不可用）、2 项 P2（备份文件覆盖、未知 API 返回 200 HTML）、1 项 P3（文档详情索引状态未回填）。
除上述缺陷外，其余功能与预期配置一致。

## 二、环境与已配置 API

| 项目 | 值 |
| --- | --- |
| LLM | openai_compatible / https://api.deepseek.com/v1 / deepseek-chat |
| Embedding | openai_compatible / https://api.jina.ai/v1 / jina-embeddings-v3 |
| 向量维度 | 1024 |
| 向量库 | Qdrant local / document_chunks |
| 检索模式 | semantic |
| 索引状态 | completed（11/11 块） |
| 初始知识库 | 3 文档 / 11 文本块 |

说明：报告中不展示任何 API Key 明文；外部服务请求头与响应中的密钥均已脱敏。

## 三、关键链路实测指标

| 链路 | 实测结果 | 耗时 |
| --- | --- | ---: |
| LLM 连接测试 | 大模型连接成功：连接成功；模型 deepseek-chat | 1654 ms |
| Embedding 连接测试 | 向量服务连接成功，返回维度校验通过；维度 1024；降级 False | 1535 ms |
| 语义检索 | 5 条结果；最高相似度 0.6884 | 1427 ms |
| 全量重建索引 | 12 块；1024 维 | 2052 ms |
| 非流式 RAG 问答 | 引用 5 条；回答 41 字 | 3267 ms |
| 流式 RAG 问答 | 60 个 SSE 事件；最高相似度 0.7427 | 3555 ms |
| 多文档对比分析 | 3 个小节；检索 6 段 | 8069 ms |
| 研究报告生成 | 5 个小节；导出 ['md', 'docx'] | 9127 ms |
| 备份完整性校验 | 4 文档；12 块；16 文件 | 37 ms |

## 四、模块覆盖统计

| 模块 | 用例数 | 通过 | 未通过 | 通过率 |
| --- | ---: | ---: | ---: | ---: |
| 外部模型服务 | 6 | 6 | 0 | 100.0% |
| 系统 | 4 | 4 | 0 | 100.0% |
| 系统设置 | 18 | 18 | 0 | 100.0% |
| 文档管理 | 36 | 35 | 1 | 97.2% |
| 任务中心 | 15 | 15 | 0 | 100.0% |
| 语义检索 | 17 | 17 | 0 | 100.0% |
| 智能问答 | 21 | 21 | 0 | 100.0% |
| 多文档分析 | 10 | 10 | 0 | 100.0% |
| 研究报告 | 15 | 15 | 0 | 100.0% |
| 备份恢复 | 19 | 17 | 2 | 89.5% |
| 存储位置 | 9 | 9 | 0 | 100.0% |
| 通用协议 | 7 | 6 | 1 | 85.7% |

## 五、边界与异常场景覆盖

| 场景类型 | 覆盖用例 | 实测结果 |
| --- | --- | --- |
| 必填缺失 / 类型错误 | SEA-03、SEA-11、CHAT-10、ANA-03/06、REP-12/14、DOC-23、X-05 | 均返回 422，未出现 500 |
| 数值上下边界 | SET-10~17、DOC-06/07、SEA-04~06、CHAT-11~13、ANA-07~09、REP-03/04/10、TSK-04~06、STO-01~02 | 越界值全部被 422 拒绝，合法边界值通过 |
| 资源不存在 | DOC-10/12/14/29/34、TSK-08/12/15、CHAT-08/14/21、ANA-05、REP-07/11/13、BKP-08 | 均返回 404（BKP-08 为 404） |
| 重复与冲突 | DOC-18、SEA-16 | 重复文件 409；并发重建一个 200、一个 409 |
| 不支持格式 / 方法 | DOC-19、X-04、REP-10 | 415、405、422 均符合预期 |
| 外部服务鉴权失败 | EXT-03/06、SET-08/09 | 401/403 或 ok=false，未伪造成功、未静默降级 |
| 无资料依据的拒答 | CHAT-15/17、ANA-10、REP-15 | RAG 问答与流式问答均明确拒答；分析与报告未越出资料范围或已拒答 |
| 并发互斥 | SEA-16 | 重建索引锁生效，返回 200 与 409 |
| 恢复失败后的数据安全 | BKP-14~18 | 恢复失败后自动回滚，文档、索引、检索、健康检查均正常 |
| 未知 API 路径 | X-02 | 返回 200 HTML（未通过，见缺陷清单） |

## 六、缺陷清单

| 级别 | 用例 | 问题 | 影响与建议 |
| --- | --- | --- | --- |
| P1 | BKP-13 | 备份恢复在 Windows 下失败：Qdrant 目录被占用 | 影响：桌面端「数据备份与恢复」的恢复流程实际不可用；虽然失败后已自动回滚且数据未被破坏，但用户无法通过备份恢复数据。 建议：在关闭 Qdrant 客户端后等待锁释放并延长重试；或改为复制到目标后再删除旧目录，避免对正在使用的目录做 rename。 |
| P2 | BKP-19 | 连续备份文件名秒级冲突，后一次覆盖前一次 | 影响：用户快速连续备份时，前一个备份会被静默覆盖，造成备份丢失。 建议：文件名中加入毫秒或短随机串，并在写入前检查同名文件，必要时追加序号。 |
| P2 | X-02 | 未知 API 路径返回 200 HTML，而不是 404 JSON | 影响：API 客户端无法通过状态码区分「接口不存在」与「成功」；错误处理与监控会被误导。备份文件本身未被泄露。 建议：为 /api/* 未匹配路径增加 JSON 404 兜底，SPA 回退只对非 API 路径生效。 |
| P3 | DOC-36 | 文档详情接口未回填 index_status | 影响：同一资源在不同接口中的字段不一致，依赖详情页展示索引状态的场景可能误判为未知状态。 建议：详情接口复用列表的索引状态装饰逻辑，或在 DocumentOut 校验时补充 index_status。 |

## 七、逐项测试结果

| ID | 模块 | 测试项 | 方法 | 路径 | 预期 | 实际 | 结果 | 截图 | 详情 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXT-01 | 外部模型服务 | DeepSeek LLM 对话补全直连 | POST | https://api.deepseek.com/v1/chat/completions | 200 | 200 | 通过 | [截图](screenshots/001_PASS_EXT-01_DeepSeek_LLM_对话补全直连.png) | [详情](cases/EXT-01.html) |
| EXT-02 | 外部模型服务 | DeepSeek LLM 流式输出直连 | POST | https://api.deepseek.com/v1/chat/completions | 200 | 200 | 通过 | [截图](screenshots/002_PASS_EXT-02_DeepSeek_LLM_流式输出直连.png) | [详情](cases/EXT-02.html) |
| EXT-03 | 外部模型服务 | DeepSeek LLM 鉴权失败处理 | POST | https://api.deepseek.com/v1/chat/completions | [401, 403] | 401 | 通过 | [截图](screenshots/003_PASS_EXT-03_DeepSeek_LLM_鉴权失败处理.png) | [详情](cases/EXT-03.html) |
| EXT-04 | 外部模型服务 | Jina Embedding 向量接口直连 | POST | https://api.jina.ai/v1/embeddings | 200 | 200 | 通过 | [截图](screenshots/004_PASS_EXT-04_Jina_Embedding_向量接口直连.png) | [详情](cases/EXT-04.html) |
| EXT-05 | 外部模型服务 | Jina Embedding 模型名错误处理 | POST | https://api.jina.ai/v1/embeddings | [400, 404, 422] | 422 | 通过 | [截图](screenshots/005_PASS_EXT-05_Jina_Embedding_模型名错误处理.png) | [详情](cases/EXT-05.html) |
| EXT-06 | 外部模型服务 | Jina Embedding 鉴权失败处理 | POST | https://api.jina.ai/v1/embeddings | [401, 403] | 401 | 通过 | [截图](screenshots/006_PASS_EXT-06_Jina_Embedding_鉴权失败处理.png) | [详情](cases/EXT-06.html) |
| SYS-01 | 系统 | 健康检查 | GET | http://127.0.0.1:8011/api/v1/system/health | 200 | 200 | 通过 | [截图](screenshots/007_PASS_SYS-01_健康检查.png) | [详情](cases/SYS-01.html) |
| SYS-02 | 系统 | 系统信息与模型配置状态 | GET | http://127.0.0.1:8011/api/v1/system/info | 200 | 200 | 通过 | [截图](screenshots/008_PASS_SYS-02_系统信息与模型配置状态.png) | [详情](cases/SYS-02.html) |
| SYS-03 | 系统 | 知识库统计 | GET | http://127.0.0.1:8011/api/v1/system/stats | 200 | 200 | 通过 | [截图](screenshots/009_PASS_SYS-03_知识库统计.png) | [详情](cases/SYS-03.html) |
| SYS-04 | 系统 | 读取存储位置 | GET | http://127.0.0.1:8011/api/v1/system/storage | 200 | 200 | 通过 | [截图](screenshots/010_PASS_SYS-04_读取存储位置.png) | [详情](cases/SYS-04.html) |
| SET-01 | 系统设置 | 读取完整设置 | GET | http://127.0.0.1:8011/api/v1/settings | 200 | 200 | 通过 | [截图](screenshots/011_PASS_SET-01_读取完整设置.png) | [详情](cases/SET-01.html) |
| SET-02 | 系统设置 | 读取模型设置 | GET | http://127.0.0.1:8011/api/v1/settings/models | 200 | 200 | 通过 | [截图](screenshots/012_PASS_SET-02_读取模型设置.png) | [详情](cases/SET-02.html) |
| SET-03 | 系统设置 | 保存相同模型配置 | PUT | http://127.0.0.1:8011/api/v1/settings/models | 200 | 200 | 通过 | [截图](screenshots/013_PASS_SET-03_保存相同模型配置.png) | [详情](cases/SET-03.html) |
| SET-04 | 系统设置 | 掩码密钥不被覆盖 | PUT | http://127.0.0.1:8011/api/v1/settings/models | 200 | 200 | 通过 | [截图](screenshots/014_PASS_SET-04_掩码密钥不被覆盖.png) | [详情](cases/SET-04.html) |
| SET-05 | 系统设置 | 测试大模型连接 | POST | http://127.0.0.1:8011/api/v1/settings/models/test | 200 | 200 | 通过 | [截图](screenshots/015_PASS_SET-05_测试大模型连接.png) | [详情](cases/SET-05.html) |
| SET-06 | 系统设置 | 测试向量服务连接 | POST | http://127.0.0.1:8011/api/v1/settings/models/test | 200 | 200 | 通过 | [截图](screenshots/016_PASS_SET-06_测试向量服务连接.png) | [详情](cases/SET-06.html) |
| SET-07 | 系统设置 | 测试目标参数非法 | POST | http://127.0.0.1:8011/api/v1/settings/models/test | 422 | 422 | 通过 | [截图](screenshots/017_PASS_SET-07_测试目标参数非法.png) | [详情](cases/SET-07.html) |
| SET-08 | 系统设置 | 错误 LLM Key 不伪造成功 | POST | http://127.0.0.1:8011/api/v1/settings/models/test | 200 | 200 | 通过 | [截图](screenshots/018_PASS_SET-08_错误_LLM_Key_不伪造成功.png) | [详情](cases/SET-08.html) |
| SET-09 | 系统设置 | 错误 Embedding Key 不降级 | POST | http://127.0.0.1:8011/api/v1/settings/models/test | 200 | 200 | 通过 | [截图](screenshots/019_PASS_SET-09_错误_Embedding_Key_不降级.png) | [详情](cases/SET-09.html) |
| SET-10 | 系统设置 | chunk_size 下边界校验 | PUT | http://127.0.0.1:8011/api/v1/settings | 422 | 422 | 通过 | [截图](screenshots/020_PASS_SET-10_chunk_size_下边界校验.png) | [详情](cases/SET-10.html) |
| SET-11 | 系统设置 | chunk_size 上边界校验 | PUT | http://127.0.0.1:8011/api/v1/settings | 422 | 422 | 通过 | [截图](screenshots/021_PASS_SET-11_chunk_size_上边界校验.png) | [详情](cases/SET-11.html) |
| SET-12 | 系统设置 | chunk_size 合法边界值 | PUT | http://127.0.0.1:8011/api/v1/settings | 200 | 200 | 通过 | [截图](screenshots/022_PASS_SET-12_chunk_size_合法边界值.png) | [详情](cases/SET-12.html) |
| SET-13 | 系统设置 | chunk_overlap 边界校验 | PUT | http://127.0.0.1:8011/api/v1/settings | 422 | 422 | 通过 | [截图](screenshots/023_PASS_SET-13_chunk_overlap_边界校验.png) | [详情](cases/SET-13.html) |
| SET-14 | 系统设置 | default_top_k 边界校验 | PUT | http://127.0.0.1:8011/api/v1/settings | 422 | 422 | 通过 | [截图](screenshots/024_PASS_SET-14_default_top_k_边界校验.png) | [详情](cases/SET-14.html) |
| SET-15 | 系统设置 | max_upload_mb 边界校验 | PUT | http://127.0.0.1:8011/api/v1/settings | 422 | 422 | 通过 | [截图](screenshots/025_PASS_SET-15_max_upload_mb_边界校验.png) | [详情](cases/SET-15.html) |
| SET-16 | 系统设置 | RAG 拒答阈值越界 | PUT | http://127.0.0.1:8011/api/v1/settings | 422 | 422 | 通过 | [截图](screenshots/026_PASS_SET-16_RAG_拒答阈值越界.png) | [详情](cases/SET-16.html) |
| SET-17 | 系统设置 | RAG top_k 越界 | PUT | http://127.0.0.1:8011/api/v1/settings | 422 | 422 | 通过 | [截图](screenshots/027_PASS_SET-17_RAG_top_k_越界.png) | [详情](cases/SET-17.html) |
| SET-18 | 系统设置 | 恢复原始处理参数 | PUT | http://127.0.0.1:8011/api/v1/settings | 200 | 200 | 通过 | [截图](screenshots/028_PASS_SET-18_恢复原始处理参数.png) | [详情](cases/SET-18.html) |
| DOC-01 | 文档管理 | 文档列表分页 | GET | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/029_PASS_DOC-01_文档列表分页.png) | [详情](cases/DOC-01.html) |
| DOC-02 | 文档管理 | 分页参数生效 | GET | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/030_PASS_DOC-02_分页参数生效.png) | [详情](cases/DOC-02.html) |
| DOC-03 | 文档管理 | 按状态筛选 | GET | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/031_PASS_DOC-03_按状态筛选.png) | [详情](cases/DOC-03.html) |
| DOC-04 | 文档管理 | 按文件类型筛选 | GET | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/032_PASS_DOC-04_按文件类型筛选.png) | [详情](cases/DOC-04.html) |
| DOC-05 | 文档管理 | 按关键词搜索文档 | GET | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/033_PASS_DOC-05_按关键词搜索文档.png) | [详情](cases/DOC-05.html) |
| DOC-06 | 文档管理 | 页码非法校验 | GET | http://127.0.0.1:8011/api/v1/documents | 422 | 422 | 通过 | [截图](screenshots/034_PASS_DOC-06_页码非法校验.png) | [详情](cases/DOC-06.html) |
| DOC-07 | 文档管理 | 分页大小上限校验 | GET | http://127.0.0.1:8011/api/v1/documents | 422 | 422 | 通过 | [截图](screenshots/035_PASS_DOC-07_分页大小上限校验.png) | [详情](cases/DOC-07.html) |
| DOC-08 | 文档管理 | 索引汇总 | GET | http://127.0.0.1:8011/api/v1/documents/index-summary | 200 | 200 | 通过 | [截图](screenshots/036_PASS_DOC-08_索引汇总.png) | [详情](cases/DOC-08.html) |
| DOC-09 | 文档管理 | 读取文档详情 | GET | http://127.0.0.1:8011/api/v1/documents/71f8776d-e81e-4949-9a66-d9df0dbab55f | 200 | 200 | 通过 | [截图](screenshots/037_PASS_DOC-09_读取文档详情.png) | [详情](cases/DOC-09.html) |
| DOC-10 | 文档管理 | 文档不存在 | GET | http://127.0.0.1:8011/api/v1/documents/151986f0-b725-4b7a-b778-80494dfceceb | 404 | 404 | 通过 | [截图](screenshots/038_PASS_DOC-10_文档不存在.png) | [详情](cases/DOC-10.html) |
| DOC-11 | 文档管理 | 读取文档解析内容 | GET | http://127.0.0.1:8011/api/v1/documents/71f8776d-e81e-4949-9a66-d9df0dbab55f/content | 200 | 200 | 通过 | [截图](screenshots/039_PASS_DOC-11_读取文档解析内容.png) | [详情](cases/DOC-11.html) |
| DOC-12 | 文档管理 | 不存在文档的内容 | GET | http://127.0.0.1:8011/api/v1/documents/fc4dd61f-4465-456e-a6a8-ecae80cace2f/content | 404 | 404 | 通过 | [截图](screenshots/040_PASS_DOC-12_不存在文档的内容.png) | [详情](cases/DOC-12.html) |
| DOC-13 | 文档管理 | 原始文件预览 | GET | http://127.0.0.1:8011/api/v1/documents/71f8776d-e81e-4949-9a66-d9df0dbab55f/preview | 200 | 200 | 通过 | [截图](screenshots/041_PASS_DOC-13_原始文件预览.png) | [详情](cases/DOC-13.html) |
| DOC-14 | 文档管理 | 预览不存在文档 | GET | http://127.0.0.1:8011/api/v1/documents/7166ad4a-fcf2-410e-8f17-f876544ccc57/preview | 404 | 404 | 通过 | [截图](screenshots/042_PASS_DOC-14_预览不存在文档.png) | [详情](cases/DOC-14.html) |
| DOC-15 | 文档管理 | 上传 TXT 文档 | POST | http://127.0.0.1:8011/api/v1/documents/upload | 201 | 201 | 通过 | [截图](screenshots/043_PASS_DOC-15_上传_TXT_文档.png) | [详情](cases/DOC-15.html) |
| DOC-16 | 文档管理 | 上传后异步处理完成 | GET | http://127.0.0.1:8011/api/v1/documents/a9538bd8-9ab5-4403-88a3-e0e1a61dfbde | 200 | 200 | 通过 | [截图](screenshots/044_PASS_DOC-16_上传后异步处理完成.png) | [详情](cases/DOC-16.html) |
| DOC-17 | 文档管理 | 新文档可被语义检索 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/045_PASS_DOC-17_新文档可被语义检索.png) | [详情](cases/DOC-17.html) |
| DOC-18 | 文档管理 | 重复文件拦截 | POST | http://127.0.0.1:8011/api/v1/documents/upload | 409 | 409 | 通过 | [截图](screenshots/046_PASS_DOC-18_重复文件拦截.png) | [详情](cases/DOC-18.html) |
| DOC-19 | 文档管理 | 不支持的格式 | POST | http://127.0.0.1:8011/api/v1/documents/upload | 415 | 415 | 通过 | [截图](screenshots/047_PASS_DOC-19_不支持的格式.png) | [详情](cases/DOC-19.html) |
| DOC-20 | 文档管理 | 空文件校验 | POST | http://127.0.0.1:8011/api/v1/documents/upload | 422 | 422 | 通过 | [截图](screenshots/048_PASS_DOC-20_空文件校验.png) | [详情](cases/DOC-20.html) |
| DOC-21 | 文档管理 | 批量上传混合成功/失败 | POST | http://127.0.0.1:8011/api/v1/documents/batch-upload | 201 | 201 | 通过 | [截图](screenshots/049_PASS_DOC-21_批量上传混合成功_失败.png) | [详情](cases/DOC-21.html) |
| DOC-22 | 文档管理 | 批量上传文档处理完成 | GET | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/050_PASS_DOC-22_批量上传文档处理完成.png) | [详情](cases/DOC-22.html) |
| DOC-23 | 文档管理 | 批量上传缺少文件 | POST | http://127.0.0.1:8011/api/v1/documents/batch-upload | 422 | 422 | 通过 | [截图](screenshots/051_PASS_DOC-23_批量上传缺少文件.png) | [详情](cases/DOC-23.html) |
| DOC-24 | 文档管理 | 临时收紧上传上限 | PUT | http://127.0.0.1:8011/api/v1/settings | 200 | 200 | 通过 | [截图](screenshots/052_PASS_DOC-24_临时收紧上传上限.png) | [详情](cases/DOC-24.html) |
| DOC-25 | 文档管理 | 文件超过大小上限 | POST | http://127.0.0.1:8011/api/v1/documents/upload | 422 | 422 | 通过 | [截图](screenshots/053_PASS_DOC-25_文件超过大小上限.png) | [详情](cases/DOC-25.html) |
| DOC-26 | 文档管理 | 恢复上传上限 | PUT | http://127.0.0.1:8011/api/v1/settings | 200 | 200 | 通过 | [截图](screenshots/054_PASS_DOC-26_恢复上传上限.png) | [详情](cases/DOC-26.html) |
| DOC-27 | 文档管理 | 重新解析文档 | POST | http://127.0.0.1:8011/api/v1/documents/a9538bd8-9ab5-4403-88a3-e0e1a61dfbde/reprocess | 202 | 202 | 通过 | [截图](screenshots/055_PASS_DOC-27_重新解析文档.png) | [详情](cases/DOC-27.html) |
| DOC-28 | 文档管理 | 重新解析完成且块数稳定 | GET | http://127.0.0.1:8011/api/v1/documents/a9538bd8-9ab5-4403-88a3-e0e1a61dfbde | 200 | 200 | 通过 | [截图](screenshots/056_PASS_DOC-28_重新解析完成且块数稳定.png) | [详情](cases/DOC-28.html) |
| DOC-29 | 文档管理 | 重新解析不存在文档 | POST | http://127.0.0.1:8011/api/v1/documents/9b594ee9-e629-445d-ad5d-5fe660f65231/reprocess | 404 | 404 | 通过 | [截图](screenshots/057_PASS_DOC-29_重新解析不存在文档.png) | [详情](cases/DOC-29.html) |
| DOC-30 | 文档管理 | 删除批量文档 | DELETE | http://127.0.0.1:8011/api/v1/documents/38f7a309-a1b4-4cd8-ad7c-e1157bd653dc | 204 | 204 | 通过 | [截图](screenshots/058_PASS_DOC-30_删除批量文档.png) | [详情](cases/DOC-30.html) |
| DOC-31 | 文档管理 | 删除后文档不可见 | GET | http://127.0.0.1:8011/api/v1/documents/38f7a309-a1b4-4cd8-ad7c-e1157bd653dc | 404 | 404 | 通过 | [截图](screenshots/059_PASS_DOC-31_删除后文档不可见.png) | [详情](cases/DOC-31.html) |
| DOC-32 | 文档管理 | 删除文档同步清理向量 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/060_PASS_DOC-32_删除文档同步清理向量.png) | [详情](cases/DOC-32.html) |
| DOC-33 | 文档管理 | 删除第二个批量文档 | DELETE | http://127.0.0.1:8011/api/v1/documents/2c44b0d2-ba07-4294-a387-3e5a1f820f77 | 204 | 204 | 通过 | [截图](screenshots/061_PASS_DOC-33_删除第二个批量文档.png) | [详情](cases/DOC-33.html) |
| DOC-34 | 文档管理 | 删除不存在文档 | DELETE | http://127.0.0.1:8011/api/v1/documents/7cd0d450-43d4-4ce8-9750-56604af93c2d | 404 | 404 | 通过 | [截图](screenshots/062_PASS_DOC-34_删除不存在文档.png) | [详情](cases/DOC-34.html) |
| DOC-35 | 文档管理 | 索引计数与真实向量一致 | GET | http://127.0.0.1:8011/api/v1/documents/index-summary | 200 | 200 | 通过 | [截图](screenshots/063_PASS_DOC-35_索引计数与真实向量一致.png) | [详情](cases/DOC-35.html) |
| DOC-36 | 文档管理 | 文档详情索引状态回填 | GET | http://127.0.0.1:8011/api/v1/documents/a9538bd8-9ab5-4403-88a3-e0e1a61dfbde | 200 | 200 | 未通过 | [截图](screenshots/064_FAIL_DOC-36_文档详情索引状态回填.png) | [详情](cases/DOC-36.html) |
| TSK-01 | 任务中心 | 任务列表 | GET | http://127.0.0.1:8011/api/v1/tasks | 200 | 200 | 通过 | [截图](screenshots/065_PASS_TSK-01_任务列表.png) | [详情](cases/TSK-01.html) |
| TSK-02 | 任务中心 | 按状态筛选任务 | GET | http://127.0.0.1:8011/api/v1/tasks | 200 | 200 | 通过 | [截图](screenshots/066_PASS_TSK-02_按状态筛选任务.png) | [详情](cases/TSK-02.html) |
| TSK-03 | 任务中心 | 任务列表 limit 合法边界 | GET | http://127.0.0.1:8011/api/v1/tasks | 200 | 200 | 通过 | [截图](screenshots/067_PASS_TSK-03_任务列表_limit_合法边界.png) | [详情](cases/TSK-03.html) |
| TSK-04 | 任务中心 | 任务 limit 下界校验 | GET | http://127.0.0.1:8011/api/v1/tasks | 422 | 422 | 通过 | [截图](screenshots/068_PASS_TSK-04_任务_limit_下界校验.png) | [详情](cases/TSK-04.html) |
| TSK-05 | 任务中心 | 任务 limit 上界校验 | GET | http://127.0.0.1:8011/api/v1/tasks | 422 | 422 | 通过 | [截图](screenshots/069_PASS_TSK-05_任务_limit_上界校验.png) | [详情](cases/TSK-05.html) |
| TSK-06 | 任务中心 | 任务 offset 校验 | GET | http://127.0.0.1:8011/api/v1/tasks | 422 | 422 | 通过 | [截图](screenshots/070_PASS_TSK-06_任务_offset_校验.png) | [详情](cases/TSK-06.html) |
| TSK-07 | 任务中心 | 读取任务详情 | GET | http://127.0.0.1:8011/api/v1/tasks/96290fb5-20fc-44af-bf34-210ac3c22dae | 200 | 200 | 通过 | [截图](screenshots/071_PASS_TSK-07_读取任务详情.png) | [详情](cases/TSK-07.html) |
| TSK-08 | 任务中心 | 任务不存在 | GET | http://127.0.0.1:8011/api/v1/tasks/5b94cfe0-0559-4a54-8175-e916dae25c44 | 404 | 404 | 通过 | [截图](screenshots/072_PASS_TSK-08_任务不存在.png) | [详情](cases/TSK-08.html) |
| TSK-09 | 任务中心 | 已完成任务的 SSE 进度订阅 | GET | http://127.0.0.1:8011/api/v1/tasks/96290fb5-20fc-44af-bf34-210ac3c22dae/events | 200 | 200 | 通过 | [截图](screenshots/073_PASS_TSK-09_已完成任务的_SSE_进度订阅.png) | [详情](cases/TSK-09.html) |
| TSK-10 | 任务中心 | 重试已完成任务 | POST | http://127.0.0.1:8011/api/v1/tasks/96290fb5-20fc-44af-bf34-210ac3c22dae/retry | 202 | 202 | 通过 | [截图](screenshots/074_PASS_TSK-10_重试已完成任务.png) | [详情](cases/TSK-10.html) |
| TSK-11 | 任务中心 | 重试任务处理完成 | GET | http://127.0.0.1:8011/api/v1/documents/66ded2ab-71e0-45c6-be94-5f06ca1c3b49 | 200 | 200 | 通过 | [截图](screenshots/075_PASS_TSK-11_重试任务处理完成.png) | [详情](cases/TSK-11.html) |
| TSK-12 | 任务中心 | 重试不存在任务 | POST | http://127.0.0.1:8011/api/v1/tasks/59c68633-318c-4bfb-ab21-b18cc2381c99/retry | 404 | 404 | 通过 | [截图](screenshots/076_PASS_TSK-12_重试不存在任务.png) | [详情](cases/TSK-12.html) |
| TSK-13 | 任务中心 | 删除已完成任务 | DELETE | http://127.0.0.1:8011/api/v1/tasks/96290fb5-20fc-44af-bf34-210ac3c22dae | 204 | 204 | 通过 | [截图](screenshots/077_PASS_TSK-13_删除已完成任务.png) | [详情](cases/TSK-13.html) |
| TSK-14 | 任务中心 | 删除后任务不可见 | GET | http://127.0.0.1:8011/api/v1/tasks/96290fb5-20fc-44af-bf34-210ac3c22dae | 404 | 404 | 通过 | [截图](screenshots/078_PASS_TSK-14_删除后任务不可见.png) | [详情](cases/TSK-14.html) |
| TSK-15 | 任务中心 | 删除不存在任务 | DELETE | http://127.0.0.1:8011/api/v1/tasks/05279e33-51ed-40dd-b6a6-6bcf00ecf514 | 404 | 404 | 通过 | [截图](screenshots/079_PASS_TSK-15_删除不存在任务.png) | [详情](cases/TSK-15.html) |
| SEA-01 | 语义检索 | 真实语义检索 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/080_PASS_SEA-01_真实语义检索.png) | [详情](cases/SEA-01.html) |
| SEA-02 | 语义检索 | 语义相关性排序 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/081_PASS_SEA-02_语义相关性排序.png) | [详情](cases/SEA-02.html) |
| SEA-03 | 语义检索 | 空查询校验 | POST | http://127.0.0.1:8011/api/v1/search | 422 | 422 | 通过 | [截图](screenshots/082_PASS_SEA-03_空查询校验.png) | [详情](cases/SEA-03.html) |
| SEA-04 | 语义检索 | 超长查询校验 | POST | http://127.0.0.1:8011/api/v1/search | 422 | 422 | 通过 | [截图](screenshots/083_PASS_SEA-04_超长查询校验.png) | [详情](cases/SEA-04.html) |
| SEA-05 | 语义检索 | top_k 下界校验 | POST | http://127.0.0.1:8011/api/v1/search | 422 | 422 | 通过 | [截图](screenshots/084_PASS_SEA-05_top_k_下界校验.png) | [详情](cases/SEA-05.html) |
| SEA-06 | 语义检索 | top_k 上界校验 | POST | http://127.0.0.1:8011/api/v1/search | 422 | 422 | 通过 | [截图](screenshots/085_PASS_SEA-06_top_k_上界校验.png) | [详情](cases/SEA-06.html) |
| SEA-07 | 语义检索 | top_k 合法上边界 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/086_PASS_SEA-07_top_k_合法上边界.png) | [详情](cases/SEA-07.html) |
| SEA-08 | 语义检索 | 按文档 ID 过滤 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/087_PASS_SEA-08_按文档_ID_过滤.png) | [详情](cases/SEA-08.html) |
| SEA-09 | 语义检索 | 不存在的文档过滤 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/088_PASS_SEA-09_不存在的文档过滤.png) | [详情](cases/SEA-09.html) |
| SEA-10 | 语义检索 | 按文件类型过滤 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/089_PASS_SEA-10_按文件类型过滤.png) | [详情](cases/SEA-10.html) |
| SEA-11 | 语义检索 | 过滤类型错误校验 | POST | http://127.0.0.1:8011/api/v1/search | 422 | 422 | 通过 | [截图](screenshots/090_PASS_SEA-11_过滤类型错误校验.png) | [详情](cases/SEA-11.html) |
| SEA-12 | 语义检索 | 检索历史 | GET | http://127.0.0.1:8011/api/v1/search/history | 200 | 200 | 通过 | [截图](screenshots/091_PASS_SEA-12_检索历史.png) | [详情](cases/SEA-12.html) |
| SEA-13 | 语义检索 | 重建索引前状态 | GET | http://127.0.0.1:8011/api/v1/search/reindex/status | 200 | 200 | 通过 | [截图](screenshots/092_PASS_SEA-13_重建索引前状态.png) | [详情](cases/SEA-13.html) |
| SEA-14 | 语义检索 | 全量重建索引 | POST | http://127.0.0.1:8011/api/v1/search/reindex | 200 | 200 | 通过 | [截图](screenshots/093_PASS_SEA-14_全量重建索引.png) | [详情](cases/SEA-14.html) |
| SEA-15 | 语义检索 | 重建后索引状态 | GET | http://127.0.0.1:8011/api/v1/documents/index-summary | 200 | 200 | 通过 | [截图](screenshots/094_PASS_SEA-15_重建后索引状态.png) | [详情](cases/SEA-15.html) |
| SEA-16 | 语义检索 | 重建索引并发互斥 | POST | http://127.0.0.1:8011/api/v1/search/reindex | [200, 409] | [200, 409] | 通过 | [截图](screenshots/095_PASS_SEA-16_重建索引并发互斥.png) | [详情](cases/SEA-16.html) |
| SEA-17 | 语义检索 | 重建后检索仍可用 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/096_PASS_SEA-17_重建后检索仍可用.png) | [详情](cases/SEA-17.html) |
| CHAT-01 | 智能问答 | 创建默认会话 | POST | http://127.0.0.1:8011/api/v1/chat/sessions | 201 | 201 | 通过 | [截图](screenshots/097_PASS_CHAT-01_创建默认会话.png) | [详情](cases/CHAT-01.html) |
| CHAT-02 | 智能问答 | 创建指定标题会话 | POST | http://127.0.0.1:8011/api/v1/chat/sessions | 201 | 201 | 通过 | [截图](screenshots/098_PASS_CHAT-02_创建指定标题会话.png) | [详情](cases/CHAT-02.html) |
| CHAT-03 | 智能问答 | 会话标题长度校验 | POST | http://127.0.0.1:8011/api/v1/chat/sessions | 422 | 422 | 通过 | [截图](screenshots/099_PASS_CHAT-03_会话标题长度校验.png) | [详情](cases/CHAT-03.html) |
| CHAT-04 | 智能问答 | 会话列表分页 | GET | http://127.0.0.1:8011/api/v1/chat/sessions | 200 | 200 | 通过 | [截图](screenshots/100_PASS_CHAT-04_会话列表分页.png) | [详情](cases/CHAT-04.html) |
| CHAT-05 | 智能问答 | 会话页码校验 | GET | http://127.0.0.1:8011/api/v1/chat/sessions | 422 | 422 | 通过 | [截图](screenshots/101_PASS_CHAT-05_会话页码校验.png) | [详情](cases/CHAT-05.html) |
| CHAT-06 | 智能问答 | 会话分页大小校验 | GET | http://127.0.0.1:8011/api/v1/chat/sessions | 422 | 422 | 通过 | [截图](screenshots/102_PASS_CHAT-06_会话分页大小校验.png) | [详情](cases/CHAT-06.html) |
| CHAT-07 | 智能问答 | 读取会话详情 | GET | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea | 200 | 200 | 通过 | [截图](screenshots/103_PASS_CHAT-07_读取会话详情.png) | [详情](cases/CHAT-07.html) |
| CHAT-08 | 智能问答 | 会话不存在 | GET | http://127.0.0.1:8011/api/v1/chat/sessions/f8b853b6-5627-409e-8316-58795fb58465 | 404 | 404 | 通过 | [截图](screenshots/104_PASS_CHAT-08_会话不存在.png) | [详情](cases/CHAT-08.html) |
| CHAT-09 | 智能问答 | 非流式知识库问答 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 200 | 200 | 通过 | [截图](screenshots/105_PASS_CHAT-09_非流式知识库问答.png) | [详情](cases/CHAT-09.html) |
| CHAT-10 | 智能问答 | 空问题校验 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 422 | 422 | 通过 | [截图](screenshots/106_PASS_CHAT-10_空问题校验.png) | [详情](cases/CHAT-10.html) |
| CHAT-11 | 智能问答 | 超长问题校验 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 422 | 422 | 通过 | [截图](screenshots/107_PASS_CHAT-11_超长问题校验.png) | [详情](cases/CHAT-11.html) |
| CHAT-12 | 智能问答 | 问答 top_k 下界校验 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 422 | 422 | 通过 | [截图](screenshots/108_PASS_CHAT-12_问答_top_k_下界校验.png) | [详情](cases/CHAT-12.html) |
| CHAT-13 | 智能问答 | 问答 top_k 上界校验 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 422 | 422 | 通过 | [截图](screenshots/109_PASS_CHAT-13_问答_top_k_上界校验.png) | [详情](cases/CHAT-13.html) |
| CHAT-14 | 智能问答 | 问答会话不存在 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/e462e76d-283d-412f-b27d-536864c9aab3/messages | 404 | 404 | 通过 | [截图](screenshots/110_PASS_CHAT-14_问答会话不存在.png) | [详情](cases/CHAT-14.html) |
| CHAT-15 | 智能问答 | 无关问题拒绝编造 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 200 | 200 | 通过 | [截图](screenshots/111_PASS_CHAT-15_无关问题拒绝编造.png) | [详情](cases/CHAT-15.html) |
| CHAT-16 | 智能问答 | 流式知识库问答 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 200 | 200 | 通过 | [截图](screenshots/112_PASS_CHAT-16_流式知识库问答.png) | [详情](cases/CHAT-16.html) |
| CHAT-17 | 智能问答 | 流式问答的拒答保护 | POST | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea/messages | 200 | 200 | 通过 | [截图](screenshots/113_PASS_CHAT-17_流式问答的拒答保护.png) | [详情](cases/CHAT-17.html) |
| CHAT-18 | 智能问答 | 会话消息与引用持久化 | GET | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea | 200 | 200 | 通过 | [截图](screenshots/114_PASS_CHAT-18_会话消息与引用持久化.png) | [详情](cases/CHAT-18.html) |
| CHAT-19 | 智能问答 | 删除会话 | DELETE | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea | 204 | 204 | 通过 | [截图](screenshots/115_PASS_CHAT-19_删除会话.png) | [详情](cases/CHAT-19.html) |
| CHAT-20 | 智能问答 | 删除后会话不可见 | GET | http://127.0.0.1:8011/api/v1/chat/sessions/72061525-ca57-406b-80f6-1cf6b91af2ea | 404 | 404 | 通过 | [截图](screenshots/116_PASS_CHAT-20_删除后会话不可见.png) | [详情](cases/CHAT-20.html) |
| CHAT-21 | 智能问答 | 删除不存在会话 | DELETE | http://127.0.0.1:8011/api/v1/chat/sessions/c356f44e-79d7-4604-bbeb-638b038742d3 | 404 | 404 | 通过 | [截图](screenshots/117_PASS_CHAT-21_删除不存在会话.png) | [详情](cases/CHAT-21.html) |
| ANA-01 | 多文档分析 | 多文档对比分析 | POST | http://127.0.0.1:8011/api/v1/analysis | 200 | 200 | 通过 | [截图](screenshots/118_PASS_ANA-01_多文档对比分析.png) | [详情](cases/ANA-01.html) |
| ANA-02 | 多文档分析 | 单文档智能总结 | POST | http://127.0.0.1:8011/api/v1/analysis/summary | 200 | 200 | 通过 | [截图](screenshots/119_PASS_ANA-02_单文档智能总结.png) | [详情](cases/ANA-02.html) |
| ANA-03 | 多文档分析 | 空文档列表校验 | POST | http://127.0.0.1:8011/api/v1/analysis | 422 | 422 | 通过 | [截图](screenshots/120_PASS_ANA-03_空文档列表校验.png) | [详情](cases/ANA-03.html) |
| ANA-04 | 多文档分析 | 文档数量上限校验 | POST | http://127.0.0.1:8011/api/v1/analysis | 422 | 422 | 通过 | [截图](screenshots/121_PASS_ANA-04_文档数量上限校验.png) | [详情](cases/ANA-04.html) |
| ANA-05 | 多文档分析 | 分析文档不存在 | POST | http://127.0.0.1:8011/api/v1/analysis | 404 | 404 | 通过 | [截图](screenshots/122_PASS_ANA-05_分析文档不存在.png) | [详情](cases/ANA-05.html) |
| ANA-06 | 多文档分析 | 分析主题为空 | POST | http://127.0.0.1:8011/api/v1/analysis | 422 | 422 | 通过 | [截图](screenshots/123_PASS_ANA-06_分析主题为空.png) | [详情](cases/ANA-06.html) |
| ANA-07 | 多文档分析 | 分析主题超长 | POST | http://127.0.0.1:8011/api/v1/analysis | 422 | 422 | 通过 | [截图](screenshots/124_PASS_ANA-07_分析主题超长.png) | [详情](cases/ANA-07.html) |
| ANA-08 | 多文档分析 | 分析 top_k 下界 | POST | http://127.0.0.1:8011/api/v1/analysis | 422 | 422 | 通过 | [截图](screenshots/125_PASS_ANA-08_分析_top_k_下界.png) | [详情](cases/ANA-08.html) |
| ANA-09 | 多文档分析 | 分析 top_k 上界 | POST | http://127.0.0.1:8011/api/v1/analysis | 422 | 422 | 通过 | [截图](screenshots/126_PASS_ANA-09_分析_top_k_上界.png) | [详情](cases/ANA-09.html) |
| ANA-10 | 多文档分析 | 无关主题的拒答保护 | POST | http://127.0.0.1:8011/api/v1/analysis | 200 | 200 | 通过 | [截图](screenshots/127_PASS_ANA-10_无关主题的拒答保护.png) | [详情](cases/ANA-10.html) |
| REP-01 | 研究报告 | 生成结构化研究报告 | POST | http://127.0.0.1:8011/api/v1/reports/generate | 200 | 200 | 通过 | [截图](screenshots/128_PASS_REP-01_生成结构化研究报告.png) | [详情](cases/REP-01.html) |
| REP-02 | 研究报告 | 报告历史列表 | GET | http://127.0.0.1:8011/api/v1/reports | 200 | 200 | 通过 | [截图](screenshots/129_PASS_REP-02_报告历史列表.png) | [详情](cases/REP-02.html) |
| REP-03 | 研究报告 | 报告列表 limit 下界 | GET | http://127.0.0.1:8011/api/v1/reports | 422 | 422 | 通过 | [截图](screenshots/130_PASS_REP-03_报告列表_limit_下界.png) | [详情](cases/REP-03.html) |
| REP-04 | 研究报告 | 报告列表 limit 上界 | GET | http://127.0.0.1:8011/api/v1/reports | 422 | 422 | 通过 | [截图](screenshots/131_PASS_REP-04_报告列表_limit_上界.png) | [详情](cases/REP-04.html) |
| REP-05 | 研究报告 | 读取报告详情 | GET | http://127.0.0.1:8011/api/v1/reports/6b7a639b4a054a27bcb00d23ee5cd19b | 200 | 200 | 通过 | [截图](screenshots/132_PASS_REP-05_读取报告详情.png) | [详情](cases/REP-05.html) |
| REP-06 | 研究报告 | 非法报告 ID | GET | http://127.0.0.1:8011/api/v1/reports/not-a-valid-id | 404 | 404 | 通过 | [截图](screenshots/133_PASS_REP-06_非法报告_ID.png) | [详情](cases/REP-06.html) |
| REP-07 | 研究报告 | 报告不存在 | GET | http://127.0.0.1:8011/api/v1/reports/e3dba61a9caa4fcbb85c209328e1cd26 | 404 | 404 | 通过 | [截图](screenshots/134_PASS_REP-07_报告不存在.png) | [详情](cases/REP-07.html) |
| REP-08 | 研究报告 | 下载 Markdown 报告 | GET | http://127.0.0.1:8011/api/v1/reports/6b7a639b4a054a27bcb00d23ee5cd19b/download | 200 | 200 | 通过 | [截图](screenshots/135_PASS_REP-08_下载_Markdown_报告.png) | [详情](cases/REP-08.html) |
| REP-09 | 研究报告 | 下载 DOCX 报告 | GET | http://127.0.0.1:8011/api/v1/reports/6b7a639b4a054a27bcb00d23ee5cd19b/download | 200 | 200 | 通过 | [截图](screenshots/136_PASS_REP-09_下载_DOCX_报告.png) | [详情](cases/REP-09.html) |
| REP-10 | 研究报告 | 导出格式白名单 | GET | http://127.0.0.1:8011/api/v1/reports/6b7a639b4a054a27bcb00d23ee5cd19b/download | 422 | 422 | 通过 | [截图](screenshots/137_PASS_REP-10_导出格式白名单.png) | [详情](cases/REP-10.html) |
| REP-11 | 研究报告 | 下载不存在报告 | GET | http://127.0.0.1:8011/api/v1/reports/ce317e2a58af4b729b03ff726ffeba84/download | 404 | 404 | 通过 | [截图](screenshots/138_PASS_REP-11_下载不存在报告.png) | [详情](cases/REP-11.html) |
| REP-12 | 研究报告 | 生成时文档列表为空 | POST | http://127.0.0.1:8011/api/v1/reports/generate | 422 | 422 | 通过 | [截图](screenshots/139_PASS_REP-12_生成时文档列表为空.png) | [详情](cases/REP-12.html) |
| REP-13 | 研究报告 | 生成时文档不存在 | POST | http://127.0.0.1:8011/api/v1/reports/generate | 404 | 404 | 通过 | [截图](screenshots/140_PASS_REP-13_生成时文档不存在.png) | [详情](cases/REP-13.html) |
| REP-14 | 研究报告 | 生成主题为空 | POST | http://127.0.0.1:8011/api/v1/reports/generate | 422 | 422 | 通过 | [截图](screenshots/141_PASS_REP-14_生成主题为空.png) | [详情](cases/REP-14.html) |
| REP-15 | 研究报告 | 无关主题的报告拒答保护 | POST | http://127.0.0.1:8011/api/v1/reports/generate | 200 | 200 | 通过 | [截图](screenshots/142_PASS_REP-15_无关主题的报告拒答保护.png) | [详情](cases/REP-15.html) |
| BKP-01 | 备份恢复 | 创建默认备份 | POST | http://127.0.0.1:8011/api/v1/backup | 200 | 200 | 通过 | [截图](screenshots/143_PASS_BKP-01_创建默认备份.png) | [详情](cases/BKP-01.html) |
| BKP-02 | 备份恢复 | 备份列表 | GET | http://127.0.0.1:8011/api/v1/backup | 200 | 200 | 通过 | [截图](screenshots/144_PASS_BKP-02_备份列表.png) | [详情](cases/BKP-02.html) |
| BKP-03 | 备份恢复 | 下载备份包 | GET | http://127.0.0.1:8011/api/v1/backup/knowflow-backup-20261122-195920.zip/download | 200 | 200 | 通过 | [截图](screenshots/145_PASS_BKP-03_下载备份包.png) | [详情](cases/BKP-03.html) |
| BKP-04 | 备份恢复 | 校验备份完整性 | POST | http://127.0.0.1:8011/api/v1/backup/validate | 200 | 200 | 通过 | [截图](screenshots/146_PASS_BKP-04_校验备份完整性.png) | [详情](cases/BKP-04.html) |
| BKP-05 | 备份恢复 | 校验非 ZIP 文件 | POST | http://127.0.0.1:8011/api/v1/backup/validate | 422 | 422 | 通过 | [截图](screenshots/147_PASS_BKP-05_校验非_ZIP_文件.png) | [详情](cases/BKP-05.html) |
| BKP-06 | 备份恢复 | 校验缺少 manifest 的 ZIP | POST | http://127.0.0.1:8011/api/v1/backup/validate | 422 | 422 | 通过 | [截图](screenshots/148_PASS_BKP-06_校验缺少_manifest_的_ZIP.png) | [详情](cases/BKP-06.html) |
| BKP-07 | 备份恢复 | 校验空备份文件 | POST | http://127.0.0.1:8011/api/v1/backup/validate | 422 | 422 | 通过 | [截图](screenshots/149_PASS_BKP-07_校验空备份文件.png) | [详情](cases/BKP-07.html) |
| BKP-08 | 备份恢复 | 下载不存在的备份 | GET | http://127.0.0.1:8011/api/v1/backup/not-exist-20260101.zip/download | 404 | 404 | 通过 | [截图](screenshots/150_PASS_BKP-08_下载不存在的备份.png) | [详情](cases/BKP-08.html) |
| BKP-09 | 备份恢复 | 备份文件名路径穿越防护 | GET | http://127.0.0.1:8011/api/v1/backup/..%2F..%2Fevil.zip/download | [200, 404] | 200 | 通过 | [截图](screenshots/151_PASS_BKP-09_备份文件名路径穿越防护.png) | [详情](cases/BKP-09.html) |
| BKP-10 | 备份恢复 | 创建含密钥备份（可选） | POST | http://127.0.0.1:8011/api/v1/backup | 200 | 200 | 通过 | [截图](screenshots/152_PASS_BKP-10_创建含密钥备份（可选）.png) | [详情](cases/BKP-10.html) |
| BKP-11 | 备份恢复 | 默认备份不含 API Key | ZIP 内部检查 | C:\Users\foolsama\AppData\Local\Temp\knowflow_api_test\default_backup.zip | False | 文件检查 | 通过 | [截图](screenshots/153_PASS_BKP-11_默认备份不含_API_Key.png) | [详情](cases/BKP-11.html) |
| BKP-12 | 备份恢复 | 显式含密钥备份行为 | ZIP 内部检查 | C:\Users\foolsama\AppData\Local\Temp\knowflow_api_test\run_root\custom_data\backups\knowflow-backup-20261122-195921.zip | True | 文件检查 | 通过 | [截图](screenshots/154_PASS_BKP-12_显式含密钥备份行为.png) | [详情](cases/BKP-12.html) |
| BKP-19 | 备份恢复 | 连续备份文件名唯一性 | POST | http://127.0.0.1:8011/api/v1/backup | 两个不同的文件名 | [200, 200] | 未通过 | [截图](screenshots/155_FAIL_BKP-19_连续备份文件名唯一性.png) | [详情](cases/BKP-19.html) |
| BKP-13 | 备份恢复 | 从备份恢复数据 | POST | http://127.0.0.1:8011/api/v1/backup/restore | 200 | 422 | 未通过 | [截图](screenshots/156_FAIL_BKP-13_从备份恢复数据.png) | [详情](cases/BKP-13.html) |
| BKP-14 | 备份恢复 | 恢复后文档数据完整 | GET | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/157_PASS_BKP-14_恢复后文档数据完整.png) | [详情](cases/BKP-14.html) |
| BKP-15 | 备份恢复 | 恢复后保留当前密钥 | GET | http://127.0.0.1:8011/api/v1/settings/models | 200 | 200 | 通过 | [截图](screenshots/158_PASS_BKP-15_恢复后保留当前密钥.png) | [详情](cases/BKP-15.html) |
| BKP-16 | 备份恢复 | 恢复后索引可用 | GET | http://127.0.0.1:8011/api/v1/documents/index-summary | 200 | 200 | 通过 | [截图](screenshots/159_PASS_BKP-16_恢复后索引可用.png) | [详情](cases/BKP-16.html) |
| BKP-17 | 备份恢复 | 恢复后语义检索可用 | POST | http://127.0.0.1:8011/api/v1/search | 200 | 200 | 通过 | [截图](screenshots/160_PASS_BKP-17_恢复后语义检索可用.png) | [详情](cases/BKP-17.html) |
| BKP-18 | 备份恢复 | 恢复后健康检查 | GET | http://127.0.0.1:8011/api/v1/system/health | 200 | 200 | 通过 | [截图](screenshots/161_PASS_BKP-18_恢复后健康检查.png) | [详情](cases/BKP-18.html) |
| STO-01 | 存储位置 | 空目录校验 | PUT | http://127.0.0.1:8011/api/v1/system/storage | 422 | 422 | 通过 | [截图](screenshots/162_PASS_STO-01_空目录校验.png) | [详情](cases/STO-01.html) |
| STO-02 | 存储位置 | 相对路径校验 | PUT | http://127.0.0.1:8011/api/v1/system/storage | 422 | 422 | 通过 | [截图](screenshots/163_PASS_STO-02_相对路径校验.png) | [详情](cases/STO-02.html) |
| STO-03 | 存储位置 | 当前目录重复校验 | PUT | http://127.0.0.1:8011/api/v1/system/storage | 422 | 422 | 通过 | [截图](screenshots/164_PASS_STO-03_当前目录重复校验.png) | [详情](cases/STO-03.html) |
| STO-04 | 存储位置 | 禁止切入子目录 | PUT | http://127.0.0.1:8011/api/v1/system/storage | 422 | 422 | 通过 | [截图](screenshots/165_PASS_STO-04_禁止切入子目录.png) | [详情](cases/STO-04.html) |
| STO-05 | 存储位置 | 目标已有知识库数据 | PUT | http://127.0.0.1:8011/api/v1/system/storage | 422 | 422 | 通过 | [截图](screenshots/166_PASS_STO-05_目标已有知识库数据.png) | [详情](cases/STO-05.html) |
| STO-06 | 存储位置 | 切换到新的空目录 | PUT | http://127.0.0.1:8011/api/v1/system/storage | 200 | 200 | 通过 | [截图](screenshots/167_PASS_STO-06_切换到新的空目录.png) | [详情](cases/STO-06.html) |
| STO-07 | 存储位置 | 读取待生效的存储位置 | GET | http://127.0.0.1:8011/api/v1/system/storage | 200 | 200 | 通过 | [截图](screenshots/168_PASS_STO-07_读取待生效的存储位置.png) | [详情](cases/STO-07.html) |
| STO-08 | 存储位置 | 恢复默认存储位置 | DELETE | http://127.0.0.1:8011/api/v1/system/storage | 200 | 200 | 通过 | [截图](screenshots/169_PASS_STO-08_恢复默认存储位置.png) | [详情](cases/STO-08.html) |
| STO-09 | 存储位置 | 恢复后自定义标记已清除 | GET | http://127.0.0.1:8011/api/v1/system/storage | 200 | 200 | 通过 | [截图](screenshots/170_PASS_STO-09_恢复后自定义标记已清除.png) | [详情](cases/STO-09.html) |
| X-01 | 通用协议 | 根路径返回前端页面 | GET | http://127.0.0.1:8011/ | 200 | 200 | 通过 | [截图](screenshots/171_PASS_X-01_根路径返回前端页面.png) | [详情](cases/X-01.html) |
| X-02 | 通用协议 | 未知 API 路径 | GET | http://127.0.0.1:8011/api/v1/unknown-endpoint | 404 | 200 | 未通过 | [截图](screenshots/172_FAIL_X-02_未知_API_路径.png) | [详情](cases/X-02.html) |
| X-03 | 通用协议 | CORS 预检 | OPTIONS | http://127.0.0.1:8011/api/v1/documents | 200 | 200 | 通过 | [截图](screenshots/173_PASS_X-03_CORS_预检.png) | [详情](cases/X-03.html) |
| X-04 | 通用协议 | 不支持的 HTTP 方法 | PATCH | http://127.0.0.1:8011/api/v1/documents | 405 | 405 | 通过 | [截图](screenshots/174_PASS_X-04_不支持的_HTTP_方法.png) | [详情](cases/X-04.html) |
| X-05 | 通用协议 | 畸形 JSON 请求体 | POST | http://127.0.0.1:8011/api/v1/search | 422 | 422 | 通过 | [截图](screenshots/175_PASS_X-05_畸形_JSON_请求体.png) | [详情](cases/X-05.html) |
| X-06 | 通用协议 | OpenAPI 文档可访问 | GET | http://127.0.0.1:8011/docs | 200 | 200 | 通过 | [截图](screenshots/176_PASS_X-06_OpenAPI_文档可访问.png) | [详情](cases/X-06.html) |
| X-07 | 通用协议 | OpenAPI schema 完整 | GET | http://127.0.0.1:8011/openapi.json | 200 | 200 | 通过 | [截图](screenshots/177_PASS_X-07_OpenAPI_schema_完整.png) | [详情](cases/X-07.html) |

## 八、附件

- `screenshots/`：177 张逐项测试截图，另含 2 张总览与 Swagger 接口清单截图；文件名格式为 `序号_结果_用例ID_测试项.png`。
- `raw/`：每个用例一份完整原始响应 JSON。
- `index.html`：可视化测试总览。
- `all-cases.html`：全部用例明细表。
- `cases/`：每个用例的请求、响应、状态码、断言与等价 cURL 证据页。

## 九、说明

- 本报告中的状态码、响应体、耗时均来自实际 HTTP 调用，未人工修改。
- 备份恢复用例失败后已确认数据自动回滚：文档数、索引状态、检索与健康检查均正常。
- 外部模型调用使用测试专用无效 Key 的用例仅验证鉴权失败路径，不涉及真实密钥泄露。
