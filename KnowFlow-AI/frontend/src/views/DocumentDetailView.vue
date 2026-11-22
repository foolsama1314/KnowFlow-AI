<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Link, Refresh, View } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { api } from '@/api'
import StatusTag from '@/components/StatusTag.vue'
import type { DocumentContent, PageOut } from '@/types'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const content = ref<DocumentContent | null>(null)
const activePage = ref(0)
const activeTab = ref<'content' | 'meta'>('content')

const documentId = computed(() => route.params.id as string)

const currentPage = computed<PageOut | null>(() => {
  const pages = content.value?.pages ?? []
  return pages[activePage.value] ?? pages[0] ?? null
})

const pages = computed<PageOut[]>(() => content.value?.pages ?? [])

const doc = computed(() => content.value?.document ?? null)

const pageLabel = computed(() => {
  if (!doc.value) return ''
  return doc.value.file_type === 'pdf' ? `${currentPage.value?.page_no ?? 1} / ${content.value?.pages.length ?? 0}` : '全文'
})

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

async function load() {
  loading.value = true
  try {
    content.value = await api.getDocumentContent(documentId.value)
    const requestedPage = Number(route.query.page)
    const requestedIndex = content.value.pages.findIndex((page) => page.page_no === requestedPage)
    activePage.value = Number.isInteger(requestedPage) && requestedIndex >= 0 ? requestedIndex : 0
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function reprocess() {
  try {
    await api.reprocessDocument(documentId.value)
    ElMessage.success('已提交重新解析任务，可在任务中心查看进度')
    await load()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function openPreview() {
  window.open(api.previewUrl(documentId.value), '_blank')
}

onMounted(load)
watch(
  () => [route.params.id, route.query.page],
  () => load()
)
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div class="head-left">
        <el-button :icon="ArrowLeft" text @click="router.push('/documents')">返回资料列表</el-button>
        <h1 class="page-title">{{ doc?.original_name ?? '资料详情' }}</h1>
        <div class="meta-line" v-if="doc">
          <StatusTag :status="doc.status" />
          <span class="tag-soft">{{ TYPE_LABEL[doc.file_type] ?? doc.file_type }}</span>
          <span class="muted">{{ doc.page_count }} 页 · {{ doc.chunk_count }} 个文本块</span>
          <span class="muted">导入于 {{ dayjs(doc.created_at).format('YYYY-MM-DD HH:mm') }}</span>
        </div>
      </div>
      <div class="head-actions">
        <el-button :icon="View" @click="openPreview">查看原文</el-button>
        <el-button :icon="Refresh" @click="reprocess">重新解析</el-button>
      </div>
    </div>

    <el-alert
      v-if="doc?.status === 'failed'"
      type="error"
      :closable="false"
      show-icon
      title="该资料处理失败"
      description="请到任务中心查看失败原因；修复问题后点击「重新解析」。"
    />
    <el-alert
      v-else-if="doc?.status !== 'completed'"
      type="warning"
      :closable="false"
      show-icon
      title="资料仍在处理中"
      description="解析完成前，该资料可能无法被检索到。"
    />

    <section class="panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="解析内容" name="content">
          <div v-if="!content?.pages.length" class="empty">暂无解析结果</div>
          <div v-else class="reader">
            <aside class="page-nav">
              <button
                v-for="(page, index) in content.pages"
                :key="page.id"
                type="button"
                class="page-item"
                :class="{ active: index === activePage }"
                @click="activePage = index"
              >
                <span>{{ doc?.file_type === 'pdf' ? `第 ${page.page_no} 页` : '全文' }}</span>
                <small v-if="page.parse_method === 'ocr'">OCR</small>
                <small v-else-if="page.parse_method === 'none'" class="warn">无文本</small>
              </button>
            </aside>

            <div class="page-body">
              <div class="page-toolbar">
                <span class="page-label">{{ pageLabel }}</span>
                <span class="muted">
                  解析方式：{{ currentPage?.parse_method === 'ocr' ? 'OCR 识别' : '文本层提取' }}
                  <template v-if="currentPage?.confidence !== undefined && currentPage.confidence < 1">
                    · 置信度 {{ (currentPage.confidence * 100).toFixed(1) }}%
                  </template>
                </span>
              </div>

              <div v-if="currentPage?.parse_method === 'none'" class="empty">
                该页没有文本层，且未启用 OCR。
              </div>
              <div v-else class="blocks">
                <div
                  v-for="block in currentPage?.blocks ?? []"
                  :key="block.id"
                  class="block"
                  :class="{ low: block.confidence < 0.75 }"
                >
                  <div class="block-head">
                    <span class="block-type">{{
                      block.block_type === 'title'
                        ? '标题'
                        : block.block_type === 'table'
                          ? '表格'
                          : block.block_type === 'code'
                            ? '代码'
                            : '正文'
                    }}</span>
                    <span v-if="block.confidence < 0.75" class="low-tag">识别存疑</span>
                  </div>
                  <p class="block-text">{{ block.content }}</p>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="资料信息" name="meta">
          <el-descriptions :column="2" border size="large">
            <el-descriptions-item label="文档 ID">{{ doc?.id }}</el-descriptions-item>
            <el-descriptions-item label="原始文件名">{{ doc?.original_name }}</el-descriptions-item>
            <el-descriptions-item label="格式">{{ doc?.file_type }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ doc?.status }}</el-descriptions-item>
            <el-descriptions-item label="页数">{{ doc?.page_count }}</el-descriptions-item>
            <el-descriptions-item label="文本块">{{ doc?.chunk_count }}</el-descriptions-item>
            <el-descriptions-item label="导入时间">
              {{ doc ? dayjs(doc.created_at).format('YYYY-MM-DD HH:mm:ss') : '' }}
            </el-descriptions-item>
            <el-descriptions-item label="更新时间">
              {{ doc ? dayjs(doc.updated_at).format('YYYY-MM-DD HH:mm:ss') : '' }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="meta-note">
            <el-icon><Link /></el-icon>
            每个文本块都保留页码与来源映射，检索结果可直接跳回原文位置。
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<style scoped>
.head-left {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.meta-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13.5px;
}

.head-actions {
  display: flex;
  gap: 8px;
}

.reader {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 20px;
  min-height: 420px;
}

.page-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 560px;
  overflow-y: auto;
  padding-right: 6px;
  border-right: 1px solid var(--kf-line);
}

.page-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 8px 10px;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 13.5px;
  color: #52666d;
  cursor: pointer;
  text-align: left;
}

.page-item:hover {
  background: #f2f7f6;
}

.page-item.active {
  background: var(--kf-primary-soft);
  color: var(--kf-primary);
  font-weight: 600;
}

.page-item small {
  font-size: 10.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: #eef2f3;
  color: #7d9098;
}

.page-item small.warn {
  background: #fdeceb;
  color: #c0503f;
}

.page-body {
  min-width: 0;
}

.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px dashed var(--kf-line);
  font-size: 13px;
}

.page-label {
  font-weight: 600;
  font-size: 14px;
}

.blocks {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-height: 560px;
  overflow-y: auto;
  padding-right: 6px;
}

.block {
  background: #fbfcfc;
  border: 1px solid var(--kf-line);
  border-radius: 10px;
  padding: 12px 14px;
}

.block.low {
  border-color: #f0d3cb;
  background: #fdf8f6;
}

.block-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.block-type {
  font-size: 11.5px;
  color: #7a8d94;
  background: #eef2f3;
  border-radius: 4px;
  padding: 1px 6px;
}

.low-tag {
  font-size: 11.5px;
  color: #bd5a45;
  background: #fdeceb;
  border-radius: 4px;
  padding: 1px 6px;
}

.block-text {
  font-size: 14.5px;
  line-height: 1.85;
  white-space: pre-wrap;
  word-break: break-word;
}

.empty {
  padding: 40px 0;
  text-align: center;
  color: #9fb0b6;
  font-size: 14px;
}

.meta-note {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--kf-muted);
  font-size: 13px;
}
</style>
