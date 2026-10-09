<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Cpu, Promotion, Refresh, Search } from '@element-plus/icons-vue'
import {
  handleSuggestion,
  listConversations,
  listMessages,
  listSuggestions,
  markRead,
  sendMessage,
  setTakeover,
  testReply,
  type ChatMessage,
  type Conversation,
  type ReplyPlan,
  type Suggestion,
} from '@/api/message'
import JsonBlock from '@/components/JsonBlock.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useRealtimeStore, type RealtimeEvent } from '@/stores/realtime'
import { useMobile } from '@/composables/useMobile'
import { fmtRelative, fmtTime, itemUrl, sourceMap } from '@/utils/format'

const accounts = useAccountsStore()
const realtime = useRealtimeStore()
const isMobile = useMobile()

// ---------------------------------------------------------------- 会话列表
const convs = ref<Conversation[]>([])
const convLoading = ref(false)
const convMoreLoading = ref(false)
const convTotal = ref(0)
const CONV_PAGE = 50
const filter = reactive({ account_id: undefined as number | undefined, q: '' })
const currentId = ref<number | null>(null)
const current = computed(() => convs.value.find((c) => c.id === currentId.value) || null)

const convParams = () => ({ account_id: filter.account_id, q: filter.q.trim() || undefined })

/** 重新加载会话列表；静默刷新（实时推送）时保留已加载的条数，避免“加载更多”的内容被收起 */
async function loadConvs(silent = false) {
  if (!silent) convLoading.value = true
  try {
    const limit = silent ? Math.min(200, Math.max(CONV_PAGE, convs.value.length)) : CONV_PAGE
    const res = await listConversations({ ...convParams(), limit, offset: 0 })
    convs.value = res.items
    convTotal.value = res.total
  } finally {
    convLoading.value = false
  }
}

async function loadMoreConvs() {
  convMoreLoading.value = true
  try {
    const res = await listConversations({ ...convParams(), limit: CONV_PAGE, offset: convs.value.length })
    // 列表按最新消息排序，翻页期间可能有会话移动位置，按 id 去重
    const seen = new Set(convs.value.map((c) => c.id))
    convs.value = [...convs.value, ...res.items.filter((c) => !seen.has(c.id))]
    convTotal.value = res.total
  } finally {
    convMoreLoading.value = false
  }
}

// ---------------------------------------------------------------- 消息
const messages = ref<ChatMessage[]>([])
const msgLoading = ref(false)
const hasOlder = ref(false)
const suggestions = ref<Suggestion[]>([])
const threadEl = ref<HTMLElement>()

function scrollBottom() {
  nextTick(() => {
    if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight
  })
}

async function loadThread(silent = false) {
  const id = currentId.value
  if (!id) return
  if (!silent) msgLoading.value = true
  try {
    const [msgs, sugs] = await Promise.all([listMessages(id), listSuggestions(id).catch(() => [])])
    if (currentId.value !== id) return
    messages.value = msgs
    hasOlder.value = msgs.length >= 100
    suggestions.value = sugs
    scrollBottom()
  } finally {
    msgLoading.value = false
  }
  const conv = convs.value.find((c) => c.id === id)
  if (conv?.unread) {
    await markRead(id).catch(() => undefined)
    conv.unread = 0
  }
}

async function loadOlder() {
  const id = currentId.value
  const first = messages.value[0]
  if (!id || !first) return
  const el = threadEl.value
  const prevHeight = el?.scrollHeight || 0
  const older = await listMessages(id, first.id)
  messages.value = [...older, ...messages.value]
  hasOlder.value = older.length >= 100
  nextTick(() => {
    if (el) el.scrollTop = el.scrollHeight - prevHeight
  })
}

function select(c: Conversation) {
  if (currentId.value === c.id) return
  currentId.value = c.id
  messages.value = []
  suggestions.value = []
  draft.value = ''
  loadThread()
}

// ---------------------------------------------------------------- 发送
const draft = ref('')
const sending = ref(false)

async function send() {
  const text = draft.value.trim()
  if (!text || !currentId.value) return
  sending.value = true
  try {
    const msg = await sendMessage(currentId.value, text)
    if (!messages.value.some((m) => m.id === msg.id)) messages.value.push(msg)
    draft.value = ''
    scrollBottom()
    loadConvs(true)
  } catch {
    /* 拦截器已提示 */
  } finally {
    sending.value = false
  }
}

function onKeydown(evt: Event | KeyboardEvent) {
  // Ctrl / Cmd + Enter 发送
  const e = evt as KeyboardEvent
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    send()
  }
}

// ---------------------------------------------------------------- AI 建议
const sugBusy = reactive<Record<number, boolean>>({})
async function onSuggestion(s: Suggestion, action: 'send' | 'discard') {
  sugBusy[s.id] = true
  try {
    await handleSuggestion(s.id, action)
    suggestions.value = suggestions.value.filter((x) => x.id !== s.id)
    ElMessage.success(action === 'send' ? '已发送' : '已丢弃')
    if (action === 'send') loadThread(true)
  } catch {
    /* 拦截器已提示 */
  } finally {
    sugBusy[s.id] = false
  }
}

function useSuggestion(s: Suggestion) {
  draft.value = s.text
}

// ---------------------------------------------------------------- 人工接管
const takeoverMinutes = ref(60)
const takeoverOpen = ref(false)
async function applyTakeover(minutes: number) {
  if (!currentId.value) return
  try {
    const updated = await setTakeover(currentId.value, minutes)
    const idx = convs.value.findIndex((c) => c.id === updated.id)
    if (idx >= 0) convs.value[idx] = updated
    takeoverOpen.value = false
    ElMessage.success(minutes ? `已接管 ${minutes} 分钟，期间不会自动回复` : '已恢复自动回复')
  } catch {
    /* 拦截器已提示 */
  }
}

// ---------------------------------------------------------------- 试运行
const trial = reactive({ open: false, text: '', loading: false, plan: null as ReplyPlan | null })
const actionLabel: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  send: { label: '直接回复', type: 'success' },
  suggest: { label: '生成建议（待人工确认）', type: 'primary' },
  handoff: { label: '转人工', type: 'danger' },
  none: { label: '不回复', type: 'info' },
}
function openTrial() {
  const lastBuyer = [...messages.value].reverse().find((m) => m.direction === 'in' && !m.is_system)
  Object.assign(trial, { open: true, text: lastBuyer?.text || '', plan: null })
}
async function runTrial() {
  if (!currentId.value || !trial.text.trim()) return
  trial.loading = true
  try {
    trial.plan = await testReply(currentId.value, trial.text.trim())
  } catch {
    /* 拦截器已提示 */
  } finally {
    trial.loading = false
  }
}
const planExtra = computed(() => {
  if (!trial.plan) return null
  const { action: _a, text: _t, source: _s, intent: _i, note: _n, ...rest } = trial.plan
  return Object.keys(rest).length ? rest : null
})

// ---------------------------------------------------------------- 实时推送
let refreshTimer: number | undefined
function scheduleListRefresh() {
  // 合并短时间内的多次推送
  window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(() => loadConvs(true), 400)
}

async function onRealtime(ev: RealtimeEvent) {
  const convId = ev.data.conversation_id
  if (ev.event === 'message') {
    scheduleListRefresh()
    if (convId && convId === currentId.value) {
      const fresh = await listMessages(convId).catch(() => null)
      if (fresh && currentId.value === convId) {
        messages.value = fresh
        scrollBottom()
        markRead(convId).catch(() => undefined)
      }
    }
  } else if (ev.event === 'suggestion') {
    scheduleListRefresh()
    if (convId && convId === currentId.value) {
      suggestions.value = await listSuggestions(convId).catch(() => suggestions.value)
    }
  }
}

let unsubscribe: (() => void) | undefined
onMounted(() => {
  accounts.load().catch(() => undefined)
  loadConvs()
  unsubscribe = realtime.subscribe(onRealtime)
})
onBeforeUnmount(() => {
  unsubscribe?.()
  window.clearTimeout(refreshTimer)
})

function bubbleClass(m: ChatMessage) {
  return [m.direction === 'in' ? 'in' : 'out', sourceMap[m.source]?.cls || 'src-system']
}

const showList = computed(() => !isMobile.value || !currentId.value)
const showThread = computed(() => !isMobile.value || !!currentId.value)
</script>

<template>
  <div class="inbox">
    <!-- 会话列表 -->
    <section v-show="showList" class="list-pane">
      <div class="list-head">
        <el-select v-model="filter.account_id" clearable placeholder="全部账号" size="small" class="acc-sel" @change="loadConvs()">
          <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
        </el-select>
        <el-button size="small" :icon="Refresh" :loading="convLoading" circle @click="loadConvs()" />
      </div>
      <div class="list-search">
        <el-input v-model="filter.q" size="small" placeholder="搜索买家 / 消息" clearable :prefix-icon="Search" @keyup.enter="loadConvs()" @clear="loadConvs()" />
      </div>
      <el-scrollbar v-loading="convLoading && !convs.length" class="list-scroll">
        <el-empty v-if="!convLoading && !convs.length" description="暂无会话" :image-size="60" />
        <div
          v-for="c in convs"
          :key="c.id"
          class="conv"
          :class="{ active: c.id === currentId }"
          @click="select(c)"
        >
          <el-badge :value="c.unread" :hidden="!c.unread" :max="99">
            <el-avatar :size="38" class="conv-avatar">{{ (c.peer_name || '买').slice(0, 1) }}</el-avatar>
          </el-badge>
          <div class="conv-main">
            <div class="conv-top">
              <span class="conv-name ellipsis">{{ c.peer_name || c.peer_id || '买家' }}</span>
              <span class="conv-time">{{ fmtRelative(c.last_message_at) }}</span>
            </div>
            <div class="conv-bottom">
              <span class="conv-last ellipsis">{{ c.last_message }}</span>
              <el-tag v-if="c.in_takeover" size="small" type="warning" effect="plain" class="tk">接管中</el-tag>
            </div>
            <div class="muted conv-acc ellipsis">{{ accounts.nameOf(c.account_id) }}</div>
          </div>
        </div>
        <div v-if="convs.length" class="conv-foot">
          <span class="muted small">共 {{ convTotal }} 个会话</span>
          <el-button v-if="convs.length < convTotal" link type="primary" size="small" :loading="convMoreLoading" @click="loadMoreConvs">加载更多</el-button>
        </div>
      </el-scrollbar>
    </section>

    <!-- 消息线程 -->
    <section v-show="showThread" class="thread-pane">
      <template v-if="current">
        <header class="thread-head">
          <div class="th-left">
            <el-button v-if="isMobile" :icon="ArrowLeft" circle size="small" @click="currentId = null" />
            <div class="th-info">
              <div class="th-name">
                {{ current.peer_name || '买家' }}
                <el-tag v-if="current.in_takeover" size="small" type="warning">人工接管中</el-tag>
              </div>
              <div class="muted small ellipsis">
                {{ accounts.nameOf(current.account_id) }}
                <template v-if="current.item_id">
                  · <el-link :href="itemUrl(current.item_id)" target="_blank" type="primary" class="small">商品 {{ current.item_id }}</el-link>
                </template>
                <template v-if="current.bargain_rounds"> · 已议价 {{ current.bargain_rounds }} 轮</template>
                <template v-if="current.in_takeover && current.takeover_until"> · 接管至 {{ fmtTime(current.takeover_until) }}</template>
              </div>
            </div>
          </div>
          <div class="th-right">
            <el-button v-if="current.in_takeover" size="small" @click="applyTakeover(0)">恢复自动回复</el-button>
            <el-popover v-else v-model:visible="takeoverOpen" trigger="click" :width="240">
              <template #reference>
                <el-button size="small" type="warning" plain>人工接管</el-button>
              </template>
              <div class="small">接管期间该会话暂停所有自动回复</div>
              <div class="tk-row">
                <el-input-number v-model="takeoverMinutes" :min="1" :max="1440" size="small" />
                <span class="small">分钟</span>
              </div>
              <el-button size="small" type="primary" class="full" @click="applyTakeover(takeoverMinutes)">确定接管</el-button>
            </el-popover>
            <el-button size="small" :icon="Cpu" @click="openTrial">试运行</el-button>
          </div>
        </header>

        <div ref="threadEl" v-loading="msgLoading" class="thread">
          <div v-if="hasOlder" class="older"><el-button link size="small" @click="loadOlder">加载更早的消息</el-button></div>
          <template v-for="m in messages" :key="m.id">
            <div v-if="m.is_system || m.source === 'system'" class="sys-msg">
              <span>{{ m.notice ? `[${m.notice}] ` : '' }}{{ m.text }}</span>
              <span class="sys-time">{{ fmtTime(m.created_at) }}</span>
            </div>
            <div v-else class="msg-row" :class="m.direction === 'in' ? 'left' : 'right'">
              <div class="msg-meta">
                <el-tag size="small" :type="sourceMap[m.source]?.type || 'info'" effect="plain" disable-transitions>
                  {{ sourceMap[m.source]?.label || m.source }}
                </el-tag>
                <span>{{ fmtTime(m.created_at) }}</span>
              </div>
              <div class="bubble" :class="bubbleClass(m)">{{ m.text }}</div>
            </div>
          </template>
          <el-empty v-if="!msgLoading && !messages.length" description="暂无消息" :image-size="60" />
        </div>

        <div v-if="suggestions.length" class="sugs">
          <div class="sugs-title small">AI 建议回复（待确认）</div>
          <div v-for="s in suggestions" :key="s.id" class="sug">
            <div class="sug-text" title="点击填入输入框编辑" @click="useSuggestion(s)">{{ s.text }}</div>
            <div class="sug-meta">
              <span class="muted small">
                <template v-if="s.intent">意图：{{ s.intent }}</template>
                <template v-if="s.note"> · {{ s.note }}</template>
              </span>
              <span>
                <el-button size="small" type="primary" :loading="sugBusy[s.id]" @click="onSuggestion(s, 'send')">发送</el-button>
                <el-button size="small" :disabled="sugBusy[s.id]" @click="onSuggestion(s, 'discard')">丢弃</el-button>
              </span>
            </div>
          </div>
        </div>

        <footer class="composer">
          <el-input
            v-model="draft"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            maxlength="1000"
            placeholder="输入回复内容，Ctrl / ⌘ + Enter 发送。人工发送后会自动接管该会话。"
            @keydown="onKeydown"
          />
          <el-button type="primary" :icon="Promotion" :loading="sending" :disabled="!draft.trim()" @click="send">发送</el-button>
        </footer>
      </template>
      <el-empty v-else description="选择左侧会话查看消息" class="placeholder" />
    </section>

    <!-- 试运行 -->
    <el-dialog v-model="trial.open" title="试运行：系统会如何回复？" width="600px">
      <div class="muted small mb">模拟买家发来一条消息，查看回复决策（不会真的发送，也不改变会话状态）。</div>
      <el-input v-model="trial.text" type="textarea" :rows="3" maxlength="500" placeholder="买家消息，例如：最低多少钱？能包邮吗？" />
      <div class="trial-btn">
        <el-button type="primary" :loading="trial.loading" :disabled="!trial.text.trim()" @click="runTrial">运行</el-button>
      </div>
      <template v-if="trial.plan">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="决策">
            <el-tag :type="actionLabel[trial.plan.action]?.type || 'info'">{{ actionLabel[trial.plan.action]?.label || trial.plan.action }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="trial.plan.source" label="来源">
            {{ sourceMap[trial.plan.source]?.label || trial.plan.source }}
          </el-descriptions-item>
          <el-descriptions-item v-if="trial.plan.intent" label="意图">{{ trial.plan.intent }}</el-descriptions-item>
          <el-descriptions-item v-if="trial.plan.note" label="说明">{{ trial.plan.note }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="trial.plan.text" class="trial-reply">
          <div class="small muted">将要回复的内容</div>
          <div class="bubble out src-ai">{{ trial.plan.text }}</div>
        </div>
        <el-collapse class="mt">
          <el-collapse-item :title="planExtra ? '更多细节（原始数据）' : '原始数据'" name="raw">
            <JsonBlock :value="trial.plan" />
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.inbox {
  display: flex;
  height: calc(100vh - 56px - 40px);
  min-height: 420px;
  background: #fff;
  border: 1px solid var(--xh-border);
  border-radius: 10px;
  overflow: hidden;
}
.list-pane {
  width: 300px;
  flex-shrink: 0;
  border-right: 1px solid var(--xh-border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.list-head {
  display: flex;
  gap: 8px;
  padding: 10px 10px 6px;
}
.acc-sel {
  flex: 1;
}
.list-search {
  padding: 0 10px 8px;
  border-bottom: 1px solid var(--xh-border);
}
.list-scroll {
  flex: 1;
  min-height: 0;
}
.conv {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
  border-bottom: 1px solid #f2f3f5;
}
.conv:hover {
  background: #f7f8fa;
}
.conv.active {
  background: var(--el-color-primary-light-9);
}
.conv-avatar {
  background: #c6e9d9;
  color: var(--xh-primary);
  font-weight: 600;
}
.conv-main {
  flex: 1;
  min-width: 0;
}
.conv-top,
.conv-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
}
.conv-name {
  font-weight: 600;
}
.conv-time {
  font-size: 11px;
  color: var(--xh-muted);
  flex-shrink: 0;
}
.conv-last {
  font-size: 12px;
  color: #606266;
}
.tk {
  flex-shrink: 0;
}
.conv-acc {
  font-size: 11px;
}
.thread-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.placeholder {
  margin: auto;
}
.thread-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--xh-border);
  flex-wrap: wrap;
}
.th-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.th-info {
  min-width: 0;
}
.th-name {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}
.th-right {
  display: flex;
  gap: 6px;
}
.th-right .el-button + .el-button {
  margin-left: 0;
}
.tk-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0;
}
.full {
  width: 100%;
}
.thread {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  background: #f7f8fa;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.older {
  text-align: center;
}
.sys-msg {
  align-self: center;
  font-size: 12px;
  color: var(--xh-muted);
  background: #eceef1;
  border-radius: 10px;
  padding: 4px 10px;
  max-width: 85%;
  text-align: center;
}
.sys-time {
  margin-left: 6px;
  opacity: 0.7;
}
.msg-row {
  display: flex;
  flex-direction: column;
  max-width: 78%;
}
.msg-row.left {
  align-self: flex-start;
  align-items: flex-start;
}
.msg-row.right {
  align-self: flex-end;
  align-items: flex-end;
}
.msg-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--xh-muted);
  margin-bottom: 3px;
}
.bubble {
  padding: 8px 12px;
  border-radius: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  border: 1px solid transparent;
}
.bubble.in {
  border-top-left-radius: 4px;
}
.bubble.out {
  border-top-right-radius: 4px;
}
/* 按消息来源区分配色 */
.src-buyer {
  background: #fff;
  border-color: var(--xh-border);
}
.src-manual {
  background: #ecf5ff;
  border-color: #c6e2ff;
}
.src-ai {
  background: #e9f5f0;
  border-color: #bce2d2;
}
.src-keyword {
  background: #fdf6ec;
  border-color: #f5dab1;
}
.src-delivery {
  background: #f0f9eb;
  border-color: #c2e7b0;
}
.src-system {
  background: #f4f4f5;
  border-color: #e9e9eb;
}
.sugs {
  border-top: 1px solid var(--xh-border);
  padding: 8px 14px;
  background: #fbfdfc;
  max-height: 34%;
  overflow-y: auto;
}
.sugs-title {
  font-weight: 600;
  color: var(--xh-primary);
  margin-bottom: 6px;
}
.sug {
  border: 1px dashed var(--el-color-primary-light-5);
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 6px;
  background: #fff;
}
.sug-text {
  white-space: pre-wrap;
  cursor: pointer;
}
.sug-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.composer {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 10px 14px;
  border-top: 1px solid var(--xh-border);
}
.mb {
  margin-bottom: 8px;
}
.mt {
  margin-top: 12px;
}
.trial-btn {
  margin: 10px 0;
  text-align: right;
}
.trial-reply {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}
@media (max-width: 768px) {
  .inbox {
    height: calc(100vh - 56px - 24px);
  }
  .list-pane {
    width: 100%;
    border-right: none;
  }
  .msg-row {
    max-width: 90%;
  }
}
.conv-foot {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 0 14px;
}
</style>
