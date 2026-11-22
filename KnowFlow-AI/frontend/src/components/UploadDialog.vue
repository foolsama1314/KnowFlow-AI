<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadRawFile, UploadUserFile } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { api } from '@/api'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'uploaded'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const fileList = ref<UploadUserFile[]>([])
const uploading = ref(false)
const percent = ref(0)
const failures = ref<{ name: string; message: string }[]>([])
const succeededCount = ref(0)

const ACCEPT = '.pdf,.docx,.txt,.md,.markdown,.jpg,.jpeg,.png,.bmp,.webp'

watch(visible, (value) => {
  if (value) {
    fileList.value = []
    percent.value = 0
    failures.value = []
    succeededCount.value = 0
  }
})

async function submit() {
  const files = fileList.value
    .map((item) => item.raw)
    .filter((raw): raw is UploadRawFile => Boolean(raw))
  if (!files.length) {
    ElMessage.warning('请先选择需要导入的文件')
    return
  }
  uploading.value = true
  percent.value = 0
  failures.value = []
  try {
    const result = await api.uploadFiles(files, (value) => {
      percent.value = value
    })
    succeededCount.value = result.succeeded.length
    failures.value = result.failed
    emit('uploaded')
    window.dispatchEvent(new CustomEvent('knowflow:documents-updated'))
    if (!result.failed.length) {
      ElMessage.success(`已导入 ${result.succeeded.length} 份资料，正在后台解析`)
      visible.value = false
    } else {
      ElMessage.warning(
        `成功 ${result.succeeded.length} 份，失败 ${result.failed.length} 份，请查看失败原因`,
      )
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="导入资料" width="640px" :close-on-click-modal="!uploading">
    <el-upload
      v-model:file-list="fileList"
      drag
      multiple
      :auto-upload="false"
      :accept="ACCEPT"
      :disabled="uploading"
    >
      <el-icon class="upload-icon"><UploadFilled /></el-icon>
      <div class="upload-text">将文件拖到此处，或 <em>点击选择</em></div>
      <template #tip>
        <div class="upload-tip">
          支持 PDF、DOCX、TXT、Markdown、JPG/PNG/BMP/WEBP；单文件默认不超过
          {{ 200 }} MB。上传后自动进入解析队列。
        </div>
      </template>
    </el-upload>

    <el-progress
      v-if="uploading"
      :percentage="percent"
      :stroke-width="8"
      class="upload-progress"
    />

    <div v-if="succeededCount > 0" class="result-ok">
      已成功提交 {{ succeededCount }} 份资料，可在「任务中心」查看解析进度。
    </div>

    <div v-if="failures.length" class="result-fail">
      <p class="fail-title">以下文件未能导入：</p>
      <ul>
        <li v-for="item in failures" :key="item.name">
          <strong>{{ item.name }}</strong>：{{ item.message }}
        </li>
      </ul>
    </div>

    <template #footer>
      <el-button :disabled="uploading" @click="visible = false">关闭</el-button>
      <el-button type="primary" :loading="uploading" @click="submit">
        {{ uploading ? '上传中…' : '开始导入' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.upload-icon {
  font-size: 42px;
  color: #9fb4b9;
  margin-bottom: 8px;
}

.upload-text {
  color: #55696f;
  font-size: 14px;
}

.upload-text em {
  color: var(--kf-primary);
  font-style: normal;
  font-weight: 600;
}

.upload-tip {
  margin-top: 10px;
  color: var(--kf-muted);
  font-size: 12.5px;
  line-height: 1.7;
}

.upload-progress {
  margin-top: 16px;
}

.result-ok {
  margin-top: 16px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--kf-primary-soft);
  color: #1a6458;
  font-size: 13.5px;
}

.result-fail {
  margin-top: 14px;
  padding: 12px 16px;
  border-radius: 10px;
  background: #fdf1ee;
  color: #9c3f2c;
  font-size: 13px;
}

.fail-title {
  font-weight: 600;
  margin-bottom: 6px;
}

.result-fail ul {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
}
</style>
