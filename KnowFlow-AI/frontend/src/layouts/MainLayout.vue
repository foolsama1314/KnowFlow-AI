<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatDotRound,
  Collection,
  DataAnalysis,
  Document,
  HomeFilled,
  List,
  Notebook,
  Search,
  Setting,
  UploadFilled,
} from '@element-plus/icons-vue'
import { api } from '@/api'
import UploadDialog from '@/components/UploadDialog.vue'

const route = useRoute()
const router = useRouter()

const collapsed = ref(false)
const uploadVisible = ref(false)
const online = ref(true)
const version = ref('')

const menus = [
  { path: '/dashboard', label: '工作台', icon: HomeFilled },
  { path: '/documents', label: '资料管理', icon: Document },
  { path: '/tasks', label: '任务中心', icon: List },
  { path: '/search', label: '语义检索', icon: Search },
  { path: '/chat', label: '智能问答', icon: ChatDotRound },
  { path: '/analysis', label: '多文档分析', icon: DataAnalysis },
  { path: '/reports', label: '研究报告', icon: Notebook },
  { path: '/settings', label: '系统设置', icon: Setting },
]

const activePath = computed(() => {
  if (route.path.startsWith('/documents')) return '/documents'
  return route.path
})

const pageTitle = computed(() => (route.meta.title as string) || '知枢 AI')

let timer: number | undefined

async function checkHealth() {
  try {
    const health = await api.health()
    online.value = health.status === 'ok'
    version.value = health.version
  } catch {
    online.value = false
  }
}

function openUpload() {
  uploadVisible.value = true
}

onMounted(() => {
  checkHealth()
  timer = window.setInterval(checkHealth, 30000)
  window.addEventListener('knowflow:open-upload', openUpload)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  window.removeEventListener('knowflow:open-upload', openUpload)
})
</script>

<template>
  <div class="layout">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand" @click="router.push('/dashboard')">
        <div class="brand-mark">
          <Collection :size="20" />
        </div>
        <div v-show="!collapsed" class="brand-text">
          <strong>知枢 AI</strong>
          <span>KnowFlow</span>
        </div>
      </div>

      <nav class="menu">
        <RouterLink
          v-for="item in menus"
          :key="item.path"
          :to="item.path"
          class="menu-item"
          :class="{ active: activePath === item.path }"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
          <span v-show="!collapsed">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div v-show="!collapsed" class="sidebar-foot">
        <div class="status-line">
          <i class="dot" :class="{ offline: !online }" />
          {{ online ? '本地服务运行中' : '服务未连接' }}
        </div>
        <p class="version">v{{ version || '0.1.0' }} · 本地部署</p>
      </div>

      <button class="collapse-btn" type="button" @click="collapsed = !collapsed">
        {{ collapsed ? '»' : '«' }}
      </button>
    </aside>

    <div class="main-area">
      <header class="topbar">
        <div class="topbar-left">
          <span class="crumb">知枢 AI</span>
          <span class="sep">/</span>
          <span class="current">{{ pageTitle }}</span>
        </div>
        <div class="topbar-right">
          <el-button :icon="Search" text class="search-jump" @click="router.push('/search')">语义检索</el-button>
          <el-button type="primary" :icon="UploadFilled" @click="uploadVisible = true">
            导入资料
          </el-button>
        </div>
      </header>

      <main class="content">
        <RouterView v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </RouterView>
      </main>
    </div>

    <UploadDialog v-model="uploadVisible" />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--kf-bg);
}

.sidebar {
  position: relative;
  width: 224px;
  flex: 0 0 224px;
  height: 100vh;
  background: var(--kf-sidebar);
  color: #dfe9ec;
  display: flex;
  flex-direction: column;
  padding: 22px 14px 18px;
  overflow-y: auto;
  overflow-x: hidden;
  transition: width 0.2s ease, flex-basis 0.2s ease;
}

.sidebar.collapsed {
  width: 78px;
  flex-basis: 78px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 6px 22px;
  cursor: pointer;
}

.brand-mark {
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: 11px;
  background: linear-gradient(135deg, #2a8f7d, #17625a);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #eafff9;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  overflow: hidden;
  white-space: nowrap;
}

.brand-text strong {
  font-size: 16px;
  color: #f2fbf9;
}

.brand-text span {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #7fa8a2;
}

.menu {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 11px 13px;
  border-radius: 10px;
  color: #b9ccd1;
  font-size: 14.5px;
  transition: background 0.16s ease, color 0.16s ease;
  white-space: nowrap;
}

.menu-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #ffffff;
}

.menu-item.active {
  background: rgba(42, 143, 125, 0.24);
  color: #8fe4d3;
  box-shadow: inset 2px 0 0 #43b39c;
}

.sidebar-foot {
  margin-top: auto;
  padding: 14px 8px 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
}

.status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: #a9c0c4;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #45c08a;
  box-shadow: 0 0 0 3px rgba(69, 192, 138, 0.16);
}

.dot.offline {
  background: #e0836a;
  box-shadow: 0 0 0 3px rgba(224, 131, 106, 0.16);
}

.version {
  margin-top: 6px;
  font-size: 11.5px;
  color: #6c868c;
}

.collapse-btn {
  position: absolute;
  right: -11px;
  top: 76px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid #29424a;
  background: #1b323b;
  color: #9db6bb;
  font-size: 11px;
  cursor: pointer;
  z-index: 3;
}

.main-area {
  flex: 1;
  min-width: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.topbar {
  height: 64px;
  flex: 0 0 64px;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--kf-line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  position: sticky;
  top: 0;
  z-index: 5;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 14px;
}

.crumb {
  color: var(--kf-muted);
}

.sep {
  color: #c3ced2;
}

.current {
  font-weight: 600;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

@media (max-width: 1024px) {
  .topbar {
    padding: 0 18px;
  }
}

@media (max-width: 780px) {
  .topbar {
    height: 56px;
    flex-basis: 56px;
    padding: 0 14px;
  }

  .search-jump {
    display: none;
  }
}
</style>
