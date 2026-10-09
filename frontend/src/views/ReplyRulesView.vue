<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { createRule, deleteRule, listRules, updateRule, type RuleIn, type RuleOut } from '@/api/message'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'

const accounts = useAccountsStore()
const isMobile = useMobile()
const rules = ref<RuleOut[]>([])
const loading = ref(false)

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
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>消息中心 · 回复规则</h2>
        <div class="sub">买家消息命中关键词时自动回复，优先级高于 AI。需在账号设置中开启「自动回复」与「关键词回复」。</div>
      </div>
      <div class="toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建规则</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="rules" empty-text="还没有规则。常见示例：关键词「在吗」「还在吗」→ 回复「在的，宝贝有什么想了解的～」">
          <el-table-column label="名称" prop="name" min-width="110">
            <template #default="{ row }">{{ row.name || '-' }}</template>
          </el-table-column>
          <el-table-column label="关键词" min-width="180">
            <template #default="{ row }">
              <div class="kw">
                <el-tag v-for="k in row.keywords" :key="k" size="small" effect="plain">{{ k }}</el-tag>
              </div>
              <span class="muted small">{{ matchLabel[row.match] }}</span>
            </template>
          </el-table-column>
          <el-table-column label="回复内容" prop="reply" min-width="220" show-overflow-tooltip />
          <el-table-column label="生效范围" min-width="140">
            <template #default="{ row }">
              <div class="small">{{ row.account_id ? accounts.nameOf(row.account_id) : '全部账号' }}</div>
              <div class="small muted">{{ row.item_id ? `商品 ${row.item_id}` : '全部商品' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="优先级" prop="priority" width="80" sortable />
          <el-table-column label="仅回复一次" width="100">
            <template #default="{ row }">{{ row.reply_once ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="命中" prop="hits" width="70" sortable />
          <el-table-column label="启用" width="70">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" size="small" @change="(v: string | number | boolean) => toggle(row as RuleOut, !!v)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="openEdit(row as RuleOut)">编辑</el-button>
              <el-button size="small" link type="danger" @click="remove(row as RuleOut)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-dialog v-model="edit.open" :title="edit.id ? '编辑规则' : '新建规则'" width="600px">
      <el-form label-width="100px" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="名称">
          <el-input v-model="edit.form.name" maxlength="64" placeholder="便于识别，可留空" />
        </el-form-item>
        <el-form-item label="关键词" required>
          <el-input-tag v-model="edit.form.keywords" placeholder="输入后回车，命中任一即触发" save-on-blur />
        </el-form-item>
        <el-form-item label="匹配方式">
          <el-radio-group v-model="edit.form.match">
            <el-radio-button value="contains">包含</el-radio-button>
            <el-radio-button value="exact">完全匹配</el-radio-button>
            <el-radio-button value="regex">正则</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="回复内容" required>
          <el-input v-model="edit.form.reply" type="textarea" :rows="4" maxlength="1000" show-word-limit />
          <div class="form-tip">不要包含微信号、QQ 等站外联系方式，容易触发平台风控。</div>
        </el-form-item>
        <el-form-item label="生效账号">
          <el-select v-model="edit.form.account_id" clearable placeholder="全部账号" class="w240">
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
          </el-select>
        </el-form-item>
        <el-form-item label="指定商品 ID">
          <el-input v-model="edit.form.item_id" placeholder="留空对全部商品生效" clearable class="w240" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="edit.form.priority" :min="-100" :max="100" />
          <div class="form-tip">多条规则同时命中时，优先级高的生效。</div>
        </el-form-item>
        <el-form-item label="选项">
          <el-checkbox v-model="edit.form.reply_once">每个会话只回复一次</el-checkbox>
          <el-checkbox v-model="edit.form.enabled">启用</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kw {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 2px;
}
.w240 {
  width: 240px;
  max-width: 100%;
}
</style>
