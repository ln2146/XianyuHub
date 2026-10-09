<script setup lang="ts">
/**
 * 商品图片上传组件：
 * - 空状态展示大面积拖拽区域，支持点击选择、拖拽进入、⌘V / Ctrl+V 粘贴截图
 * - 已有图片以网格展示，支持拖拽添加更多图片
 * - 支持设为首图、删除图片、全屏大图预览
 * - 支持并发上传占位与数量上限控制
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, type UploadRequestOptions } from 'element-plus'
import { Close, Picture, Star, UploadFilled } from '@element-plus/icons-vue'
import { uploadImage, uploadUrl } from '@/api/goods'

const props = withDefaults(
  defineProps<{
    max?: number
    pasteable?: boolean
    allowCover?: boolean
  }>(),
  {
    max: 9,
    pasteable: true,
    allowCover: true,
  },
)

const ids = defineModel<string[]>({ required: true })
const uploading = defineModel<number>('uploading', { default: 0 })

const pending = ref(0)
watch(pending, (n) => {
  uploading.value = n
})

const MAX_SIZE = 10 * 1024 * 1024 // 10MB

function accept(file: File): boolean {
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('只能上传图片文件')
    return false
  }
  if (file.size > MAX_SIZE) {
    ElMessage.warning('单张图片大小不能超过 10MB')
    return false
  }
  if (ids.value.length + pending.value >= props.max) {
    ElMessage.warning(`最多上传 ${props.max} 张图片`)
    return false
  }
  return true
}

async function upload(file: File) {
  pending.value += 1
  try {
    const res = await uploadImage(file)
    if (ids.value.length < props.max) {
      ids.value.push(res.id)
    }
  } catch {
    /* 错误已由 axios 拦截器提示 */
  } finally {
    pending.value -= 1
  }
}

const beforeUpload = (file: File) => accept(file)
const onRequest = (opt: UploadRequestOptions) => upload(opt.file)

function remove(index: number) {
  ids.value.splice(index, 1)
}

function makeCover(index: number) {
  const [target] = ids.value.splice(index, 1)
  if (target) {
    ids.value.unshift(target)
  }
}

// 粘贴上传截图支持
function onPaste(e: ClipboardEvent) {
  // 若用户正在输入框/文本域中编辑文字，不强行拦截文字粘贴
  const target = e.target as HTMLElement | null
  const isTyping = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')
  const files = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith('image/'))
  if (!files.length) return
  if (isTyping && !e.clipboardData?.types.includes('Files')) return

  e.preventDefault()
  let added = 0
  for (const f of files) {
    if (!accept(f)) break
    upload(f)
    added += 1
  }
  if (added) {
    ElMessage.success(`已从剪贴板添加 ${added} 张图片`)
  }
}

onMounted(() => {
  if (props.pasteable) {
    document.addEventListener('paste', onPaste)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('paste', onPaste)
})

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
</script>

<template>
  <div class="uploader-root">
    <!-- 无图片时：大面积拖拽与上传引导区域 -->
    <el-upload
      v-if="!ids.length && !pending"
      class="zone"
      drag
      multiple
      accept="image/*"
      :show-file-list="false"
      :before-upload="beforeUpload"
      :http-request="onRequest"
    >
      <el-icon class="zone-icon"><UploadFilled /></el-icon>
      <div class="zone-title">拖拽商品图片到这里，或 <em>点击上传</em></div>
      <div class="zone-sub">
        支持多选，最多 {{ max }} 张，单张 ≤ 10MB
        <template v-if="pasteable"> · 也可以直接快捷键 {{ isMac ? '⌘' : 'Ctrl' }}+V 粘贴截图</template>
      </div>
    </el-upload>

    <!-- 已有图片时：网格展示 -->
    <div v-else class="grid">
      <div v-for="(id, i) in ids" :key="id" class="tile">
        <el-image
          :src="uploadUrl(id)"
          fit="cover"
          class="img"
          :preview-src-list="ids.map(uploadUrl)"
          :initial-index="i"
          preview-teleported
          hide-on-click-modal
        >
          <template #error>
            <div class="img-fallback"><el-icon><Picture /></el-icon></div>
          </template>
        </el-image>
        <span v-if="i === 0" class="cover">首图</span>
        <div class="ops">
          <button v-if="allowCover && i > 0" type="button" class="op" title="设为首图" @click.stop="makeCover(i)">
            <el-icon><Star /></el-icon>
          </button>
          <button type="button" class="op danger" title="移除" @click.stop="remove(i)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>

      <!-- 上传中占位方块 -->
      <div
        v-for="n in pending"
        :key="`pending-${n}`"
        v-loading="true"
        class="tile placeholder"
        element-loading-background="transparent"
      />

      <!-- 继续添加按钮 -->
      <el-upload
        v-if="ids.length + pending < max"
        class="add"
        drag
        multiple
        accept="image/*"
        :show-file-list="false"
        :before-upload="beforeUpload"
        :http-request="onRequest"
      >
        <el-icon :size="20"><UploadFilled /></el-icon>
        <span class="add-count">{{ ids.length + pending }}/{{ max }}</span>
      </el-upload>
    </div>
  </div>
</template>

<style scoped>
.uploader-root {
  width: 100%;
}

/* 空状态拖拽区域 */
.zone :deep(.el-upload) {
  width: 100%;
}
.zone :deep(.el-upload-dragger) {
  width: 100%;
  padding: 32px 16px;
  border-radius: 12px;
  border: 1.5px dashed #cfd5dd;
  background: linear-gradient(180deg, #fbfcfd 0%, #f6f9f8 100%);
  transition:
    border-color 0.2s,
    background 0.2s,
    transform 0.2s;
}
.zone :deep(.el-upload-dragger:hover),
.zone :deep(.el-upload-dragger.is-dragover) {
  border-color: var(--xh-primary);
  background: var(--el-color-primary-light-9);
}
.zone :deep(.el-upload-dragger.is-dragover) {
  transform: scale(1.008);
}
.zone-icon {
  font-size: 42px;
  color: var(--el-color-primary-light-3);
  margin-bottom: 8px;
}
.zone-title {
  font-size: 14px;
  color: var(--xh-text);
  font-weight: 500;
}
.zone-title em {
  color: var(--xh-primary);
  font-style: normal;
  font-weight: 600;
}
.zone-sub {
  margin-top: 6px;
  font-size: 12px;
  color: var(--xh-muted);
}

/* 缩略图网格 */
.grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.tile {
  position: relative;
  width: 92px;
  height: 92px;
  border-radius: 10px;
}
.img {
  width: 100%;
  height: 100%;
  border-radius: 10px;
  border: 1px solid var(--xh-border);
  display: block;
  transition: box-shadow 0.2s;
}
.tile:hover .img {
  box-shadow: 0 4px 12px rgba(31, 35, 41, 0.12);
}
.img-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f2f3f5;
  color: var(--xh-muted);
  font-size: 22px;
}
.placeholder {
  border: 1px solid var(--xh-border);
  background: #f7f8fa;
}
.cover {
  position: absolute;
  left: 0;
  bottom: 0;
  background: rgba(30, 158, 106, 0.9);
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  padding: 0 7px;
  border-radius: 0 8px 0 10px;
  pointer-events: none;
}
.ops {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transform: translateY(-2px);
  transition:
    opacity 0.15s,
    transform 0.15s;
}
.tile:hover .ops {
  opacity: 1;
  transform: none;
}
@media (hover: none) {
  .ops {
    opacity: 1;
    transform: none;
  }
}
.op {
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.op:hover {
  background: var(--xh-primary);
}
.op.danger:hover {
  background: var(--el-color-danger);
}

/* 追加上传小方块 */
.add :deep(.el-upload-dragger) {
  width: 92px;
  height: 92px;
  padding: 0;
  border-radius: 10px;
  border: 1.5px dashed #cfd5dd;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: var(--xh-muted);
  transition:
    border-color 0.2s,
    color 0.2s,
    background 0.2s;
}
.add :deep(.el-upload-dragger:hover),
.add :deep(.el-upload-dragger.is-dragover) {
  border-color: var(--xh-primary);
  color: var(--xh-primary);
  background: var(--el-color-primary-light-9);
}
.add-count {
  font-size: 12px;
}
</style>
