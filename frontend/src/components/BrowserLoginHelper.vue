<script setup lang="ts">
// 通过浏览器扩展一键读取这个浏览器里的闲鱼登录态；没装扩展时给出安装步骤
import { onMounted, ref } from 'vue'
import { CopyDocument, Lightning, Pointer } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getBrowserCookies, helperVersion, type HelperCookies } from '@/utils/loginHelper'

const props = defineProps<{ expectUnb?: string }>()
const emit = defineEmits<{ (e: 'got', cookies: string, info: HelperCookies): void }>()
const autoRenew = defineModel<boolean>('autoRenew', { default: true })

const installed = ref(false)
const busy = ref(false)
const error = ref('')
const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname)

onMounted(() => {
  installed.value = !!helperVersion()
})

async function fetchCookies() {
  error.value = ''
  busy.value = true
  try {
    const res = await getBrowserCookies()
    if (!res.loggedIn) {
      error.value = '这个浏览器还没有登录闲鱼网页版：请先打开闲鱼网页版登录，再点一次。'
      return
    }
    if (props.expectUnb && res.unb !== props.expectUnb) {
      error.value = `浏览器里登录的是「${res.nick || res.unb}」，不是这个账号。请在闲鱼网页版切换到这个账号后再试。`
      return
    }
    emit('got', JSON.stringify({ cookies: res.cookies }), res)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

const reload = () => window.location.reload()

function copyExtensionsUrl() {
  navigator.clipboard.writeText('chrome://extensions')
  ElMessage.success('已复制 chrome://extensions 到剪贴板')
}
</script>

<template>
  <div class="login-helper-card" :class="{ 'is-installed': installed }">
    <!-- 状态 1: 扩展已安装 -->
    <template v-if="installed">
      <div class="helper-ready-box">
        <div class="ready-header">
          <div class="ready-icon-wrap">
            <el-icon><Lightning /></el-icon>
          </div>
          <div class="ready-meta">
            <div class="ready-title">
              <span>已连接浏览器扩展助手</span>
              <span class="ready-tag">免手动复制</span>
            </div>
            <p class="ready-desc">直接读取当前浏览器「闲鱼网页版」登录态并填入下方</p>
          </div>
        </div>

        <div class="ready-actions">
          <el-button
            type="primary"
            class="fetch-btn"
            :icon="Pointer"
            :loading="busy"
            @click="fetchCookies"
          >
            从当前浏览器一键读取 Cookie
          </el-button>
          <div class="auto-renew-row">
            <el-checkbox v-model="autoRenew">账号掉线时，自动从本浏览器静默同步恢复</el-checkbox>
          </div>
        </div>

        <p class="ready-hint">
          还没登录？先 <el-link type="primary" href="https://www.goofish.com" target="_blank">打开闲鱼网页版</el-link> 登录此账号。
        </p>
      </div>
    </template>

    <!-- 状态 2: 扩展未安装 -->
    <template v-else>
      <div class="helper-guide-box">
        <div class="guide-header">
          <div class="guide-icon-wrap">
            <el-icon><Lightning /></el-icon>
          </div>
          <div class="guide-title-wrap">
            <span class="guide-title">使用浏览器扩展一键同步</span>
            <span class="guide-tag">免手动复制</span>
          </div>
        </div>

        <div class="steps-list">
          <div class="step-item">
            <span class="step-num">1</span>
            <div class="step-content">
              <span>在浏览器地址栏打开</span>
              <code class="step-code">chrome://extensions</code>
              <el-tooltip content="点击复制地址" placement="top">
                <el-button link size="small" :icon="CopyDocument" class="copy-btn" @click="copyExtensionsUrl" />
              </el-tooltip>
              <span>开启「开发者模式」</span>
            </div>
          </div>

          <div class="step-item">
            <span class="step-num">2</span>
            <div class="step-content">
              <span>点击「加载已解压的扩展程序」，选择项目根目录下的</span>
              <code class="step-code">extension</code>
              <span>文件夹</span>
            </div>
          </div>

          <div class="step-item">
            <span class="step-num">3</span>
            <div class="step-content">
              <span>在当前浏览器登录</span>
              <el-link type="primary" href="https://www.goofish.com" target="_blank" class="step-link">闲鱼网页版</el-link>
              <span>，完成后点击</span>
              <el-link type="primary" class="step-link" @click="reload">刷新本页</el-link>
            </div>
          </div>
        </div>

        <div v-if="!isLocal" class="guide-footer-tip">
          💡 非 localhost 访问提示：装好后请点击扩展图标，开启「在当前网址启用一键导入」。
        </div>
      </div>
    </template>

    <!-- 错误反馈 -->
    <div v-if="error" class="helper-error-tip">
      <span class="err-icon">⚠️</span>
      <span>{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.login-helper-card {
  border: 1px solid var(--xh-border, #e2e8f0);
  border-radius: 12px;
  background: var(--xh-card, #ffffff);
  overflow: hidden;
  transition: all 0.2s ease;
}

.login-helper-card.is-installed {
  border-color: rgba(16, 185, 129, 0.3);
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.4) 0%, rgba(255, 255, 255, 1) 100%);
}

/* 扩展就绪样式 */
.helper-ready-box {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ready-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ready-icon-wrap {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: #ecfdf5;
  color: #059669;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.ready-meta {
  flex: 1;
  min-width: 0;
}

.ready-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--xh-text, #0f172a);
}

.ready-tag {
  font-size: 11px;
  font-weight: 500;
  color: #059669;
  background: #d1fae5;
  padding: 1px 6px;
  border-radius: 4px;
}

.ready-desc {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--xh-muted, #64748b);
}

.ready-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.fetch-btn {
  width: 100%;
  height: 38px;
  font-weight: 600;
  border-radius: 8px;
}

.auto-renew-row {
  display: flex;
  align-items: center;
  font-size: 12px;
}

.ready-hint {
  margin: 0;
  font-size: 11.5px;
  color: var(--xh-muted, #94a3b8);
}

/* 扩展安装指引样式 */
.helper-guide-box {
  padding: 14px 16px;
  background: #f8fafc;
}

.guide-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.guide-icon-wrap {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
}

.guide-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.guide-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--xh-text, #0f172a);
}

.guide-tag {
  font-size: 11px;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid rgba(16, 185, 129, 0.2);
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--xh-text-2, #334155);
}

.step-num {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-content {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  line-height: 1.5;
}

.step-code {
  padding: 1px 6px;
  border-radius: 4px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  font-family: monospace;
  font-size: 11.5px;
  color: #0f172a;
}

.copy-btn {
  padding: 0 2px !important;
  height: auto !important;
  color: #64748b;
}

.copy-btn:hover {
  color: #059669;
}

.step-link {
  font-size: 12px;
}

.guide-footer-tip {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed #e2e8f0;
  font-size: 11px;
  color: var(--xh-muted, #64748b);
  line-height: 1.4;
}

.helper-error-tip {
  margin: 10px 16px 12px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 6px;
  font-size: 12px;
  color: #dc2626;
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
