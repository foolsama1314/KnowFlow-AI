<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '@/api'
import type { AnalysisResult, DocumentOut } from '@/types'

const router = useRouter()
const loadingDocs = ref(false)
const generating = ref(false)
const documents = ref<DocumentOut[]>([])
const keyword = ref('')
const selected = ref<string[]>([])
const mode = ref<'compare' | 'summary'>('compare')
const topic = ref('')
const topK = ref(3)
const result = ref<AnalysisResult | null>(null)

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  if (!text) return documents.value
  return documents.value.filter((item) => item.original_name.toLowerCase().includes(text))
})

const allSelected = computed(
  () => filtered.value.length > 0 && filtered.value.every((item) => selected.value.includes(item.id)),
)

function toggleAll(value: boolean) {
  if (value) {
    const ids = new Set(selected.value)
    filtered.value.forEach((item) => ids.add(item.id))
    selected.value = Array.from(ids).slice(0, 8)
    if (ids.size > 8) ElMessage.warning('最多选择 8 份资料')
  } else {
    const visible = new Set(filtered.value.map((item) => item.id))
    selected.value = selected.value.filter((id) => !visible.has(id))
  }
}

function toggle(id: string) {
  if (selected.value.includes(id)) {
    selected.value = selected.value.filter((item) => item !== id)
    return
  }
  if (selected.value.length >= 8) {
    ElMessage.warning('最多选择 8 份资料，以保证分析质量')
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
  if (!selected.value.length) {
    ElMessage.warning('请先选择参与分析的资料')
    return
  }
  if (!topic.value.trim()) {
    ElMessage.warning('请输入分析主题或问题')
    return
  }
  generating.value = true
  result.value = null
  try {
    const payload = {
      mode: mode.value,
      document_ids: selected.value,
      topic: topic.value.trim(),
      top_k: topK.value,
    }
    const data =
      mode.value === 'summary' ? await api.summarize(payload) : await api.analyze(payload)
    result.value = data
    if (data.refusal) {
      ElMessage.warning(data.message || '资料不足，未生成内容')
    } else {
      ElMessage.success(`已生成，用时 ${(data.took_ms / 1000).toFixed(1)} 秒`)
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    generating.value = false
  }
}

const citedCount = computed(
  () => result.value?.citations.filter((item) => item.cited).length ?? 0,
)

onMounted(loadDocuments)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">多文档分析</h1>
        <p class="page-desc">
          选择多份资料，围绕同一主题做联合检索与分析；所有结论都标注真实来源与页码。
        </p>
      </div>
    </div>

    <div class="analysis-grid">
      <section class="panel doc-panel">
        <div class="panel-title">
          <span>选择资料</span>
          <span class="panel-subtitle">已选 {{ selected.length }} / 8</span>
        </div>
        <el-input
          v-model="keyword"
          placeholder="搜索资料名称"
          :prefix-icon="Search"
          clearable
          class="doc-search"
        />
        <div class="doc-toolbar">
          <el-checkbox
            :model-value="allSelected"
            :disabled="!filtered.length"
            @change="toggleAll(Boolean($event))"
          >
            全选当前列表
          </el-checkbox>
          <el-button text :icon="Refresh" @click="loadDocuments">刷新</el-button>
        </div>

        <div v-loading="loadingDocs" class="doc-list">
          <div
            v-for="item in filtered"
            :key="item.id"
            class="doc-item"
            :class="{ active: selected.includes(item.id) }"
            @click="toggle(item.id)"
          >
            <el-checkbox :model-value="selected.includes(item.id)" @click.stop @change="toggle(item.id)" />
            <el-icon class="doc-icon"><Document /></el-icon>
            <div class="doc-meta">
              <span class="doc-name">{{ item.original_name }}</span>
              <span class="doc-sub">{{ item.page_count }} 页 · {{ item.chunk_count }} 个文本块</span>
            </div>
          </div>
          <el-empty
            v-if="!loadingDocs && !filtered.length"
            :description="documents.length ? '没有匹配的资料' : '暂无已解析完成的资料'"
            :image-size="80"
          >
            <el-button type="primary" @click="router.push('/documents')">去导入资料</el-button>
          </el-empty>
        </div>
      </section>

      <section class="panel work-panel">
        <div class="panel-title">
          <span>分析设置</span>
          <span class="panel-subtitle">检索范围仅限所选资料</span>
        </div>

        <el-radio-group v-model="mode" class="mode-group">
          <el-radio-button value="compare">联合分析</el-radio-button>
          <el-radio-button value="summary">智能总结</el-radio-button>
        </el-radio-group>

        <el-input
          v-model="topic"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          :placeholder="
            mode === 'compare'
              ? '例如：这几份资料在方法论上的共同观点和差异是什么？'
              : '例如：请总结这些资料的核心观点与待研究问题'
          "
        />

        <div class="options">
          <span class="option-label">每篇返回片段</span>
          <el-input-number v-model="topK" :min="1" :max="8" size="small" />
          <span class="option-hint">资料较多时会自动控制上下文长度</span>
        </div>

        <el-button type="primary" :loading="generating" class="generate-btn" @click="generate">
          {{ generating ? '正在分析，请稍候…' : mode === 'summary' ? '生成智能总结' : '开始联合分析' }}
        </el-button>

        <div v-if="generating" class="generating-tip">
          正在对 {{ selected.length }} 份资料进行真实检索并调用大模型，通常需要数秒到数十秒。
        </div>

        <template v-if="result">
          <el-alert
            v-if="result.refusal"
            type="warning"
            :closable="false"
            show-icon
            title="未生成分析"
            :description="result.message"
            class="result-alert"
          />
          <template v-else>
            <el-alert
              v-if="result.truncated"
              type="info"
              :closable="false"
              show-icon
              title="部分资料因上下文长度限制被截取"
              description="系统已优先保留相关度更高的片段；如需更完整分析，可减少资料数量。"
              class="result-alert"
            />
            <div class="result-head">
              <span class="result-title">{{ result.topic }}</span>
              <span class="result-meta">
                {{ result.retrieval_count }} 段资料 · 引用 {{ citedCount }} 处 · {{ result.model }}
              </span>
            </div>
            <div class="sections">
              <article v-for="section in result.sections" :key="section.title" class="section-card">
                <h3 class="section-title">{{ section.title }}</h3>
                <p class="section-content">{{ section.content }}</p>
              </article>
            </div>
            <div class="citation-block">
              <div class="citation-title">资料来源（点击可定位原文）</div>
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
      </section>
    </div>
  </div>
</template>

<style scoped>
.analysis-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.doc-panel {
  position: sticky;
  top: 82px;
}

.doc-search {
  margin-bottom: 10px;
}

.doc-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.doc-list {
  max-height: 560px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--kf-line);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease;
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

.doc-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.doc-name {
  font-size: 13.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-sub {
  font-size: 12px;
  color: var(--kf-muted);
}

.mode-group {
  margin-bottom: 14px;
}

.options {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 14px 0;
}

.option-label {
  font-size: 13.5px;
  color: var(--kf-muted);
}

.option-hint {
  font-size: 12px;
  color: var(--kf-muted);
}

.generate-btn {
  width: 100%;
}

.generating-tip {
  margin-top: 10px;
  font-size: 13px;
  color: var(--kf-muted);
}

.result-alert {
  margin-top: 16px;
}

.result-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin: 18px 0 10px;
}

.result-title {
  font-size: 17px;
  font-weight: 600;
}

.result-meta {
  font-size: 12.5px;
  color: var(--kf-muted);
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
  .analysis-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .doc-panel {
    position: static;
  }

  .doc-list {
    max-height: 300px;
  }
}
</style>
