<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ArrowRight } from '@element-plus/icons-vue'
import { api } from '@/api'
import StatCard from '@/components/StatCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import type { DocumentOut, Stats, SystemInfo } from '@/types'

const router = useRouter()
const stats = ref<Stats | null>(null)
const recent = ref<DocumentOut[]>([])
const info = ref<SystemInfo | null>(null)
const loading = ref(true)
const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

const TYPE_LABEL: Record<string, string> = {
  pdf: 'PDF',
  docx: 'Word',
  txt: '文本',
  md: 'Markdown',
  jpg: '图片',
  jpeg: '图片',
  png: '图片',
  bmp: '图片',
  webp: '图片',
}

const storageText = computed(() => {
  const bytes = stats.value?.storage_bytes ?? 0
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
})

const chartData = computed(() =>
  Object.entries(stats.value?.by_file_type ?? {}).map(([type, count]) => ({
    name: TYPE_LABEL[type] ?? type.toUpperCase(),
    value: count,
  })),
)

function renderChart() {
  if (!chartRef.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}：{c} 份（{d}%）' },
    legend: {
      orient: 'vertical',
      right: 4,
      top: 'center',
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: '#55696f', fontSize: 12 },
    },
    color: ['#1f7a6b', '#4f9c8f', '#8cc4b8', '#c98b3f', '#6b8fa3', '#a7b8bf'],
    series: [
      {
        type: 'pie',
        radius: ['54%', '76%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { show: false },
        data: chartData.value,
      },
    ],
  })
  if (!chartData.value.length) {
    chart.setOption({
      title: {
        text: '暂无资料',
        left: '38%',
        top: '46%',
        textAlign: 'center',
        textStyle: { color: '#9fb0b6', fontSize: 13, fontWeight: 400 },
      },
    })
  } else {
    chart.setOption({ title: { text: '' } })
  }
}

function resize() {
  chart?.resize()
}

async function load() {
  loading.value = true
  try {
    const [statsData, docs, systemInfo] = await Promise.all([
      api.stats(),
      api.listDocuments({ page: 1, page_size: 6 }),
      api.systemInfo(),
    ])
    stats.value = statsData
    recent.value = docs.items
    info.value = systemInfo
  } catch {
    // 首屏失败不阻塞页面，顶部状态灯会提示服务未连接
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  renderChart()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})

watch(chartData, () => renderChart())
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">工作台</h1>
        <p class="page-desc">把多格式资料统一转换为可搜索、可问答的个人知识库。</p>
      </div>
      <el-button type="primary" @click="router.push('/documents')">进入资料管理</el-button>
    </div>

    <div class="stat-grid">
      <StatCard
        label="资料总数"
        :value="stats?.document_count ?? 0"
        hint="已导入的全部文件"
        accent
      />
      <StatCard label="可检索文本块" :value="stats?.chunk_count ?? 0" hint="切块并完成向量化" />
      <StatCard label="进行中任务" :value="stats?.task_running ?? 0" hint="解析与向量化队列" />
      <StatCard label="占用存储" :value="storageText" hint="原始文件本地存储" />
    </div>

    <div class="grid">
      <section class="panel">
        <div class="panel-title">
          <span>最近导入</span>
          <el-button text type="primary" @click="router.push('/documents')">
            全部资料<el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </div>
        <el-table :data="recent" v-loading="loading" size="large" empty-text="还没有资料，先导入一份试试">
          <el-table-column label="名称" min-width="260">
            <template #default="{ row }">
              <a class="doc-link" @click="router.push(`/documents/${row.id}`)">
                {{ row.original_name }}
              </a>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">
              <span class="tag-soft">{{ TYPE_LABEL[row.file_type] ?? row.file_type }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <StatusTag :status="row.status" />
            </template>
          </el-table-column>
          <el-table-column label="文本块" width="90" align="right">
            <template #default="{ row }">{{ row.chunk_count }}</template>
          </el-table-column>
        </el-table>
      </section>

      <div class="side">
        <section class="panel">
          <div class="panel-title">
            <span>资料构成</span>
            <span class="panel-subtitle">按格式</span>
          </div>
          <div ref="chartRef" class="chart" />
        </section>

        <section class="panel">
          <div class="panel-title">
            <span>处理链路</span>
            <span class="panel-subtitle">第一阶段</span>
          </div>
          <ol class="pipeline">
            <li><b>上传</b><span>格式校验、去重、本地保存</span></li>
            <li><b>解析</b><span>PDF / Word / 文本 / OCR</span></li>
            <li><b>切块</b><span>保留页码与版面来源</span></li>
            <li><b>向量化</b><span>写入 Qdrant 供语义检索</span></li>
            <li><b>检索</b><span>返回原文片段与出处</span></li>
          </ol>
        </section>

        <el-alert
          v-if="info?.embedding_degraded"
          type="warning"
          :closable="false"
          show-icon
          title="当前使用本地降级向量"
          description="检索仅按词面相近度排序。配置 Embedding API 后重建索引可获得真正的语义检索。"
        />
        <el-alert
          v-else-if="info"
          type="success"
          :closable="false"
          show-icon
          :title="`向量模型：${info.embedding_model || '未命名'}（${info.embedding_dim} 维）`"
          :description="`Qdrant 运行于${info.qdrant_mode === 'local' ? '本地嵌入式' : '服务'}模式`"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(300px, 1fr);
  gap: 16px;
  align-items: start;
}

.side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chart {
  height: 210px;
  width: 100%;
}

.doc-link {
  color: var(--kf-ink);
  cursor: pointer;
  font-weight: 500;
}

.doc-link:hover {
  color: var(--kf-primary);
}

.pipeline {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13.5px;
}

.pipeline li b {
  display: block;
  font-size: 14px;
  margin-bottom: 2px;
}

.pipeline li span {
  color: var(--kf-muted);
}

@media (max-width: 1180px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
