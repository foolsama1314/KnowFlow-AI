<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatDotRound, Delete, Plus, Promotion, VideoPause } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { api } from '@/api'
import type { ChatMessage, ChatSession, Citation, SystemInfo } from '@/types'

const router = useRouter()

const sessions = ref<ChatSession[]>([])
const activeId = ref('')
const messages = ref<ChatMessage[]>([])
const question = ref('')
const loading = ref(false)
const streaming = ref(false)
const info = ref<SystemInfo | null>(null)
const listRef = ref<HTMLElement | null>(null)
let controller: AbortController | null = null

const ready = computed(
  () =>
    info.value?.retrieval_mode === 'semantic' &&
    info.value?.index_status.status === 'completed' &&
    info.value?.llm_configured === true,
)

const blockedReason = computed(() => {
  if (!info.value) return ''
  if (!info.value.llm_configured) {
    return '尚未配置大语言模型，请到「系统设置 → 大模型（LLM）」填写接口地址、API Key 和模型名称。'
  }
  if (info.value.index_status.status === 'unconfigured') {
    return '尚未配置真实 Embedding 服务，无法检索知识库。'
  }
  if (info.value.index_status.status !== 'completed') {
    return info.value.index_status.error || '向量索引尚未就绪，请先在「语义检索」页重建索引。'
  }
  return ''
})

function scrollBottom() {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function loadInfo() {
  try {
    info.value = await api.systemInfo()
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function refreshSessions() {
  try {
    const data = await api.listChatSessions(1, 50)
    sessions.value = data.items
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function loadSession(id: string) {
  loading.value = true
  try {
    const detail = await api.getChatSession(id)
    activeId.value = detail.session.id
    messages.value = detail.messages
    scrollBottom()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function createSession() {
  if (streaming.value) return
  try {
    const session = await api.createChatSession()
    sessions.value = [session, ...sessions.value]
    activeId.value = session.id
    messages.value = []
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

async function removeSession(session: ChatSession) {
  try {
    await ElMessageBox.confirm(`删除会话「${session.title}」？该操作不可恢复。`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api.deleteChatSession(session.id)
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
    if (activeId.value === session.id) {
      activeId.value = ''
      messages.value = []
    }
    ElMessage.success('会话已删除')
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function stop() {
  controller?.abort()
}

function openCitation(citation: Citation) {
  const query = citation.page_from ? { page: String(citation.page_from) } : {}
  router.push({ path: `/documents/${citation.document_id}`, query })
}

async function send() {
  const text = question.value.trim()
  if (!text || loading.value || streaming.value) return
  if (!ready.value) {
    ElMessage.warning(blockedReason.value || '当前无法问答')
    return
  }
  if (!activeId.value) await createSession()
  if (!activeId.value) return

  question.value = ''
  messages.value.push({
    id: `local-user-${Date.now()}`,
    session_id: activeId.value,
    role: 'user',
    content: text,
    citations: null,
    created_at: new Date().toISOString(),
  })
  const target: ChatMessage = {
    id: `local-assistant-${Date.now()}`,
    session_id: activeId.value,
    role: 'assistant',
    content: '',
    citations: [],
    created_at: new Date().toISOString(),
  }
  messages.value.push(target)
  scrollBottom()

  streaming.value = true
  controller = new AbortController()
  try {
    await api.streamChat(
      activeId.value,
      text,
      {
        onSources: (citations) => {
          target.citations = citations
        },
        onDelta: (delta) => {
          target.content += delta
          scrollBottom()
        },
        onDone: (data) => {
          target.id = data.message_id
          target.content = data.content || target.content
          target.citations = data.citations
        },
        onError: (message) => {
          if (!target.content) target.content = `生成失败：${message}`
          ElMessage.error(message)
        },
      },
      controller.signal,
    )
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      ElMessage.info('已停止生成')
    } else {
      ElMessage.error((error as Error).message)
    }
  } finally {
    streaming.value = false
    controller = null
    if (!target.content) target.content = '（未生成内容）'
    if (activeId.value) await loadSession(activeId.value)
    await refreshSessions()
  }
}

function splitCitations(message: ChatMessage): { cited: Citation[]; others: Citation[] } {
  const list = message.citations ?? []
  return {
    cited: list.filter((item) => item.cited),
    others: list.filter((item) => !item.cited),
  }
}

onMounted(async () => {
  await loadInfo()
  await refreshSessions()
  if (sessions.value.length) await loadSession(sessions.value[0].id)
})

onBeforeUnmount(() => {
  controller?.abort()
})
</script>

<template>
  <div class="chat-page" v-loading="loading">
    <aside class="session-side">
      <el-button type="primary" :icon="Plus" class="new-btn" @click="createSession">
        新建对话
      </el-button>
      <div class="session-list">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === activeId }"
          @click="loadSession(session.id)"
        >
          <el-icon :size="16"><ChatDotRound /></el-icon>
          <div class="session-text">
            <strong>{{ session.title }}</strong>
            <small>{{ dayjs(session.updated_at).format('MM-DD HH:mm') }}</small>
          </div>
          <el-button
            text
            :icon="Delete"
            class="session-del"
            @click.stop="removeSession(session)"
          />
        </div>
        <p v-if="!sessions.length" class="session-empty">还没有对话，点上方新建</p>
      </div>
    </aside>

    <section class="chat-main">
      <header class="chat-head">
        <div>
          <h1 class="page-title">智能问答</h1>
          <p class="page-desc">基于你的知识库检索后回答，每条结论都标注真实出处。</p>
        </div>
        <div v-if="info" class="model-chip">
          {{ info.llm_configured ? '大模型已配置' : '大模型未配置' }} ·
          {{ info.index_status.chunk_count }} 个文本块
        </div>
      </header>

      <el-alert
        v-if="blockedReason && info"
        type="warning"
        :closable="false"
        show-icon
        :title="blockedReason"
      />

      <div ref="listRef" class="messages">
        <div v-if="!messages.length" class="empty">
          <el-icon :size="34"><ChatDotRound /></el-icon>
          <p>向知识库提一个问题，例如「咖啡烘焙的一爆是怎么形成的？」</p>
          <small>回答只依据已建立索引的文档，资料不足时会明确拒答。</small>
        </div>

        <div v-for="message in messages" :key="message.id" class="msg" :class="message.role">
          <div class="bubble">{{ message.content }}</div>

          <div v-if="message.role === 'assistant' && message.citations?.length" class="citations">
            <div v-if="splitCitations(message).cited.length" class="citation-group">
              <span class="citation-label">引用资料</span>
              <button
                v-for="(citation, index) in splitCitations(message).cited"
                :key="citation.chunk_id"
                type="button"
                class="citation"
                @click="openCitation(citation)"
              >
                <span class="citation-index">{{ index + 1 }}</span>
                <span class="citation-body">
                  <strong>{{ citation.document_name }}</strong>
                  <small>
                    {{ citation.page_from ? `第 ${citation.page_from} 页` : '全文' }} ·
                    相似度 {{ citation.score.toFixed(2) }}
                  </small>
                  <em>{{ citation.snippet }}</em>
                </span>
              </button>
            </div>

            <el-collapse v-if="splitCitations(message).others.length" class="other-collapse">
              <el-collapse-item
                :title="`另有 ${splitCitations(message).others.length} 条检索结果未被回答引用`"
              >
                <button
                  v-for="citation in splitCitations(message).others"
                  :key="citation.chunk_id"
                  type="button"
                  class="citation other"
                  @click="openCitation(citation)"
                >
                  <span class="citation-body">
                    <strong>{{ citation.document_name }}</strong>
                    <small>
                      {{ citation.page_from ? `第 ${citation.page_from} 页` : '全文' }} ·
                      相似度 {{ citation.score.toFixed(2) }}
                    </small>
                    <em>{{ citation.snippet }}</em>
                  </span>
                </button>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
      </div>

      <footer class="composer">
        <el-input
          v-model="question"
          type="textarea"
          :rows="3"
          resize="none"
          maxlength="2000"
          placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
          :disabled="!ready || streaming"
          @keydown.enter.exact.prevent="send"
        />
        <div class="composer-actions">
          <span class="hint">单轮问答 · 仅依据检索到的资料回答</span>
          <el-button v-if="streaming" :icon="VideoPause" @click="stop">停止生成</el-button>
          <el-button
            v-else
            type="primary"
            :icon="Promotion"
            :disabled="!ready || !question.trim()"
            @click="send"
          >发送</el-button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.chat-page {
  height: 100%;
  display: flex;
  gap: 18px;
  padding: 20px 24px 24px;
  min-height: 0;
}

.session-side {
  width: 248px;
  flex: 0 0 248px;
  background: var(--kf-panel);
  border: 1px solid var(--kf-line);
  border-radius: 14px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.new-btn {
  width: 100%;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 10px;
  border-radius: 10px;
  cursor: pointer;
  color: var(--kf-muted);
  transition: background 0.15s ease;
}

.session-item:hover {
  background: var(--kf-bg);
}

.session-item.active {
  background: var(--kf-primary-soft);
  color: var(--kf-primary);
}

.session-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-text strong {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-text small {
  font-size: 11px;
  color: var(--kf-muted);
}

.session-del {
  opacity: 0;
}

.session-item:hover .session-del {
  opacity: 1;
}

.session-empty {
  font-size: 12px;
  color: var(--kf-muted);
  text-align: center;
  padding: 20px 0;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.chat-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-title {
  font-size: 22px;
  font-weight: 700;
}

.page-desc {
  margin-top: 4px;
  color: var(--kf-muted);
  font-size: 13px;
}

.model-chip {
  font-size: 12px;
  color: var(--kf-muted);
  background: var(--kf-panel);
  border: 1px solid var(--kf-line);
  border-radius: 999px;
  padding: 5px 12px;
  white-space: nowrap;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: var(--kf-panel);
  border: 1px solid var(--kf-line);
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty {
  margin: auto;
  text-align: center;
  color: var(--kf-muted);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  max-width: 420px;
}

.empty small {
  font-size: 12px;
  opacity: 0.8;
}

.msg {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 82%;
}

.msg.user {
  align-self: flex-end;
  align-items: flex-end;
}

.msg.assistant {
  align-self: flex-start;
}

.bubble {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
  font-size: 14px;
  padding: 11px 14px;
  border-radius: 12px;
  background: var(--kf-bg);
}

.msg.user .bubble {
  background: var(--kf-primary);
  color: #fff;
}

.citations {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.citation-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.citation-label {
  font-size: 12px;
  color: var(--kf-muted);
}

.citation {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  text-align: left;
  border: 1px solid var(--kf-line);
  background: #fff;
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.citation:hover {
  border-color: var(--kf-primary);
  background: var(--kf-primary-soft);
}

.citation-index {
  flex: 0 0 20px;
  height: 20px;
  border-radius: 6px;
  background: var(--kf-primary-soft);
  color: var(--kf-primary);
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.citation-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.citation-body strong {
  font-size: 13px;
  color: var(--kf-ink);
}

.citation-body small {
  font-size: 11px;
  color: var(--kf-muted);
}

.citation-body em {
  font-style: normal;
  font-size: 12px;
  color: var(--kf-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.citation.other {
  width: 100%;
  margin-bottom: 6px;
}

.other-collapse {
  border: none;
}

.other-collapse :deep(.el-collapse-item__header) {
  font-size: 12px;
  color: var(--kf-muted);
  border-bottom: none;
  background: transparent;
  height: 30px;
}

.composer {
  background: var(--kf-panel);
  border: 1px solid var(--kf-line);
  border-radius: 14px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hint {
  font-size: 12px;
  color: var(--kf-muted);
}
</style>
