<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Refresh, Search } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import type { DocumentOut, ReportResult, ReportSummary } from '@/types'

const router = useRouter()
const documents = ref<DocumentOut[]>([])
const loadingDocs = ref(false)
const selected = ref<string[]>([])
const keyword = ref('')
const topic = ref('')
const topK = ref(4)
const generating = ref(false)
const result = ref<ReportResult | null>(null)
const history = ref<ReportSummary[]>([])
const loadingHistory = ref(false)
const downloading = ref<'md' | 'docx' | ''>('')

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return documents.value
  return documents.value.filter((item) => item.original_name.toLowerCase().includes(text))
})

function toggle(id: string) {
  if (selected.value.includes(id)) {
    selected.value = selected.value.filter((item) => item !== id)
    return
  }
  if (selected.value.length >= 8) {
    ElMessage.warning('最多选择 8 份资料')
    return
  }
  selected.value = [...selected.value, id]
}

async function loadDocuments() {
  loadingDocs.value = true
  try {
    const data = await api.listDocuments({ page: 1, page_size: 100, status: 'completed' })
    documents.value = data.items
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loadingDocs.value = false
  }
}

async function loadHistory() {
  loadingHistory.value = true
  try {
    history.value = await api.listReports(20)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loadingHistory.value = false
  }
}

function pageText(pageFrom: number | null, pageTo: number | null): string {
  if (pageFrom === null) return '全文'
  if (pageFrom === pageTo) return `第 ${pageFrom} 页`
  return `第 ${pageFrom}–${pageTo} 页`
}

function openCitation(documentId: string, page: number | null) {
  router.push({
    path: `/documents/${documentId}`,
    query: page ? { page: String(page) } : {},
  })
}

async function generate() {
  if (!topic.value.trim()) {
    ElMessage.warning('请输入研究主题')
    return
  }
  if (!selected.value.length) {
    ElMessage.warning('请选择参与研究的资料')
    return
  }
  generating.value = true
  result.value = null
  try {
    const data = await api.generateReport({
      topic: topic.value.trim(),
      document_ids: selected.value,
      top_k: topK.value,
    })
    result.value = data
    if (data.refusal) {
      ElMessage.warning(data.message || '资料不足，未生成报告')
    } else {
      ElMessage.success('研究报告已生成')
      loadHistory()
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    generating.value = false
  }
}

async function openHistory(item: ReportSummary) {
  try {
    result.value = await api.getReport(item.report_id)
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function download(format: 'md' | 'docx') {
  if (!result.value?.report_id) return
  downloading.value = format
  try {
    const response = await fetch(api.reportDownloadUrl(result.value.report_id, format))
    if (!response.ok) {
      throw new Error(`下载失败（${response.status}）`)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${result.value.title}.${format}`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${format.toUpperCase()} 文件`)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    downloading.value = ''
  }
}

const citedCount = computed(
  () => result.value?.citations.filter((item) => item.cited).length ?? 0,
)

onMounted(() => {
  loadDocuments()
  loadHistory()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">研究报告</h1>
        <p class="page-desc">
          输入研究主题并选择知识库资料，系统会真实检索并调用大模型生成带来源引用的结构化报告。
        </p>
      </div>
    </div>

    <div class="report-grid">
      <div class="left-col">
        <section class="panel">
          <div class="panel-title">
            <span>研究设置</span>
            <span class="panel-subtitle">基于知识库真实资料</span>
          </div>
          <el-input
            v-model="topic"
            placeholder="例如：企业知识管理的技术演进与落地挑战"
            maxlength="200"
            show-word-limit
          />
          <el-input
            v-model="keyword"
            placeholder="搜索资料名称"
            :prefix-icon="Search"
            clearable
            class="doc-search"
          />
          <div class="doc-list">
            <div
              v-for="item in filtered"
              :key="item.id"
              class="doc-item"
              :class="{ active: selected.includes(item.id) }"
              @click="toggle(item.id)"
            >
              <el-checkbox
                :model-value="selected.includes(item.id)"
                @click.stop
                @change="toggle(item.id)"
              />
              <el-icon class="doc-icon"><Document /></el-icon>
              <span class="doc-name">{{ item.original_name }}</span>
            </div>
            <el-empty
              v-if="!filtered.length"
              :description="documents.length ? '没有匹配的资料' : '暂无已解析完成的资料'"
              :image-size="70"
            >
              <el-button type="primary" @click="router.push('/documents')">去导入资料</el-button>
            </el-empty>
          </div>
          <div class="options">
            <span class="option-label">每篇片段</span>
            <el-input-number v-model="topK" :min="1" :max="8" size="small" />
            <span class="option-hint">已选 {{ selected.length }} / 8</span>
          </div>
          <el-button type="primary" :loading="generating" class="generate-btn" @click="generate">
            {{ generating ? '正在检索并生成报告…' : '生成研究报告' }}
          </el-button>
          <p v-if="generating" class="generating-tip">
            正在逐篇检索相关资料并调用大模型，通常需要数秒到数十秒。
          </p>
        </section>

        <section class="panel">
          <div class="panel-title">
            <span>历史报告</span>
            <el-button text :icon="Refresh" :loading="loadingHistory" @click="loadHistory" />
          </div>
          <div v-if="history.length" class="history-list">
            <div
              v-for="item in history"
              :key="item.report_id"
              class="history-item"
              :class="{ active: result?.report_id === item.report_id }"
              @click="openHistory(item)"
            >
              <span class="history-title">{{ item.title }}</span>
              <span class="history-meta">
                {{ item.created_at.slice(0, 16).replace('T', ' ') }} · 引用 {{ item.citation_count }}
              </span>
            </div>
          </div>
          <el-empty v-else :description="loadingHistory ? '加载中…' : '还没有生成过报告'" :image-size="70" />
        </section>
      </div>

      <section class="panel preview-panel">
        <template v-if="result">
          <el-alert
            v-if="result.refusal"
            type="warning"
            :closable="false"
            show-icon
            title="未生成报告"
            :description="result.message"
          />
          <template v-else>
            <div class="report-head">
              <div>
                <h2 class="report-title">{{ result.title }}</h2>
                <p class="report-meta">
                  {{ result.created_at.slice(0, 16).replace('T', ' ') }} · 引用 {{ citedCount }} 处 ·
                  {{ result.model }}
                </p>
              </div>
              <div class="download-actions">
                <el-button :loading="downloading === 'md'" @click="download('md')">导出 Markdown</el-button>
                <el-button
                  type="primary"
                  :loading="downloading === 'docx'"
                  @click="download('docx')"
                >
                  导出 DOCX
                </el-button>
              </div>
            </div>
            <el-alert
              v-if="result.truncated"
              type="info"
              :closable="false"
              show-icon
              title="部分资料因上下文长度限制被截取"
              class="truncate-alert"
            />
            <div class="sections">
              <article v-for="section in result.sections" :key="section.title" class="section-card">
                <h3 class="section-title">{{ section.title }}</h3>
                <p class="section-content">{{ section.content }}</p>
              </article>
            </div>
            <div class="citation-block">
              <div class="citation-title">参考资料（点击可定位原文）</div>
              <div
                v-for="citation in result.citations"
                :key="citation.chunk_id"
                class="citation-item"
                :class="{ uncited: !citation.cited }"
                @click="openCitation(citation.document_id, citation.page_from)"
              >
                <span class="citation-name">《{{ citation.document_name }}》</span>
                <span class="citation-page">{{ pageText(citation.page_from, citation.page_to) }}</span>
                <span class="citation-score">相似度 {{ citation.score.toFixed(2) }}</span>
                <el-tag :type="citation.cited ? 'success' : 'info'" size="small">
                  {{ citation.cited ? '已引用' : '仅检索到' }}
                </el-tag>
              </div>
            </div>
          </template>
        </template>
        <div v-else class="preview-empty">
          <el-empty description="生成后的报告会在这里预览，并支持导出 Markdown / DOCX" />
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.report-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.left-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.doc-search {
  margin-top: 12px;
}

.doc-list {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--kf-line);
  border-radius: 9px;
  cursor: pointer;
  font-size: 13.5px;
}

.doc-item:hover {
  border-color: #b9d8d2;
}

.doc-item.active {
  background: var(--kf-primary-soft);
  border-color: #8ec7bd;
}

.doc-icon {
  color: var(--kf-primary);
  flex: 0 0 auto;
}

.doc-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.options {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 14px 0;
}

.option-label,
.option-hint {
  font-size: 12.5px;
  color: var(--kf-muted);
}

.generate-btn {
  width: 100%;
}

.generating-tip {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--kf-muted);
  line-height: 1.7;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 260px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 11px;
  border: 1px solid var(--kf-line);
  border-radius: 9px;
  cursor: pointer;
}

.history-item:hover,
.history-item.active {
  border-color: #8ec7bd;
  background: #f7fcfb;
}

.history-title {
  font-size: 13.5px;
  font-weight: 500;
}

.history-meta {
  font-size: 12px;
  color: var(--kf-muted);
}

.preview-panel {
  min-height: 520px;
}

.preview-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 420px;
}

.report-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.report-title {
  font-size: 20px;
  font-weight: 600;
}

.report-meta {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--kf-muted);
}

.download-actions {
  display: flex;
  gap: 8px;
}

.truncate-alert {
  margin-bottom: 12px;
}

.sections {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-card {
  border: 1px solid var(--kf-line);
  border-radius: 12px;
  padding: 14px 16px;
  background: #fbfcfc;
}

.section-title {
  font-size: 14.5px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--kf-primary);
}

.section-content {
  white-space: pre-wrap;
  line-height: 1.85;
  font-size: 14px;
  color: #263b44;
}

.citation-block {
  margin-top: 18px;
}

.citation-title {
  font-size: 13.5px;
  font-weight: 600;
  margin-bottom: 8px;
}

.citation-item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--kf-line);
  border-radius: 9px;
  margin-bottom: 6px;
  cursor: pointer;
  font-size: 13px;
}

.citation-item:hover {
  border-color: #8ec7bd;
  background: #f7fcfb;
}

.citation-item.uncited {
  opacity: 0.68;
}

.citation-name {
  font-weight: 500;
}

.citation-page {
  color: var(--kf-muted);
}

.citation-score {
  margin-left: auto;
  color: var(--kf-muted);
  font-size: 12px;
}

@media (max-width: 1080px) {
  .report-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
