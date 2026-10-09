<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, Plus, Refresh, Setting } from '@element-plus/icons-vue'
import { createRule, deleteRule, listRules, updateRule, type RuleIn, type RuleOut } from '@/api/message'
import { updateAccount, type Account } from '@/api/account'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import StatusTag from '@/components/StatusTag.vue'
import { accountStatusMap } from '@/utils/format'

const router = useRouter()
const accounts = useAccountsStore()
const isMobile = useMobile()
const rules = ref<RuleOut[]>([])
const loading = ref(false)
const busyAccount = reactive<Record<string, boolean>>({})

const matchLabel: Record<string, string> = { contains: '包含', exact: '完全匹配', regex: '正则' }

async function load() {
  loading.value = true
  try {
    rules.value = await listRules()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  accounts.load().catch(() => undefined)
})

const empty = (): RuleIn => ({
  name: '',
  account_id: null,
  item_id: null,
  keywords: [],
  match: 'contains',
  reply: '',
  priority: 0,
  reply_once: false,
  enabled: true,
})

const edit = reactive({ open: false, saving: false, id: null as number | null, form: empty() })

function openCreate() {
  Object.assign(edit, { open: true, id: null, form: empty() })
}

function openEdit(r: RuleOut) {
  const { id: _id, hits: _hits, ...rest } = r
  Object.assign(edit, { open: true, id: r.id, form: { ...rest, keywords: [...r.keywords] } })
}

function toIn(r: RuleOut): RuleIn {
  const { id: _id, hits: _hits, ...rest } = r
  return rest
}

async function save() {
  const f = edit.form
  if (!f.keywords.length) return ElMessage.warning('至少需要一个关键词')
  if (!f.reply.trim()) return ElMessage.warning('请填写回复内容')
  if (f.match === 'regex') {
    for (const k of f.keywords) {
      try {
        new RegExp(k)
      } catch {
        return ElMessage.warning(`正则表达式无效：${k}`)
      }
    }
  }
  edit.saving = true
  try {
    const body: RuleIn = { ...f, item_id: f.item_id?.trim() || null }
    if (edit.id) await updateRule(edit.id, body)
    else await createRule(body)
    ElMessage.success('已保存')
    edit.open = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.saving = false
  }
}

async function toggle(r: RuleOut, enabled: boolean) {
  try {
    await updateRule(r.id, { ...toIn(r), enabled })
    r.enabled = enabled
    ElMessage.success(enabled ? '已启用规则' : '已停用规则')
  } catch {
    /* 拦截器已提示 */
  }
}

async function remove(r: RuleOut) {
  await ElMessageBox.confirm(`删除规则「${r.name || r.keywords.join('、')}」？`, '删除规则', { type: 'warning' })
  await deleteRule(r.id)
  ElMessage.success('已删除')
  await load()
}

// ---------------------------------------------------------------- 就地账号自动回复开关
async function toggleAccountAutoReply(a: Account, val: boolean) {
  busyAccount[`ar-${a.id}`] = true
  try {
    await updateAccount(a.id, { settings: { auto_reply: val } })
    a.settings.auto_reply = val
    ElMessage.success(`账号「${a.remark || a.nickname}」已${val ? '开启' : '关闭'}自动回复`)
  } catch {
    /* 拦截器已处理 */
  } finally {
    busyAccount[`ar-${a.id}`] = false
  }
}

async function toggleAccountKeywordReply(a: Account, val: boolean) {
  busyAccount[`kw-${a.id}`] = true
  try {
    await updateAccount(a.id, { settings: { keyword_reply: val } })
    a.settings.keyword_reply = val
    ElMessage.success(`账号「${a.remark || a.nickname}」已${val ? '开启' : '关闭'}关键词回复`)
  } catch {
    /* 拦截器已处理 */
  } finally {
    busyAccount[`kw-${a.id}`] = false
  }
}

// ---------------------------------------------------------------- 常用模版
const presetTemplates = [
  {
    name: '常在线问候',
    keywords: ['在吗', '还在吗', '在不在', '有人吗'],
    reply: '在的，宝贝！商品成色完好，随时可以拍下，当天为您安排发出～',
  },
  {
    name: '快递与发货时效',
    keywords: ['发什么快递', '什么时候发货', '今天能发吗', '发货时效'],
    reply: '一般下单后当天或次日上午发出，支持顺丰/中通，需要加急可以随时备注哦～',
  },
  {
    name: '正品与验货保障',
    keywords: ['是正品吗', '正品不', '保真吗', '支持验货吗'],
    reply: '保证正品保真，实物拍摄，支持官方或第三方验货，请放心下单～',
  },
]

function applyPreset(tpl: (typeof presetTemplates)[0]) {
  Object.assign(edit, {
    open: true,
    id: null,
    form: {
      ...empty(),
      name: tpl.name,
      keywords: [...tpl.keywords],
      reply: tpl.reply,
    },
  })
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>消息中心 · 回复规则</h2>
        <div class="sub">买家消息命中关键词时自动回复，优先级高于 AI 大模型。请确保账号开启了「自动回复」与「关键词回复」。</div>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" round @click="load">刷新列表</el-button>
        <el-button type="primary" :icon="Plus" round @click="openCreate">新建规则</el-button>
      </div>
    </div>

    <!-- 账号自动回复状态就地控制卡片 -->
    <el-card shadow="never" class="acc-status-card">
      <div class="acc-card-head">
        <div class="acc-card-title">
          <el-icon class="title-icon"><Setting /></el-icon>
          <span>闲鱼账号自动回复状态（就地控制，无需跳转）</span>
        </div>
        <el-link type="primary" class="smaller" @click="router.push('/accounts')">前往账号管理中心 &gt;</el-link>
      </div>

      <div v-if="!accounts.list.length" class="empty-acc-tip muted small">
        尚未添加闲鱼账号，请先在「账号配置」中接入账号。
      </div>

      <div v-else class="acc-grid">
        <div v-for="a in accounts.list" :key="a.id" class="acc-item-card">
          <div class="acc-item-left">
            <div class="acc-avatar">{{ (a.remark || a.nickname || '🐟')[0] }}</div>
            <div class="acc-text">
              <div class="acc-name">{{ a.remark || a.nickname || a.unb }}</div>
              <div class="acc-status-row">
                <StatusTag :value="a.status" :map="accountStatusMap" />
                <span v-if="!a.settings?.auto_reply" class="warn-badge">⚠️ 自动回复已关</span>
                <span v-else-if="!a.settings?.keyword_reply" class="warn-badge">⚠️ 关键词回复已关</span>
              </div>
            </div>
          </div>

          <div class="acc-item-switches">
            <div class="switch-col">
              <span class="sw-label">总开关</span>
              <el-switch
                :model-value="a.settings?.auto_reply ?? false"
                :loading="busyAccount[`ar-${a.id}`]"
                inline-prompt
                active-text="开"
                inactive-text="关"
                size="small"
                @change="(v: string | number | boolean) => toggleAccountAutoReply(a, !!v)"
              />
            </div>
            <div class="switch-col">
              <span class="sw-label">关键词</span>
              <el-switch
                :model-value="a.settings?.keyword_reply ?? false"
                :loading="busyAccount[`kw-${a.id}`]"
                :disabled="!a.settings?.auto_reply"
                inline-prompt
                active-text="开"
                inactive-text="关"
                size="small"
                @change="(v: string | number | boolean) => toggleAccountKeywordReply(a, !!v)"
              />
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 常用规则模版推荐条 -->
    <div class="preset-bar">
      <span class="preset-label">
        <el-icon><MagicStick /></el-icon>
        <span>快捷添加常用模版：</span>
      </span>
      <div class="preset-chips">
        <el-tag
          v-for="tpl in presetTemplates"
          :key="tpl.name"
          class="preset-tag"
          effect="plain"
          type="primary"
          @click="applyPreset(tpl)"
        >
          + {{ tpl.name }}（{{ tpl.keywords.slice(0, 2).join('、') }}）
        </el-tag>
      </div>
    </div>

    <!-- 规则表格 -->
    <el-card shadow="never" class="table-card">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="rules" empty-text="还没有规则。可点击上方快捷模版或「新建规则」添加！">
          <el-table-column label="规则名称" prop="name" min-width="120">
            <template #default="{ row }">
              <span class="font-semibold">{{ row.name || '未命名规则' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="触发关键词" min-width="200">
            <template #default="{ row }">
              <div class="kw-wrap">
                <el-tag v-for="k in row.keywords" :key="k" size="small" class="kw-tag" effect="light">{{ k }}</el-tag>
              </div>
              <div class="muted smaller mt-xs">
                <span>方式: {{ matchLabel[row.match] || row.match }}</span>
                <span class="dot-sep">·</span>
                <span v-if="row.reply_once">每买家单次</span>
                <span v-else>每次触发</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="自动回复内容" prop="reply" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="reply-text">{{ row.reply }}</div>
            </template>
          </el-table-column>
          <el-table-column label="生效范围" min-width="140">
            <template #default="{ row }">
              <div class="small font-medium">{{ row.account_id ? accounts.nameOf(row.account_id) : '全部闲鱼账号' }}</div>
              <div class="smaller muted">{{ row.item_id ? `商品: ${row.item_id}` : '全部商品' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="命中次数" prop="hits" width="90" sortable align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.hits > 0 ? 'success' : 'info'" effect="plain">
                {{ row.hits || 0 }} 次
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="启用" width="80" align="center">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" size="small" @change="(v: string | number | boolean) => toggle(row as RuleOut, !!v)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="ops">
                <el-button size="small" type="primary" plain @click="openEdit(row as RuleOut)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="remove(row as RuleOut)">删除</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 编辑/新建弹窗 -->
    <el-dialog v-model="edit.open" :title="edit.id ? '编辑回复规则' : '新建回复规则'" width="580px" destroy-on-close>
      <el-form label-width="95px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="规则名称">
          <el-input v-model="edit.form.name" maxlength="64" placeholder="例如：常在线问候 / 快递时效说明" />
        </el-form-item>
        <el-form-item label="关键词" required>
          <el-input-tag v-model="edit.form.keywords" placeholder="输入关键词后回车，买家消息包含任一即触发" save-on-blur />
        </el-form-item>
        <el-form-item label="匹配方式">
          <el-radio-group v-model="edit.form.match">
            <el-radio-button value="contains">包含关键词</el-radio-button>
            <el-radio-button value="exact">完全匹配</el-radio-button>
            <el-radio-button value="regex">正则表达式</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="回复内容" required>
          <el-input v-model="edit.form.reply" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="买家触发该关键词后系统自动回复的内容" />
          <div class="form-tip">严禁包含微信号、手机号、外链等站外引流词，容易触发闲鱼平台违规扣分。</div>
        </el-form-item>
        <el-form-item label="生效账号">
          <el-select v-model="edit.form.account_id" clearable placeholder="全部闲鱼账号通用" class="w-full">
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
          </el-select>
        </el-form-item>
        <el-form-item label="指定商品">
          <el-input v-model="edit.form.item_id" placeholder="填写闲鱼商品 ID，留空对全部商品生效" clearable />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="edit.form.priority" :min="-100" :max="100" />
          <div class="form-tip">多条规则同时命中时，优先级数值越大越先执行。</div>
        </el-form-item>
        <el-form-item label="执行选项">
          <el-checkbox v-model="edit.form.reply_once">每个买家会话仅回复一次（避免刷屏）</el-checkbox>
          <el-checkbox v-model="edit.form.enabled">立即启用</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">保存规则</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.acc-status-card {
  margin-bottom: 12px;
  border-radius: 10px;
  border-color: var(--xh-border);
}
.acc-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.acc-card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}
.title-icon {
  color: #3b82f6;
}
.acc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
}
.acc-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.acc-item-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.acc-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #eff6ff;
  color: #3b82f6;
  border: 1px solid #bfdbfe;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}
.acc-text {
  min-width: 0;
}
.acc-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.acc-status-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.warn-badge {
  font-size: 10px;
  color: #d97706;
  background: #fef3c7;
  padding: 1px 4px;
  border-radius: 4px;
}
.acc-item-switches {
  display: flex;
  gap: 12px;
  align-items: center;
}
.switch-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.sw-label {
  font-size: 10px;
  color: var(--xh-muted);
}
.preset-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
  padding: 6px 12px;
  background: #fff;
  border: 1px dashed var(--xh-border);
  border-radius: 8px;
}
.preset-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}
.preset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.preset-tag {
  cursor: pointer;
  transition: all 0.2s ease;
}
.preset-tag:hover {
  transform: translateY(-1px);
}
.table-card {
  border-radius: 10px;
  border-color: var(--xh-border);
}
.kw-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.kw-tag {
  font-weight: 500;
}
.dot-sep {
  margin: 0 4px;
  color: #94a3b8;
}
.reply-text {
  color: #334155;
  font-size: 13px;
  line-height: 1.4;
}
.ops {
  display: flex;
  gap: 6px;
}
.w-full {
  width: 100%;
}
.font-semibold {
  font-weight: 600;
}
.font-medium {
  font-weight: 500;
}
.smaller {
  font-size: 11px;
}
.mt-xs {
  margin-top: 3px;
}
</style>
