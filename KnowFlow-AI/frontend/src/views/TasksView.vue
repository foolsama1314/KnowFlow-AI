<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { api } from '@/api'
import StatusTag from '@/components/StatusTag.vue'
import type { TaskEvent, TaskOut } from '@/types'

const router = useRouter()
const loading = ref(false)
const tasks = ref<TaskOut[]>([])
const filter = ref('')
const sources = new Map<string, EventSource>()
let fallbackTimer: number | undefined

const STATUS_OPTIONS = [
  { label: '全部任务', value: '' },
  { label: '执行中', value: 'running' },
  { label: '等待中', value: 'pending' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
]

function closeSource(taskId: string) {
  const source = sources.get(taskId)
  if (source) {
    source.close()
    sources.delete(taskId)
  }
}

function closeAll() {
  sources.forEach((source) => source.close())
  sources.clear()
}

function applyEvent(event: TaskEvent) {
  const row = tasks.value.find((item) => item.id === event.task_id)
  if (!row) return
  row.status = event.status
  row.progress = event.progress
  row.current_step = event.current_step
  row.error_message = event.error_message
  if (event.status === 'completed' || event.status === 'failed') {
    closeSource(row.id)
    window.setTimeout(() => load(true), 400)
  }
}

function bindStream(task: TaskOut) {
  if (sources.has(task.id)) return
  const source = new EventSource(api.taskEventsUrl(task.id))
  source.onmessage = (message) => {
    try {
      applyEvent(JSON.parse(message.data) as TaskEvent)
    } catch {
      // 忽略无法解析的心跳数据
    }
  }
  source.onerror = () => closeSource(task.id)
  sources.set(task.id, source)
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const data = await api.listTasks({ status: filter.value || undefined, limit: 100 })
    tasks.value = data.items
    tasks.value
      .filter((item) => item.status === 'running' || item.status === 'pending')
      .forEach(bindStream)
  } catch (error) {
    if (!silent) ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function retry(row: TaskOut) {
  try {
    await api.retryTask(row.id)
    ElMessage.success('已重新提交任务')
    await load()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function remove(row: TaskOut) {
  try {
    await ElMessageBox.confirm('确认删除这条任务记录？文档与其解析结果不会被删除。', '删除任务', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api.cancelTask(row.id)
    closeSource(row.id)
    ElMessage.success('任务记录已删除')
    load()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function changeFilter() {
  closeAll()
  load()
}

onMounted(async () => {
  await load()
  fallbackTimer = window.setInterval(() => {
    if (tasks.value.some((item) => item.status === 'running' || item.status === 'pending')) {
      load(true)
    }
  }, 8000)
})

onBeforeUnmount(() => {
  closeAll()
  if (fallbackTimer) window.clearInterval(fallbackTimer)
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">任务中心</h1>
        <p class="page-desc">解析、切块与向量化都在后台执行，进度实时推送，失败可重试。</p>
      </div>
      <el-button :icon="Refresh" @click="load()">刷新</el-button>
    </div>

    <section class="panel">
      <el-radio-group v-model="filter" @change="changeFilter" class="filters">
        <el-radio-button v-for="option in STATUS_OPTIONS" :key="option.value" :value="option.value">
          {{ option.label }}
        </el-radio-button>
      </el-radio-group>

      <el-table :data="tasks" v-loading="loading" size="large" empty-text="暂无任务记录">
        <el-table-column label="资料" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <a class="doc-link" @click="router.push(`/documents/${row.document_id}`)">
              {{ row.document_name || row.document_id }}
            </a>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <span class="tag-soft">{{ row.task_type === 'parse' ? '解析' : row.task_type }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="进度" min-width="230">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="row.progress"
                :stroke-width="8"
                :status="row.status === 'failed' ? 'exception' : row.status === 'completed' ? 'success' : undefined"
              />
              <span class="step">{{ row.current_step }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ dayjs(row.created_at).format('MM-DD HH:mm:ss') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.error_message"
              :content="row.error_message"
              placement="top"
              effect="dark"
            >
              <el-button text type="danger">失败原因</el-button>
            </el-tooltip>
            <el-button
              v-if="row.status === 'failed'"
              text
              type="primary"
              @click="retry(row)"
            >
              重试
            </el-button>
            <el-button
              v-if="row.status !== 'running'"
              text
              @click="remove(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.filters {
  margin-bottom: 16px;
}

.progress-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
}

.step {
  font-size: 12px;
  color: var(--kf-muted);
}

.doc-link {
  cursor: pointer;
  font-weight: 500;
}

.doc-link:hover {
  color: var(--kf-primary);
}
</style>
