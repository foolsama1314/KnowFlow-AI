<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete,
  MoreFilled,
  Refresh,
  RefreshRight,
  Search,
  UploadFilled,
} from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { api } from '@/api'
import StatusTag from '@/components/StatusTag.vue'
import type { DocumentOut, IndexSummary, ReindexProgress } from '@/types'

const router = useRouter()
const loading = ref(false)
const documents = ref<DocumentOut[]>([])
const total = ref(0)
const summary = ref<IndexSummary | null>(null)
const rebuilding = ref(false)
const progress = ref<ReindexProgress | null>(null)
let pollTimer: number | undefined

const INDEX_LABEL: Record<string, string> = {
  indexed: '已索引',
  not_indexed: '待索引',
  processing: '处理中',
  failed: '失败',
  unknown: '未知',
}

const INDEX_TAG: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
  indexed: 'success',
  not_indexed: 'warning',
  processing: 'info',
  failed: 'danger',
  unknown: 'info',
}

const query = reactive({
  keyword: '',
  status: '',
  file_type: '',
  page: 1,
  page_size: 10,
})

const hasFilters = computed(() => Boolean(query.keyword || query.status || query.file_type))

const TYPE_LABEL: Record<string, string> = {
  pdf: 'PDF',
  docx: 'Word',
  txt: 'TXT',
  md: 'Markdown',
  jpg: '图片',
  jpeg: '图片',
  png: '图片',
  bmp: '图片',
  webp: '图片',
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  try {
    const data = await api.listDocuments({
      page: query.page,
      page_size: query.page_size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      file_type: query.file_type || undefined,
    })
    documents.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
  loadSummary()
}

async function loadSummary() {
  try {
    summary.value = await api.indexSummary()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      const data = await api.reindexStatus()
      progress.value = data
      if (!data.running) stopPolling()
    } catch {
      stopPolling()
    }
  }, 1500)
}

async function rebuildIndex() {
  try {
    await ElMessageBox.confirm(
      '将使用当前 Embedding 模型重建全部向量索引。重建期间语义检索、问答与分析暂不可用；新索引完整校验通过后才会替换旧索引。确认继续？',
      '重建向量索引',
      { type: 'warning', confirmButtonText: '开始重建', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  rebuilding.value = true
  progress.value = null
  startPolling()
  try {
    const result = await api.reindex()
    ElMessage.success(`重建完成：${result.chunks} 个文本块，${result.dimension} 维`)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    rebuilding.value = false
    stopPolling()
    progress.value = await api.reindexStatus().catch(() => null)
    load()
  }
}

const progressPercent = computed(() => {
  const value = progress.value
  if (!rebuilding.value) return 0
  if (!value || !value.total) return 5
  return Math.min(99, Math.round((value.processed / value.total) * 100))
})

function resetFilters() {
  query.keyword = ''
  query.status = ''
  query.file_type = ''
  query.page = 1
  load()
}

async function remove(row: DocumentOut) {
  try {
    await ElMessageBox.confirm(
      `将删除「${row.original_name}」及其解析结果、文本块与向量，且不可恢复。`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api.deleteDocument(row.id)
    ElMessage.success('已删除该资料')
    load()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function reprocess(row: DocumentOut) {
  try {
    await api.reprocessDocument(row.id)
    ElMessage.success('已提交重新解析任务')
    load()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function handleAction(command: string, row: DocumentOut) {
  if (command === 'reprocess') {
    reprocess(row)
  } else if (command === 'remove') {
    remove(row)
  }
}

function openUpload() {
  window.dispatchEvent(new CustomEvent('knowflow:open-upload'))
}

function onDocumentsUpdated() {
  load()
}

onMounted(() => {
  load()
  window.addEventListener('knowflow:documents-updated', onDocumentsUpdated)
})

onBeforeUnmount(() => {
  window.removeEventListener('knowflow:documents-updated', onDocumentsUpdated)
  stopPolling()
})
</script>

<template>
  <div class="page documents-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">资料管理</h1>
        <p class="page-desc">所有导入的资料都在这里，状态、页数与文本块数量一目了然。</p>
      </div>
      <el-button :loading="rebuilding" :disabled="!summary" @click="rebuildIndex">
        重建向量索引
      </el-button>
    </div>

    <section v-if="summary" class="panel index-panel">
      <div class="index-stats">
        <div class="stat">
          <span class="stat-value">{{ summary.total_documents }}</span>
          <span class="stat-label">资料总数</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ summary.completed_documents }}</span>
          <span class="stat-label">解析完成</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ summary.failed_documents }}</span>
          <span class="stat-label">处理失败</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ summary.pending_index }}</span>
          <span class="stat-label">待索引</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ summary.indexed_chunks }} / {{ summary.total_chunks }}</span>
          <span class="stat-label">已索引 / 文本块</span>
        </div>
        <div class="stat">
          <el-tag
            :type="summary.index_status.status === 'completed' ? 'success' : 'warning'"
            size="small"
          >
            {{ summary.index_status.status }}
          </el-tag>
          <span class="stat-label">向量索引</span>
        </div>
      </div>
      <div v-if="summary.index_status.error" class="index-warning">
        {{ summary.index_status.error }}
      </div>
      <div v-if="rebuilding" class="rebuild-progress">
        <el-progress :percentage="progressPercent" :stroke-width="8" />
        <span class="rebuild-stage">
          {{ progress?.stage || '正在准备重建…' }}
          <template v-if="progress?.total">（{{ progress.processed }}/{{ progress.total }}）</template>
        </span>
      </div>
    </section>

    <section class="panel">
      <div class="toolbar">
        <el-input
          v-model="query.keyword"
          placeholder="按名称搜索"
          class="search-box"
          clearable
          :prefix-icon="Search"
          @keyup.enter="((query.page = 1), load())"
          @clear="((query.page = 1), load())"
        />
        <el-select
          v-model="query.status"
          class="filter-select"
          placeholder="全部状态"
          clearable
          @change="((query.page = 1), load())"
        >
          <el-option label="可检索" value="completed" />
          <el-option label="处理中" value="processing" />
          <el-option label="已上传" value="uploaded" />
          <el-option label="处理失败" value="failed" />
        </el-select>
        <el-select
          v-model="query.file_type"
          class="filter-select"
          placeholder="全部格式"
          clearable
          @change="((query.page = 1), load())"
        >
          <el-option v-for="(label, type) in TYPE_LABEL" :key="type" :label="label" :value="type" />
        </el-select>
        <el-button text :icon="Refresh" class="reset-btn" @click="resetFilters">重置</el-button>
        <span class="toolbar-meta">共 {{ total }} 份资料</span>
      </div>

      <el-table
        :data="documents"
        v-loading="loading"
        size="large"
        class="documents-table"
      >
        <el-table-column label="名称" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <a class="doc-link" @click="router.push(`/documents/${row.id}`)">{{ row.original_name }}</a>
          </template>
        </el-table-column>
        <el-table-column label="格式" width="96">
          <template #default="{ row }">
            <span class="tag-soft">{{ TYPE_LABEL[row.file_type] ?? row.file_type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100" align="right">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="页数 / 块数" width="118" align="center">
          <template #default="{ row }">{{ row.page_count }} / {{ row.chunk_count }}</template>
        </el-table-column>
        <el-table-column label="状态" width="104">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="索引" width="106">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.last_error"
              :content="row.last_error"
              placement="top"
              effect="dark"
            >
              <el-tag :type="INDEX_TAG[row.index_status] ?? 'info'" size="small">
                {{ INDEX_LABEL[row.index_status] ?? row.index_status }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else :type="INDEX_TAG[row.index_status] ?? 'info'" size="small">
              {{ INDEX_LABEL[row.index_status] ?? row.index_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="导入时间" width="164">
          <template #default="{ row }">{{ dayjs(row.created_at).format('YYYY-MM-DD HH:mm') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="118" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button text type="primary" @click="router.push(`/documents/${row.id}`)">
                查看
              </el-button>
              <el-dropdown trigger="click" @command="handleAction($event, row)">
                <el-button text class="more-btn" :icon="MoreFilled" title="更多操作" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="reprocess" :icon="RefreshRight">
                      重新解析
                    </el-dropdown-item>
                    <el-dropdown-item command="remove" :icon="Delete" divided>
                      删除资料
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="table-empty">
            <p class="empty-text">{{ hasFilters ? '没有符合条件的资料' : '还没有导入任何资料' }}</p>
            <div class="empty-actions">
              <el-button v-if="hasFilters" :icon="Refresh" @click="resetFilters">清空筛选</el-button>
              <el-button type="primary" :icon="UploadFilled" @click="openUpload">导入资料</el-button>
            </div>
          </div>
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load"
          @size-change="((query.page = 1), load())"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.index-panel {
  padding: 16px 22px;
}

.index-stats {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--kf-ink);
}

.stat-label {
  font-size: 12.5px;
  color: var(--kf-muted);
}

.index-warning {
  margin-top: 10px;
  font-size: 13px;
  color: #b4762b;
}

.rebuild-progress {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rebuild-stage {
  font-size: 12.5px;
  color: var(--kf-muted);
}

.toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.search-box {
  flex: 1 1 240px;
  min-width: 200px;
  max-width: 340px;
}

.filter-select {
  width: 132px;
}

.reset-btn {
  margin-left: 2px;
}

.toolbar-meta {
  margin-left: auto;
  color: var(--kf-muted);
  font-size: 13px;
  white-space: nowrap;
}

.documents-table {
  width: 100%;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.more-btn {
  padding: 4px;
  color: var(--kf-muted);
}

.table-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 26px 0;
}

.empty-text {
  color: var(--kf-muted);
  font-size: 14px;
}

.empty-actions {
  display: flex;
  gap: 10px;
}

.doc-link {
  cursor: pointer;
  font-weight: 500;
}

.doc-link:hover {
  color: var(--kf-primary);
}

.pager {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  margin-top: 16px;
}

@media (max-width: 900px) {
  .index-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .search-box {
    flex-basis: 100%;
    max-width: none;
  }

  .filter-select {
    flex: 1 1 120px;
    width: auto;
  }

  .toolbar-meta {
    margin-left: 0;
  }

  .pager {
    justify-content: center;
  }
}
</style>
