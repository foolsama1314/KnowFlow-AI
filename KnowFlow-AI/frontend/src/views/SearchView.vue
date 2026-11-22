<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { api } from '@/api'
import type { DocumentOut, SearchHistoryItem, SearchHit, SystemInfo } from '@/types'

const router = useRouter()
const loading = ref(false)
const results = ref<SearchHit[]>([])
const searched = ref(false)
const tookMs = ref(0)
const history = ref<SearchHistoryItem[]>([])
const documents = ref<DocumentOut[]>([])
const reindexing = ref(false)
const info = ref<SystemInfo | null>(null)

const form = reactive({
  query: '',
  topK: 5,
  fileTypes: [] as string[],
  documentIds: [] as string[],
})

const FILE_TYPES = [
  { label: 'PDF', value: 'pdf' },
  { label: 'Word', value: 'docx' },
  { label: '文本 / Markdown', value: 'txt' },
  { label: 'Markdown', value: 'md' },
]

const canSearch = computed(
  () => form.query.trim().length > 0 && info.value?.index_status.status === 'completed',
)

function highlight(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  const terms = form.query
    .split(/\s+/)
    .map((term) => term.trim())
    .filter((term) => term.length >= 2)
  if (!terms.length) return escaped
  const pattern = terms
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')
  return escaped.replace(new RegExp(`(${pattern})`, 'gi'), '<mark>$1</mark>')
}

function pageLabel(hit: SearchHit): string {
  if (hit.file_type !== 'pdf') return '全文'
  if (hit.page_from == null) return '页码未知'
  return hit.page_from === hit.page_to
    ? `第 ${hit.page_from} 页`
    : `第 ${hit.page_from}–${hit.page_to} 页`
}

async function runSearch() {
  if (!form.query.trim()) {
    ElMessage.warning('请输入要检索的内容')
    return
  }
  if (!canSearch.value) {
    ElMessage.warning('请先配置 Embedding 并完成向量索引重建')
    return
  }
  loading.value = true
  searched.value = true
  try {
    const data = await api.search(form.query.trim(), form.topK, {
      document_ids: form.documentIds,
      file_types: form.fileTypes,
    })
    results.value = data.results
    tookMs.value = data.took_ms
    if (info.value) info.value.index_status = data.index_status
    await loadHistory()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function useHistory(query: string) {
  form.query = query
  runSearch()
}

async function loadHistory() {
  try {
    history.value = await api.searchHistory()
  } catch {
    history.value = []
  }
}

async function loadDocuments() {
  try {
    const data = await api.listDocuments({ page: 1, page_size: 100 })
    documents.value = data.items.filter((item) => item.status === 'completed')
  } catch {
    documents.value = []
  }
}

async function loadInfo() {
  try {
    info.value = await api.systemInfo()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function openHit(hit: SearchHit) {
  router.push({
    path: `/documents/${hit.document_id}`,
    query: hit.page_from ? { page: String(hit.page_from) } : {},
  })
}

async function reindex() {
  try {
    await ElMessageBox.confirm(
      '重建索引会调用当前 Embedding 服务重新生成全部文本块向量。新索引完整校验通过后才会替换旧索引；重建期间暂停检索。',
      '重建向量索引',
      { type: 'warning', confirmButtonText: '开始重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  reindexing.value = true
  try {
    const result = await api.reindex()
    ElMessage.success(
      `重建完成：${result.chunks} 个文本块，${result.dimension} 维，用时 ${result.elapsed_ms} ms`,
    )
    await loadHistory()
    results.value = []
    searched.value = false
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    reindexing.value = false
    await loadInfo()
  }
}

onMounted(() => {
  loadInfo()
  loadHistory()
  loadDocuments()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">语义检索</h1>
        <p class="page-desc">用自然语言描述你要找的内容，系统返回最相关的原文片段与出处。</p>
      </div>
      <el-button
        :loading="reindexing"
        :disabled="info?.retrieval_mode !== 'semantic'"
        @click="reindex"
      >重建索引</el-button>
    </div>

    <el-alert
      v-if="info?.index_status.status === 'unconfigured'"
      type="warning"
      :closable="false"
      show-icon
      title="尚未配置真实 Embedding 服务"
      description="请前往「系统设置」填写 OpenAI 兼容接口地址、API Key、模型名称和向量维度。系统不会再使用哈希向量进行正式检索。"
    />
    <el-alert
      v-else-if="info && info.index_status.status !== 'completed'"
      type="warning"
      :closable="false"
      show-icon
      title="向量索引需要准备或重建"
      :description="info.index_status.error || '请点击右上角「重建索引」，完成后即可进行语义检索。'"
    />
    <div v-else-if="info" class="index-ready">
      真实语义检索 · {{ info.index_status.model }} · {{ info.index_status.dimension }} 维 ·
      {{ info.index_status.chunk_count }} 个文本块
    </div>

    <section class="search-panel">
      <el-input
        v-model="form.query"
        class="kf-search-input"
        size="large"
        placeholder="例如：检索增强生成的核心组成是什么？"
        :prefix-icon="Search"
        clearable
        @keyup.enter="runSearch"
      >
        <template #append>
          <el-button type="primary" :loading="loading" @click="runSearch">检索</el-button>
        </template>
      </el-input>

      <div class="filters">
        <div class="filter-item">
          <span class="filter-label">返回数量</span>
          <el-select v-model="form.topK" style="width: 92px">
            <el-option :value="3" label="3 条" />
            <el-option :value="5" label="5 条" />
            <el-option :value="10" label="10 条" />
            <el-option :value="20" label="20 条" />
          </el-select>
        </div>
        <div class="filter-item">
          <span class="filter-label">格式</span>
          <el-checkbox-group v-model="form.fileTypes">
            <el-checkbox v-for="type in FILE_TYPES" :key="type.value" :value="type.value">
              {{ type.label }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
        <div class="filter-item grow">
          <span class="filter-label">限定资料</span>
          <el-select
            v-model="form.documentIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
            clearable
            placeholder="全部已入库资料"
            style="width: 100%"
          >
            <el-option
              v-for="doc in documents"
              :key="doc.id"
              :label="doc.original_name"
              :value="doc.id"
            />
          </el-select>
        </div>
      </div>

      <div v-if="history.length" class="history">
        <span class="filter-label">最近检索</span>
        <button
          v-for="item in history.slice(0, 5)"
          :key="item.at + item.query"
          type="button"
          class="history-chip"
          @click="useHistory(item.query)"
        >
          {{ item.query }}
          <small>{{ item.result_count }}</small>
        </button>
      </div>
    </section>

    <section v-if="searched" class="panel results" v-loading="loading">
      <div class="panel-title">
        <span>检索结果 <span class="muted">（{{ results.length }} 条）</span></span>
        <span class="panel-subtitle">用时 {{ tookMs }} ms</span>
      </div>

      <el-empty
        v-if="!results.length && !loading"
        description="没有找到相关内容。可以换个说法，或确认资料是否已完成解析。"
      />

      <article v-for="hit in results" :key="hit.chunk_id" class="hit">
        <div class="hit-head">
          <a class="doc-name" @click="openHit(hit)">
            {{ hit.document_name }}
          </a>
          <span class="tag-soft">{{ pageLabel(hit) }}</span>
          <span class="tag-soft">{{ hit.file_type.toUpperCase() }}</span>
          <span class="score">相似度 {{ (hit.score * 100).toFixed(1) }}%</span>
        </div>
        <p class="hit-content" v-html="highlight(hit.content)" />
      </article>
    </section>

    <section v-else class="panel hint-panel">
      <h3>怎么检索更准</h3>
      <ul>
        <li>用一句完整的问题，而不是单个关键词，例如「向量模型切换后为什么要重建索引」。</li>
        <li>结果按相似度排序，第一条通常是切块最相关的原文片段。</li>
        <li>鼠标点击文档名可跳转到资料详情，核对上下文与页码。</li>
        <li>若结果明显不相关，可在系统设置中检查 Embedding 模型和索引状态。</li>
      </ul>
      <p class="muted small">今天是 {{ dayjs().format('YYYY-MM-DD') }}，建议每周固定整理一次资料。</p>
    </section>
  </div>
</template>

<style scoped>
.index-ready {
  color: var(--kf-primary);
  font-size: 13px;
  padding: 10px 14px;
  border: 1px solid #cde2dc;
  background: #f2f9f6;
  border-radius: 10px;
}

.search-panel {
  background: var(--kf-panel);
  border: 1px solid var(--kf-line);
  border-radius: 14px;
  padding: 22px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filters {
  display: flex;
  gap: 22px;
  flex-wrap: wrap;
  align-items: center;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-item.grow {
  flex: 1;
  min-width: 260px;
}

.filter-label {
  color: var(--kf-muted);
  font-size: 13px;
  white-space: nowrap;
}

.history {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 4px;
  border-top: 1px dashed var(--kf-line);
}

.history-chip {
  border: 1px solid var(--kf-line);
  background: #fafcfc;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12.5px;
  color: #51656c;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.history-chip:hover {
  border-color: #bcd9d3;
  color: var(--kf-primary);
}

.history-chip small {
  color: #9fb0b6;
}

.results {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hit {
  border: 1px solid var(--kf-line);
  border-radius: 12px;
  padding: 14px 16px;
  background: #fcfdfd;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.hit:hover {
  border-color: #c6ded8;
  box-shadow: 0 4px 16px rgba(20, 60, 55, 0.05);
}

.hit-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.doc-name {
  font-weight: 600;
  cursor: pointer;
}

.doc-name:hover {
  color: var(--kf-primary);
}

.score {
  margin-left: auto;
  font-size: 12px;
  color: #8a9ba2;
  font-variant-numeric: tabular-nums;
}

.hit-content {
  font-size: 14.5px;
  line-height: 1.9;
  color: #2c3f47;
  white-space: pre-wrap;
  word-break: break-word;
}

.hit-content :deep(mark) {
  background: #ffeec9;
  color: #7a5312;
  padding: 0 2px;
  border-radius: 3px;
}

.hint-panel h3 {
  font-size: 16px;
  margin-bottom: 12px;
}

.hint-panel ul {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #52666d;
  font-size: 14px;
  line-height: 1.7;
}

.small {
  margin-top: 14px;
  font-size: 12.5px;
}
</style>
