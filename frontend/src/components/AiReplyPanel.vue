<script setup lang="ts">
// AI 回复设置：给 AI 的说明 + 资料文件 + 试运行（关键词规则没命中时由 AI 回复）
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import { Delete, Document, MagicStick, Upload } from '@element-plus/icons-vue'
import { updateAccount, type Account } from '@/api/account'
import { listItems, type MyItem } from '@/api/goods'
import {
  aiTrial,
  deleteKnowledgeDoc,
  listKnowledgeDocs,
  updateKnowledgeDoc,
  uploadKnowledgeDoc,
  type KnowledgeDoc,
  type ReplyPlan,
} from '@/api/message'
import { useAccountsStore } from '@/stores/accounts'
import { intentText } from '@/utils/format'

const accounts = useAccountsStore()
const accountId = ref<number | null>(null)
const account = computed<Account | undefined>(() => accounts.list.find((a) => a.id === accountId.value))

watch(
  () => accounts.list.length,
  () => {
    if (accountId.value === null && accounts.list.length) accountId.value = accounts.list[0].id
  },
  { immediate: true },
)

// ---------------------------------------------------------------- 给 AI 的说明
const MAX_INSTRUCTIONS = 2000
const instructions = ref('')
const savingInstr = ref(false)
watch(
  account,
  (a) => {
    instructions.value = a?.settings.ai_instructions || ''
  },
  { immediate: true },
)
const instrDirty = computed(() => instructions.value !== (account.value?.settings.ai_instructions || ''))
const INSTR_PLACEHOLDER = [
  '用自己的话告诉 AI 你的店铺和规矩，例如：',
  '· 我是学生党出闲置，东西都是自用，周末不发货',
  '· 说话亲切一点，可以叫“宝”，不要太像客服',
  '· 统一发中通，偏远地区不包邮',
  '· 电子资料拍下自动发，发出后不退',
].join('\n')

async function saveInstructions() {
  if (!account.value) return
  savingInstr.value = true
  try {
    await updateAccount(account.value.id, { settings: { ai_instructions: instructions.value.trim() } })
    await accounts.load(true)
    ElMessage.success('已保存，AI 下次回复就会按这些说明来')
  } finally {
    savingInstr.value = false
  }
}

// ---------------------------------------------------------------- 资料文件
const docs = ref<KnowledgeDoc[]>([])
const docsLoading = ref(false)
const uploadScope = ref<'all' | 'account'>('all')
const ACCEPT = '.txt,.md,.csv,.pdf,.docx'

async function loadDocs() {
  docsLoading.value = true
  try {
    docs.value = await listKnowledgeDocs()
  } finally {
    docsLoading.value = false
  }
}
// 当前账号能用到的资料：通用的 + 只给这个账号的
const visibleDocs = computed(() => docs.value.filter((d) => d.account_id === null || d.account_id === accountId.value))

async function upload(opts: UploadRequestOptions) {
  const d = await uploadKnowledgeDoc(opts.file, uploadScope.value === 'account' ? accountId.value : null)
  docs.value.unshift(d)
  ElMessage.success(`已读取「${d.name}」，共 ${d.chars} 字`)
}

async function toggleDoc(d: KnowledgeDoc, enabled: boolean) {
  const updated = await updateKnowledgeDoc(d.id, { enabled })
  Object.assign(d, updated)
}

async function removeDoc(d: KnowledgeDoc) {
  await ElMessageBox.confirm(`删除资料「${d.name}」？AI 之后不会再参考它。`, '删除资料', { type: 'warning' })
  await deleteKnowledgeDoc(d.id)
  docs.value = docs.value.filter((x) => x.id !== d.id)
}

// ---------------------------------------------------------------- 试运行
const items = ref<MyItem[]>([])
const trial = reactive({ text: '', itemId: '' as string, loading: false, plan: null as (ReplyPlan & { used_docs?: boolean }) | null })
watch(accountId, async (id) => {
  trial.itemId = ''
  trial.plan = null
  items.value = id ? await listItems({ account_id: id }).catch(() => []) : []
})

const trialChips = ['还在吗', '能便宜点吗', '什么时候发货', '包邮吗', '怎么用']
async function runTrial() {
  if (!accountId.value || !trial.text.trim()) return
  trial.loading = true
  trial.plan = null
  try {
    trial.plan = await aiTrial(accountId.value, trial.text.trim(), trial.itemId || null)
  } finally {
    trial.loading = false
  }
}
const trialSource = computed(() => {
  const p = trial.plan
  if (!p) return ''
  if (p.source === 'auto_keyword') return '命中关键词规则'
  if (p.source === 'auto_ai') return 'AI 回复'
  return ''
})
const trialHint = computed(() => {
  const p = trial.plan
  if (!p) return ''
  if (p.action === 'off') return 'AI 回复还没开启：开启后会这样回。'
  if (p.action === 'suggest') return '当前是「建议」模式：会在收件箱里给你这条建议，由你确认后发送。'
  if (p.action === 'handoff') return '会转人工并通知你。'
  if (p.action === 'none') return p.note || '不会回复。'
  return ''
})

onMounted(loadDocs)
</script>

<template>
  <el-card shadow="never" class="ai-panel">
    <div class="head">
      <div class="title">
        <el-icon class="title-icon"><MagicStick /></el-icon>
        <span>AI 回复设置</span>
        <span class="muted small">关键词规则没命中时，由 AI 结合商品信息、知识库和下面的说明与资料来回复</span>
      </div>
      <el-select v-if="accounts.list.length > 1" v-model="accountId" size="small" class="acc-select">
        <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
      </el-select>
    </div>

    <div v-if="!account" class="muted small">请先在「账号配置」中添加闲鱼账号。</div>

    <div v-else class="grid">
      <!-- 给 AI 的说明 -->
      <section class="block">
        <div class="block-title">给 AI 的说明</div>
        <el-input
          v-model="instructions"
          type="textarea"
          :rows="7"
          :maxlength="MAX_INSTRUCTIONS"
          show-word-limit
          :placeholder="INSTR_PLACEHOLDER"
        />
        <div class="row">
          <span class="muted smaller">底价、站外联系方式、“保证正品”类承诺等安全规则始终优先，说明里写了也不会突破。</span>
          <el-button type="primary" size="small" :loading="savingInstr" :disabled="!instrDirty" @click="saveInstructions">保存说明</el-button>
        </div>
      </section>

      <!-- 资料文件 -->
      <section class="block">
        <div class="block-title">
          资料文件
          <span class="muted smaller">说明书、FAQ、价目表等；AI 只取与买家问题相关的段落</span>
        </div>
        <div class="row">
          <el-radio-group v-model="uploadScope" size="small">
            <el-radio-button value="all">所有账号通用</el-radio-button>
            <el-radio-button value="account">只给当前账号</el-radio-button>
          </el-radio-group>
          <el-upload :show-file-list="false" :accept="ACCEPT" :http-request="upload" multiple>
            <el-button size="small" :icon="Upload">上传资料</el-button>
          </el-upload>
        </div>
        <div class="muted smaller">支持 txt / md / csv / pdf / docx，单个不超过 5MB；扫描版 PDF 需要先转成文字。</div>
        <div v-loading="docsLoading" class="docs">
          <div v-if="!visibleDocs.length" class="muted small empty">还没有资料</div>
          <div v-for="d in visibleDocs" :key="d.id" class="doc" :class="{ off: !d.enabled }">
            <el-icon class="doc-icon"><Document /></el-icon>
            <div class="doc-text">
              <div class="doc-name ellipsis" :title="d.preview">{{ d.name }}</div>
              <div class="muted smaller">{{ d.chars.toLocaleString() }} 字 · {{ d.account_id === null ? '所有账号通用' : '仅当前账号' }}</div>
            </div>
            <el-switch :model-value="d.enabled" size="small" @change="(v: string | number | boolean) => toggleDoc(d, !!v)" />
            <el-button link type="danger" :icon="Delete" aria-label="删除资料" @click="removeDoc(d)" />
          </div>
        </div>
      </section>

      <!-- 试运行 -->
      <section class="block trial">
        <div class="block-title">试运行 <span class="muted smaller">不会真的发出去，AI 未开启时也能先看效果</span></div>
        <div class="row">
          <el-select v-model="trial.itemId" clearable filterable size="small" placeholder="咨询的商品（可选）" class="item-select">
            <el-option v-for="it in items" :key="it.item_id" :value="it.item_id" :label="it.title" />
          </el-select>
        </div>
        <div class="row">
          <el-input v-model="trial.text" size="small" maxlength="500" placeholder="输入一句买家消息，例如：能便宜点吗" @keyup.enter="runTrial" />
          <el-button type="primary" size="small" :loading="trial.loading" :disabled="!trial.text.trim()" @click="runTrial">试一下</el-button>
        </div>
        <div class="chips">
          <el-tag v-for="c in trialChips" :key="c" size="small" effect="plain" class="chip" @click="trial.text = c">{{ c }}</el-tag>
        </div>
        <div v-if="trial.plan" class="result">
          <div class="result-meta">
            <el-tag v-if="trialSource" size="small" :type="trial.plan.source === 'auto_ai' ? 'success' : 'info'">{{ trialSource }}</el-tag>
            <el-tag v-if="trial.plan.intent" size="small" effect="plain">{{ intentText(trial.plan.intent) }}</el-tag>
            <el-tag v-if="trial.plan.used_docs" size="small" effect="plain" type="warning">参考了资料</el-tag>
          </div>
          <div v-if="trial.plan.text" class="bubble">{{ trial.plan.text }}</div>
          <div v-if="trialHint" class="muted smaller">{{ trialHint }}</div>
        </div>
      </section>
    </div>
  </el-card>
</template>

<style scoped>
.ai-panel {
  border-radius: var(--xh-radius-md);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xh-space-2);
  margin-bottom: var(--xh-space-3);
}
.title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
  font-weight: 600;
  color: var(--xh-text);
}
.title .muted {
  font-weight: 400;
}
.title-icon {
  color: var(--xh-primary);
}
.acc-select {
  width: 180px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--xh-space-4);
}
.block {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-2);
  min-width: 0;
}
.block-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
}
.block-title .muted {
  font-weight: 400;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--xh-space-2);
}
.docs {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-1);
  min-height: 60px;
  max-height: 220px;
  overflow-y: auto;
}
.empty {
  padding: var(--xh-space-3) 0;
  text-align: center;
}
.doc {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  padding: var(--xh-space-2);
  border-radius: var(--xh-radius-sm);
  background: var(--xh-fill);
}
.doc.off {
  opacity: 0.55;
}
.doc-icon {
  color: var(--xh-muted);
}
.doc-text {
  flex: 1;
  min-width: 0;
}
.doc-name {
  font-size: var(--xh-fs-sm);
  color: var(--xh-text);
}
.item-select {
  width: 100%;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xh-space-1);
}
.chip {
  cursor: pointer;
}
.result {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-2);
  padding: var(--xh-space-3);
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill);
}
.result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--xh-space-1);
}
.bubble {
  align-self: flex-start;
  max-width: 100%;
  padding: var(--xh-space-2) var(--xh-space-3);
  border-radius: var(--xh-radius-md);
  background: var(--xh-card);
  color: var(--xh-text);
  font-size: var(--xh-fs-sm);
  line-height: 1.6;
}
.smaller {
  font-size: var(--xh-fs-xs);
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
