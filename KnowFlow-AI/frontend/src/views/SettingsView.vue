<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'
import type {
  BackupInfo,
  BackupManifest,
  ModelSettings,
  ProcessingSettings,
  RagSettings,
  SystemInfo,
} from '@/types'
const loading = ref(false)
const savingModels = ref(false)
const savingProcessing = ref(false)
const savingRag = ref(false)
const testing = reactive({ llm: false, embedding: false })
const reindexing = ref(false)
const info = ref<SystemInfo | null>(null)
const flags = reactive({ llmHasKey: false, embeddingHasKey: false, degraded: true, llmConfigured: false })
const backups = ref<BackupInfo[]>([])
const backupLoading = ref(false)
const creatingBackup = ref(false)
const restoring = ref(false)
const includeSecrets = ref(false)
const backupFile = ref<File | null>(null)
const backupManifest = ref<BackupManifest | null>(null)
const validatingBackup = ref(false)
const storageVisible = ref(false)
const storagePath = ref('')
const storageMigrate = ref(true)
const savingStorage = ref(false)

const llm = reactive({
  llm_provider: 'openai_compatible',
  llm_base_url: 'https://api.deepseek.com/v1',
  llm_model: 'deepseek-chat',
  llm_api_key: '',
})

const embedding = reactive({
  embedding_provider: 'openai_compatible',
  embedding_base_url: '',
  embedding_model: '',
  embedding_api_key: '',
  embedding_dim: 1024,
})

const processing = reactive<ProcessingSettings>({
  chunk_size: 800,
  chunk_overlap: 120,
  default_top_k: 5,
  max_upload_mb: 200,
})

const rag = reactive<RagSettings>({
  rag_top_k: 5,
  rag_min_score: 0.35,
  rag_context_chars: 6000,
})

function applyModels(models: ModelSettings) {
  llm.llm_provider = models.llm_provider
  llm.llm_base_url = models.llm_base_url
  llm.llm_model = models.llm_model
  llm.llm_api_key = ''
  embedding.embedding_provider = models.embedding_provider
  embedding.embedding_base_url = models.embedding_base_url
  embedding.embedding_model = models.embedding_model
  embedding.embedding_api_key = ''
  embedding.embedding_dim = models.embedding_dim
  flags.llmHasKey = models.llm_has_key
  flags.llmConfigured = models.llm_configured
  flags.embeddingHasKey = models.embedding_has_key
  flags.degraded = models.embedding_degraded
}

async function load() {
  loading.value = true
  try {
    const [settings, systemInfo] = await Promise.all([api.getSettings(), api.systemInfo()])
    applyModels(settings.models)
    Object.assign(processing, settings.processing)
    Object.assign(rag, settings.rag)
    info.value = systemInfo
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
  loadBackups()
}

async function saveModels() {
  savingModels.value = true
  try {
    const payload: Record<string, string | number> = {
      llm_provider: llm.llm_provider,
      llm_base_url: llm.llm_base_url,
      llm_model: llm.llm_model,
      embedding_provider: embedding.embedding_provider,
      embedding_base_url: embedding.embedding_base_url,
      embedding_model: embedding.embedding_model,
      embedding_dim: embedding.embedding_dim,
    }
    if (llm.llm_api_key.trim()) payload.llm_api_key = llm.llm_api_key.trim()
    if (embedding.embedding_api_key.trim()) payload.embedding_api_key = embedding.embedding_api_key.trim()

    const models = await api.updateModelSettings(payload)
    applyModels(models)
    info.value = await api.systemInfo()
    ElMessage.success('模型配置已保存。若更换了向量模型，请重建索引。')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    savingModels.value = false
  }
}

async function saveProcessing() {
  savingProcessing.value = true
  try {
    const settings = await api.updateProcessing({ ...processing })
    Object.assign(processing, settings.processing)
    ElMessage.success('处理参数已保存，新任务将按新参数执行')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    savingProcessing.value = false
  }
}

async function saveRag() {
  savingRag.value = true
  try {
    const settings = await api.updateRag({ ...rag })
    Object.assign(rag, settings.rag)
    ElMessage.success('RAG 参数已保存，将用于后续问答、分析与报告')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    savingRag.value = false
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function loadBackups() {
  backupLoading.value = true
  try {
    backups.value = await api.listBackups()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    backupLoading.value = false
  }
}

async function createBackup() {
  if (includeSecrets.value) {
    try {
      await ElMessageBox.confirm(
        '包含 API Key 的备份仅适合在本机保存，请勿分享给他人。确认继续？',
        '包含敏感信息',
        { type: 'warning', confirmButtonText: '仍要备份', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  creatingBackup.value = true
  try {
    const backup = await api.createBackup(includeSecrets.value)
    ElMessage.success(`备份完成：${backup.name}`)
    loadBackups()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    creatingBackup.value = false
  }
}

function onBackupSelected(file: File): boolean {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('请选择 .zip 格式的备份文件')
    return false
  }
  backupFile.value = file
  backupManifest.value = null
  validateBackup()
  return false
}

async function validateBackup() {
  if (!backupFile.value) return
  validatingBackup.value = true
  try {
    backupManifest.value = await api.validateBackup(backupFile.value)
    ElMessage.success('备份校验通过，可执行恢复')
  } catch (error) {
    backupManifest.value = null
    ElMessage.error((error as Error).message)
  } finally {
    validatingBackup.value = false
  }
}

async function restoreBackup() {
  if (!backupFile.value) {
    ElMessage.warning('请先选择备份文件')
    return
  }
  try {
    await ElMessageBox.confirm(
      '恢复会覆盖当前知识库数据。系统会先自动备份当前数据，恢复失败会自动回滚。确认继续？',
      '恢复数据',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  restoring.value = true
  try {
    const result = await api.restoreBackup(backupFile.value)
    ElMessage.success(
      `${result.message}（${result.document_count} 份资料）。恢复前备份：${result.pre_restore_backup}`,
    )
    backupFile.value = null
    backupManifest.value = null
    await load()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    restoring.value = false
  }
}

async function downloadBackup(name: string) {
  try {
    const response = await fetch(api.backupDownloadUrl(name))
    if (!response.ok) throw new Error(`下载失败（${response.status}）`)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = name
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function test(target: 'llm' | 'embedding') {
  testing[target] = true
  try {
    const payload: Record<string, string | number> =
      target === 'llm'
        ? {
            llm_base_url: llm.llm_base_url,
            llm_model: llm.llm_model,
          }
        : {
            embedding_base_url: embedding.embedding_base_url,
            embedding_model: embedding.embedding_model,
            embedding_dim: embedding.embedding_dim,
          }
    const key = target === 'llm' ? llm.llm_api_key.trim() : embedding.embedding_api_key.trim()
    if (key) payload[`${target}_api_key`] = key

    const result = await api.testModel(target, payload)
    if (result.ok) {
      ElMessage.success(`${result.message}（${result.latency_ms} ms）`)
    } else {
      ElMessage.error(result.message)
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    testing[target] = false
  }
}

async function reindex() {
  try {
    await ElMessageBox.confirm(
      '将调用当前 Embedding 服务重建全部索引。新索引完整校验通过后才会替换旧索引，重建期间暂停检索。确认继续？',
      '重建向量索引',
      { type: 'warning', confirmButtonText: '开始重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  reindexing.value = true
  try {
    const result = await api.reindex()
    ElMessage.success(`重建完成：${result.chunks} 个文本块，${result.dimension} 维`)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    reindexing.value = false
    info.value = await api.systemInfo()
  }
}

onMounted(load)

function openStorageDialog() {
  storagePath.value = info.value?.data_dir || ''
  storageVisible.value = true
}

async function saveStorage() {
  if (!storagePath.value.trim()) {
    ElMessage.warning('请填写新的存储目录')
    return
  }
  savingStorage.value = true
  try {
    const result = await api.updateStorage(storagePath.value.trim(), storageMigrate.value)
    storageVisible.value = false
    info.value = await api.systemInfo()
    await ElMessageBox.alert(result.message, '存储位置已保存', { confirmButtonText: '知道了' })
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    savingStorage.value = false
  }
}

async function resetStorage() {
  try {
    await ElMessageBox.confirm(
      '将恢复为程序目录下的默认 data 目录，并把当前数据迁移过去。确认继续？',
      '恢复默认存储位置',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  savingStorage.value = true
  try {
    const result = await api.resetStorage(true)
    storageVisible.value = false
    await ElMessageBox.alert(result.message, '已恢复默认目录', { confirmButtonText: '知道了' })
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    savingStorage.value = false
  }
}
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div>
        <h1 class="page-title">系统设置</h1>
        <p class="page-desc">模型密钥只保存在本机后端，前端不会持有任何 API Key。</p>
      </div>
      <el-button
        :loading="reindexing"
        :disabled="info?.retrieval_mode !== 'semantic'"
        @click="reindex"
      >重建向量索引</el-button>
    </div>

    <el-alert
      v-if="info && (flags.degraded || !flags.llmConfigured)"
      type="warning"
      :closable="false"
      show-icon
      class="availability"
      title="部分 AI 功能当前不可用"
    >
      <template #default>
        <p v-if="flags.degraded">
          未配置 Embedding：语义检索、向量索引、问答、分析、总结与报告均不可用。
        </p>
        <p v-if="!flags.llmConfigured && info">
          未配置大模型：智能问答、多文档分析、智能总结与研究报告不可用；语义检索仍可使用。
        </p>
      </template>
    </el-alert>

    <div class="grid">
      <section class="panel">
        <div class="panel-title">
          <span>大模型（LLM）</span>
          <span class="panel-subtitle">
            {{ flags.llmConfigured ? '已配置' : '未配置' }}
          </span>
        </div>
        <el-form label-width="132px" label-position="left">
          <el-form-item label="服务协议">
            <el-input v-model="llm.llm_provider" placeholder="openai_compatible" />
          </el-form-item>
          <el-form-item label="接口地址">
            <el-input v-model="llm.llm_base_url" placeholder="https://api.deepseek.com/v1" />
          </el-form-item>
          <el-form-item label="模型名称">
            <el-input v-model="llm.llm_model" placeholder="deepseek-chat" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="llm.llm_api_key"
              type="password"
              show-password
              :placeholder="flags.llmHasKey ? '已保存，留空表示不修改' : '请填写 API Key'"
            />
          </el-form-item>
        </el-form>
        <div class="actions">
          <el-button :loading="testing.llm" @click="test('llm')">测试连接</el-button>
          <el-button type="primary" :loading="savingModels" @click="saveModels">保存模型配置</el-button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">
          <span>向量模型（Embedding）</span>
          <span class="panel-subtitle">
            {{ flags.degraded ? '未配置' : '真实 Embedding API' }}
          </span>
        </div>
        <el-alert
          v-if="flags.degraded"
          type="warning"
          :closable="false"
          show-icon
          title="当前未配置向量服务"
          description="未配置前，文档向量化和语义检索会明确停用，不会使用哈希向量冒充 AI。请填写 OpenAI 兼容的 Embeddings 接口信息。"
        />
        <el-form label-width="132px" label-position="left" style="margin-top: 12px">
          <el-form-item label="服务协议">
            <el-input v-model="embedding.embedding_provider" placeholder="openai_compatible" />
          </el-form-item>
          <el-form-item label="接口地址">
            <el-input v-model="embedding.embedding_base_url" placeholder="https://…/v1" />
            <span class="form-hint">填到 /v1 即可，程序自动补 /embeddings；直接粘贴完整 /embeddings 地址也能识别</span>
          </el-form-item>
          <el-form-item label="模型名称">
            <el-input v-model="embedding.embedding_model" placeholder="bge-m3 / text-embedding-3-small…" />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="embedding.embedding_api_key"
              type="password"
              show-password
              :placeholder="flags.embeddingHasKey ? '已保存，留空表示不修改' : '请填写 API Key'"
            />
          </el-form-item>
          <el-form-item label="向量维度">
            <el-input-number v-model="embedding.embedding_dim" :min="64" :max="8192" :step="64" />
            <span class="form-hint">必须与模型实际输出维度一致</span>
          </el-form-item>
        </el-form>
        <div class="actions">
          <el-button :loading="testing.embedding" @click="test('embedding')">测试连接</el-button>
          <el-button type="primary" :loading="savingModels" @click="saveModels">保存模型配置</el-button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">
          <span>处理参数</span>
          <span class="panel-subtitle">影响新提交的解析任务</span>
        </div>
        <el-form label-width="132px" label-position="left">
          <el-form-item label="切块长度">
            <el-input-number v-model="processing.chunk_size" :min="200" :max="4000" :step="100" />
            <span class="form-hint">字符数，建议 300–800</span>
          </el-form-item>
          <el-form-item label="切块重叠">
            <el-input-number v-model="processing.chunk_overlap" :min="0" :max="1000" :step="20" />
            <span class="form-hint">字符数，保留上下文衔接</span>
          </el-form-item>
          <el-form-item label="默认返回条数">
            <el-input-number v-model="processing.default_top_k" :min="1" :max="50" />
          </el-form-item>
          <el-form-item label="单文件上限">
            <el-input-number v-model="processing.max_upload_mb" :min="1" :max="2048" :step="10" />
            <span class="form-hint">MB</span>
          </el-form-item>
        </el-form>
        <div class="actions">
          <el-button type="primary" :loading="savingProcessing" @click="saveProcessing">
            保存处理参数
          </el-button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">
          <span>RAG 检索参数</span>
          <span class="panel-subtitle">影响问答、分析与报告</span>
        </div>
        <el-form label-width="132px" label-position="left">
          <el-form-item label="检索条数">
            <el-input-number v-model="rag.rag_top_k" :min="1" :max="20" />
            <span class="form-hint">每次问答取回的文本块数量</span>
          </el-form-item>
          <el-form-item label="拒答阈值">
            <el-input-number
              v-model="rag.rag_min_score"
              :min="0"
              :max="1"
              :step="0.01"
              :precision="2"
            />
            <span class="form-hint">最高相似度低于该值时直接拒答</span>
          </el-form-item>
          <el-form-item label="上下文长度">
            <el-input-number
              v-model="rag.rag_context_chars"
              :min="1000"
              :max="30000"
              :step="1000"
            />
            <span class="form-hint">字符数，超出时自动截断并提示</span>
          </el-form-item>
        </el-form>
        <p class="note">
          阈值说明：当前演示知识库实测，有答案问题 top1 相似度约 0.71，弱相关问题约 0.55，
          完全无关问题约 0.50；默认阈值 0.50。不同资料与向量模型分数分布不同，请结合实际情况调整，
          不要为了“能回答”盲目调低。
        </p>
        <div class="actions">
          <el-button type="primary" :loading="savingRag" @click="saveRag">保存 RAG 参数</el-button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-title">
          <span>运行信息</span>
          <span class="panel-subtitle">本地部署</span>
        </div>
        <el-descriptions v-if="info" :column="1" border size="small">
          <el-descriptions-item label="版本">{{ info.app_name }} v{{ info.version }}</el-descriptions-item>
          <el-descriptions-item label="Python">{{ info.python_version }}</el-descriptions-item>
          <el-descriptions-item label="数据库">
            <span class="mono">{{ info.database }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="Qdrant">
            {{ info.qdrant_mode === 'local' ? '本地嵌入式模式' : '服务模式' }} ·
            <span class="mono">{{ info.qdrant_collection }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="向量模型">
            {{ info.embedding_model }}（{{ info.embedding_dim }} 维）
          </el-descriptions-item>
          <el-descriptions-item label="索引状态">
            <el-tag
              :type="info.index_status.status === 'completed' ? 'success' : 'warning'"
              size="small"
            >
              {{ info.index_status.status }}
            </el-tag>
            · {{ info.index_status.chunk_count }} 个文本块
            <div v-if="info.index_status.error" class="index-error">
              {{ info.index_status.error }}
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="OCR">
            <el-tag :type="info.ocr_available ? 'success' : 'info'" size="small" round>
              {{ info.ocr_available ? 'PaddleOCR 可用' : '未安装' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="支持格式">
            {{ info.supported_extensions.join('、') }}
          </el-descriptions-item>
          <el-descriptions-item label="数据目录">
            <div class="storage-row">
              <span class="mono">{{ info.data_dir }}</span>
              <el-tag v-if="info.data_dir_custom" type="success" size="small">自定义</el-tag>
              <el-button text type="primary" size="small" @click="openStorageDialog">
                更改位置
              </el-button>
            </div>
          </el-descriptions-item>
        </el-descriptions>
        <p class="note">
          API Key 保存在后端环境变量或本地 data/settings.json 中，接口返回时不会明文回传。
        </p>
      </section>

      <section class="panel wide-panel">
        <div class="panel-title">
          <span>数据备份与恢复</span>
          <span class="panel-subtitle">SQLite + 上传文件 + Qdrant</span>
        </div>

        <div class="backup-actions">
          <el-checkbox v-model="includeSecrets">
            包含 API Key（仅限本机保存，请勿分享）
          </el-checkbox>
          <el-button type="primary" :loading="creatingBackup" @click="createBackup">
            立即备份
          </el-button>
          <el-button :loading="backupLoading" @click="loadBackups">刷新列表</el-button>
        </div>

        <el-table :data="backups" size="small" class="backup-table" max-height="240">
          <el-table-column prop="name" label="备份文件" min-width="260" show-overflow-tooltip />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ formatSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="180">
            <template #default="{ row }">
              {{ row.created_at.slice(0, 16).replace('T', ' ') }}
            </template>
          </el-table-column>
          <el-table-column label="包含密钥" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.secrets_included ? 'warning' : 'success'" size="small">
                {{ row.secrets_included ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="right">
            <template #default="{ row }">
              <el-button text type="primary" @click="downloadBackup(row.name)">下载</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <span class="backup-empty">还没有备份文件</span>
          </template>
        </el-table>

        <el-divider />

        <div class="restore-row">
          <el-upload
            :auto-upload="false"
            :show-file-list="false"
            accept=".zip"
            :on-change="(file: any) => onBackupSelected(file.raw as File)"
          >
            <el-button>选择备份文件</el-button>
          </el-upload>
          <span class="restore-name">{{ backupFile?.name || '未选择文件' }}</span>
          <el-button :loading="validatingBackup" :disabled="!backupFile" @click="validateBackup">
            校验
          </el-button>
          <el-button
            type="danger"
            :loading="restoring"
            :disabled="!backupManifest"
            @click="restoreBackup"
          >
            恢复数据
          </el-button>
        </div>

        <el-alert
          v-if="backupManifest"
          type="success"
          :closable="false"
          show-icon
          class="backup-manifest"
          :title="`校验通过：${backupManifest.document_count} 份资料、${backupManifest.chunk_count} 个文本块、${backupManifest.file_count} 个文件`"
          :description="`生成时间 ${backupManifest.created_at.slice(0, 16).replace('T', ' ')} · 包含密钥：${backupManifest.secrets_included ? '是' : '否'} · Qdrant：${backupManifest.qdrant_mode}`"
        />

        <p class="note">
          恢复前会自动备份当前数据；恢复失败会回滚，不会直接破坏现有资料。未包含 API Key
          的备份恢复后会保留本机现有密钥配置。
        </p>
      </section>
    </div>

    <el-dialog v-model="storageVisible" title="更改数据存储位置" width="560px">
      <el-form label-width="92px" label-position="left">
        <el-form-item label="当前目录">
          <span class="mono">{{ info?.data_dir }}</span>
        </el-form-item>
        <el-form-item label="新目录">
          <el-input v-model="storagePath" placeholder="例如 D:\知枢AI数据" />
        </el-form-item>
        <el-form-item label="迁移数据">
          <el-checkbox v-model="storageMigrate">
            把现有资料、向量索引和配置一并复制到新目录
          </el-checkbox>
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="保存后需要重启应用"
        description="数据库与向量库在启动时按目录加载，更改后会写入程序目录下的 storage.json，重新打开应用生效。"
      />
      <template #footer>
        <el-button
          v-if="info?.data_dir_custom"
          text
          type="warning"
          :disabled="savingStorage"
          @click="resetStorage"
        >恢复默认目录</el-button>
        <el-button :disabled="savingStorage" @click="storageVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingStorage" @click="saveStorage">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}

.availability {
  margin-bottom: 4px;
}

.availability p {
  margin: 2px 0;
  font-size: 13px;
  line-height: 1.7;
}

.wide-panel {
  grid-column: 1 / -1;
}

.backup-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.backup-table {
  width: 100%;
}

.backup-empty {
  color: var(--kf-muted);
  font-size: 13px;
}

.restore-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.restore-name {
  font-size: 13px;
  color: var(--kf-muted);
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.backup-manifest {
  margin-top: 14px;
}

.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--kf-muted);
}

.note {
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--kf-muted);
  line-height: 1.7;
}

.mono {
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}

.storage-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

@media (max-width: 1180px) {
  .grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
