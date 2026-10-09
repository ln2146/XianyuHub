<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import { Close, MagicStick, Plus, Refresh, Star } from '@element-plus/icons-vue'
import {
  aiCopy,
  createDraft,
  deleteDraft,
  listDrafts,
  publishDraft,
  updateDraft,
  uploadImage,
  uploadUrl,
  type CopyOut,
  type DraftIn,
  type DraftOut,
  type ShippingMode,
} from '@/api/goods'
import MarketPanel from '@/components/MarketPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { draftStatusMap, fmtMoney, fmtTime, itemUrl } from '@/utils/format'

const accounts = useAccountsStore()
const isMobile = useMobile()

// ---------------------------------------------------------------- 表单
interface FormState {
  account_id: number | null
  title: string
  desc: string
  image_ids: string[]
  price: number | null
  orig_price: number | null
  quantity: number
  shipping: ShippingMode
  post_fee: number
  self_pickup: boolean
  floor_price: number | null
  knowledge: string
  is_virtual: boolean
  scheduled_at: Date | null
}

const emptyForm = (): FormState => ({
  account_id: accounts.list[0]?.id ?? null,
  title: '',
  desc: '',
  image_ids: [],
  price: null,
  orig_price: null,
  quantity: 1,
  shipping: 'free',
  post_fee: 0,
  self_pickup: false,
  floor_price: null,
  knowledge: '',
  is_virtual: false,
  scheduled_at: null,
})

const form = reactive<FormState>(emptyForm())
const editingId = ref<number | null>(null)
const saving = ref(false)
const uploading = ref(0)

function resetForm() {
  Object.assign(form, emptyForm())
  editingId.value = null
  copy.result = null
  copy.hint = ''
}

// ---------------------------------------------------------------- 图片上传
async function onUpload(opt: UploadRequestOptions) {
  if (form.image_ids.length >= 9) {
    ElMessage.warning('最多 9 张图片')
    return
  }
  uploading.value += 1
  try {
    const r = await uploadImage(opt.file)
    if (form.image_ids.length < 9) form.image_ids.push(r.id)
  } catch {
    /* 拦截器已提示 */
  } finally {
    uploading.value -= 1
  }
}

function beforeUpload(file: File) {
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('只能上传图片')
    return false
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('单张图片不超过 10MB')
    return false
  }
  return true
}

function removeImage(i: number) {
  form.image_ids.splice(i, 1)
}
function makeCover(i: number) {
  const [id] = form.image_ids.splice(i, 1)
  if (id) form.image_ids.unshift(id)
}

// ---------------------------------------------------------------- AI 文案
const copy = reactive({ loading: false, hint: '', result: null as CopyOut | null })

async function runAiCopy() {
  if (!form.image_ids.length) {
    ElMessage.warning('请先上传至少一张图片')
    return
  }
  copy.loading = true
  try {
    const r = await aiCopy(form.image_ids.slice(0, 4), copy.hint.trim())
    copy.result = r
    if (!form.title && r.titles[0]) form.title = r.titles[0].slice(0, 60)
    if (!form.desc) form.desc = r.desc
    if (!form.price && r.market?.suggestion) form.price = r.market.suggestion.market
    ElMessage.success('文案已生成，可点击替换标题 / 描述')
  } catch {
    /* 拦截器已提示 */
  } finally {
    copy.loading = false
  }
}

function pickPrice(p: number) {
  form.price = p
  ElMessage.success(`售价已设为 ${fmtMoney(p)}`)
}

// ---------------------------------------------------------------- 保存草稿
function toBody(): DraftIn | null {
  if (!form.account_id) return ElMessage.warning('请选择发布账号'), null
  if (!form.image_ids.length) return ElMessage.warning('请至少上传一张图片'), null
  if (!form.title.trim()) return ElMessage.warning('请填写标题'), null
  if (!form.desc.trim()) return ElMessage.warning('请填写描述'), null
  if (!form.price || form.price <= 0) return ElMessage.warning('请填写售价'), null
  if (form.floor_price !== null && form.floor_price > form.price) return ElMessage.warning('底价不能高于售价'), null
  return {
    account_id: form.account_id,
    title: form.title.trim(),
    desc: form.desc.trim(),
    image_ids: form.image_ids,
    price: form.price,
    orig_price: form.orig_price,
    quantity: form.quantity,
    shipping: form.shipping,
    post_fee: form.shipping === 'fixed' ? form.post_fee : 0,
    self_pickup: form.self_pickup,
    floor_price: form.floor_price,
    knowledge: form.knowledge,
    is_virtual: form.is_virtual,
    scheduled_at: form.scheduled_at ? form.scheduled_at.toISOString() : null,
  }
}

async function saveDraft() {
  const body = toBody()
  if (!body) return
  saving.value = true
  try {
    if (editingId.value) await updateDraft(editingId.value, body)
    else await createDraft(body)
    ElMessage.success(body.scheduled_at ? '已保存为定时发布' : '草稿已保存')
    resetForm()
    await loadDrafts()
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- 草稿列表
const drafts = ref<DraftOut[]>([])
const draftsLoading = ref(false)
const busy = reactive<Record<string, boolean>>({})

async function loadDrafts() {
  draftsLoading.value = true
  try {
    drafts.value = await listDrafts()
  } finally {
    draftsLoading.value = false
  }
}

function editDraft(d: DraftOut) {
  Object.assign(form, {
    account_id: d.account_id,
    title: d.title,
    desc: d.desc,
    image_ids: [...d.image_ids],
    price: d.price,
    orig_price: d.orig_price,
    quantity: d.quantity,
    shipping: d.shipping,
    post_fee: d.post_fee,
    self_pickup: d.self_pickup,
    floor_price: d.floor_price,
    knowledge: d.knowledge,
    is_virtual: d.is_virtual,
    scheduled_at: d.scheduled_at ? new Date(d.scheduled_at) : null,
  })
  editingId.value = d.id
  copy.result = null
  window.scrollTo({ top: 0, behavior: 'smooth' })
  document.querySelector('.main')?.scrollTo({ top: 0, behavior: 'smooth' })
}

async function publish(d: DraftOut) {
  await ElMessageBox.confirm(
    `确认后将立即以账号「${accounts.nameOf(d.account_id)}」在闲鱼上发布「${d.title}」（售价 ${fmtMoney(d.price)}）。发布操作受频率保护（默认每个账号 5 分钟 1 个），发布后可在闲鱼 App 中修改或下架。`,
    '立即发布到闲鱼',
    { type: 'warning', confirmButtonText: '确认发布' },
  )
  busy[`pub-${d.id}`] = true
  try {
    const r = await publishDraft(d.id)
    ElMessage.success(`发布成功，商品 ID ${r.item_id}`)
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`pub-${d.id}`] = false
    await loadDrafts()
  }
}

async function removeDraft(d: DraftOut) {
  await ElMessageBox.confirm(`删除草稿「${d.title}」？`, '删除草稿', { type: 'warning' })
  await deleteDraft(d.id)
  if (editingId.value === d.id) resetForm()
  ElMessage.success('已删除')
  await loadDrafts()
}

const shippingLabel: Record<string, string> = {
  free: '包邮',
  by_distance: '按距离计费',
  fixed: '一口价运费',
  no_shipping: '无需邮寄',
}

const canEdit = (d: DraftOut) => d.status !== 'published' && d.status !== 'publishing'
const titleLen = computed(() => form.title.length)

onMounted(async () => {
  loadDrafts()
  await accounts.load().catch(() => undefined)
  if (!form.account_id) form.account_id = accounts.list[0]?.id ?? null
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>商品中心 · 发布</h2>
        <div class="sub">上传图片 → AI 写文案并参考行情定价 → 保存草稿 → 人工确认发布</div>
      </div>
    </div>

    <el-row :gutter="12">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <span>{{ editingId ? `编辑草稿 #${editingId}` : '新建商品' }}</span>
              <el-button v-if="editingId" link type="primary" @click="resetForm">取消编辑，新建</el-button>
            </div>
          </template>
          <el-form label-width="90px" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="发布账号" required>
              <el-select v-model="form.account_id" placeholder="选择账号" class="w240">
                <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
              </el-select>
            </el-form-item>

            <el-form-item label="图片" required>
              <div class="images">
                <div v-for="(id, i) in form.image_ids" :key="id" class="img-item">
                  <el-image :src="uploadUrl(id)" fit="cover" class="img" :preview-src-list="form.image_ids.map(uploadUrl)" :initial-index="i" preview-teleported />
                  <span v-if="i === 0" class="cover">首图</span>
                  <div class="img-ops">
                    <el-button v-if="i > 0" :icon="Star" size="small" circle title="设为首图" @click="makeCover(i)" />
                    <el-button :icon="Close" size="small" circle title="移除" @click="removeImage(i)" />
                  </div>
                </div>
                <el-upload
                  v-if="form.image_ids.length < 9"
                  :show-file-list="false"
                  :http-request="onUpload"
                  :before-upload="beforeUpload"
                  accept="image/*"
                  multiple
                >
                  <div v-loading="uploading > 0" class="uploader">
                    <el-icon :size="22"><Plus /></el-icon>
                    <span class="small">{{ form.image_ids.length }}/9</span>
                  </div>
                </el-upload>
              </div>
            </el-form-item>

            <el-form-item label="AI 文案">
              <div class="ai-row">
                <el-input v-model="copy.hint" placeholder="补充说明（可选）：入手时间、成色、配件、出售原因…" />
                <el-button type="primary" plain :icon="MagicStick" :loading="copy.loading" :disabled="!form.image_ids.length" @click="runAiCopy">AI 写文案</el-button>
              </div>
              <div class="form-tip">识别前 4 张图片生成标题、描述，并搜索同款给出建议价。</div>
            </el-form-item>

            <el-form-item v-if="copy.result" label=" ">
              <div class="ai-result">
                <div class="ai-meta">
                  <el-tag size="small" type="success">成色：{{ copy.result.condition }}</el-tag>
                  <el-tag v-for="h in copy.result.highlights" :key="h" size="small" effect="plain">{{ h }}</el-tag>
                </div>
                <div class="small muted">候选标题（点击使用）</div>
                <div v-for="t in copy.result.titles" :key="t" class="ai-title" :class="{ on: form.title === t }" @click="form.title = t.slice(0, 60)">{{ t }}</div>
                <div class="small muted mt-s">描述 <el-button link size="small" type="primary" @click="form.desc = copy.result.desc">使用此描述</el-button></div>
                <div class="ai-desc">{{ copy.result.desc }}</div>
                <el-divider />
                <div class="small muted">行情参考（点击价格填入售价）</div>
                <MarketPanel v-if="copy.result.market" :data="copy.result.market" :my-price="form.price" @pick="pickPrice" />
                <div v-else class="muted small">行情查询失败（可能是账号风控保护中），可稍后在「商品」页查看行情。</div>
              </div>
            </el-form-item>

            <el-form-item label="标题" required>
              <el-input v-model="form.title" maxlength="60" show-word-limit placeholder="品牌型号 + 核心卖点" />
              <div v-if="titleLen > 30" class="form-tip">标题建议 30 字以内，过长在列表中会被截断。</div>
            </el-form-item>
            <el-form-item label="描述" required>
              <el-input v-model="form.desc" type="textarea" :rows="6" maxlength="5000" show-word-limit placeholder="入手渠道 / 时间、成色与瑕疵、配件、出售原因、交易方式。不要留站外联系方式。" />
            </el-form-item>
            <el-form-item label="价格" required>
              <div class="range">
                <el-input-number v-model="form.price" :min="0.01" :precision="2" :controls="false" placeholder="售价" :value-on-clear="null" />
                <span class="muted">原价</span>
                <el-input-number v-model="form.orig_price" :min="0" :precision="2" :controls="false" placeholder="可选" :value-on-clear="null" />
                <span class="muted">数量</span>
                <el-input-number v-model="form.quantity" :min="1" />
              </div>
            </el-form-item>
            <el-form-item label="运费">
              <el-radio-group v-model="form.shipping">
                <el-radio-button v-for="(label, k) in shippingLabel" :key="k" :value="k">{{ label }}</el-radio-button>
              </el-radio-group>
              <div v-if="form.shipping === 'fixed'" class="range mt-s">
                <span class="muted">运费</span>
                <el-input-number v-model="form.post_fee" :min="0" :precision="2" />
                <span class="muted">元</span>
              </div>
              <el-checkbox v-model="form.self_pickup" class="mt-s">支持自提</el-checkbox>
            </el-form-item>
            <el-form-item label="底价">
              <el-input-number v-model="form.floor_price" :min="0" :precision="2" :controls="false" placeholder="不设置" :value-on-clear="null" />
              <div class="form-tip">发布后 AI 议价的最低价，不会展示给买家。</div>
            </el-form-item>
            <el-form-item label="知识库">
              <el-input v-model="form.knowledge" type="textarea" :rows="3" placeholder="可选：FAQ、参数、瑕疵说明等，发布后供 AI 客服使用" />
            </el-form-item>
            <el-form-item label="虚拟商品">
              <el-switch v-model="form.is_virtual" />
            </el-form-item>
            <el-form-item label="定时发布">
              <el-date-picker v-model="form.scheduled_at" type="datetime" placeholder="留空表示保存为草稿，手动发布" :disabled-date="(d: Date) => d.getTime() < Date.now() - 86400000" />
              <div class="form-tip">设置后到点自动发布（仍受频率保护）。</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveDraft">{{ editingId ? '保存修改' : '保存草稿' }}</el-button>
              <el-button @click="resetForm">清空</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="drafts">
          <template #header>
            <div class="card-head">
              <span>草稿与发布记录</span>
              <el-button :icon="Refresh" link :loading="draftsLoading" @click="loadDrafts">刷新</el-button>
            </div>
          </template>
          <el-empty v-if="!draftsLoading && !drafts.length" description="暂无草稿" :image-size="60" />
          <div v-loading="draftsLoading" class="draft-list">
            <div v-for="d in drafts" :key="d.id" class="draft" :class="{ editing: editingId === d.id }">
              <el-image :src="d.image_ids[0] ? uploadUrl(d.image_ids[0]) : ''" fit="cover" class="d-img" />
              <div class="d-main">
                <div class="d-title ellipsis">{{ d.title }}</div>
                <div class="small">
                  <span class="price">{{ fmtMoney(d.price) }}</span>
                  <span class="muted"> · {{ accounts.nameOf(d.account_id) }}</span>
                </div>
                <div class="small d-status">
                  <StatusTag :value="d.status" :map="draftStatusMap" />
                  <span v-if="d.status === 'scheduled'" class="muted">{{ fmtTime(d.scheduled_at) }}</span>
                  <el-link v-if="d.item_id" :href="itemUrl(d.item_id)" target="_blank" type="primary" class="small">查看商品</el-link>
                </div>
                <el-tooltip v-if="d.error" :content="d.error">
                  <div class="small err ellipsis">{{ d.error }}</div>
                </el-tooltip>
                <div class="d-ops">
                  <el-button v-if="canEdit(d)" size="small" type="primary" :loading="busy[`pub-${d.id}`]" @click="publish(d)">发布</el-button>
                  <el-button v-if="canEdit(d)" size="small" @click="editDraft(d)">编辑</el-button>
                  <el-button size="small" type="danger" plain :disabled="d.status === 'publishing'" @click="removeDraft(d)">删除</el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.w240 {
  width: 240px;
  max-width: 100%;
}
.images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.img-item {
  position: relative;
  width: 88px;
  height: 88px;
}
.img {
  width: 88px;
  height: 88px;
  border-radius: 8px;
  border: 1px solid var(--xh-border);
}
.cover {
  position: absolute;
  left: 0;
  bottom: 0;
  background: rgba(30, 158, 106, 0.85);
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 0 6px 0 8px;
}
.img-ops {
  position: absolute;
  right: -6px;
  top: -6px;
  display: flex;
  gap: 2px;
}
.img-ops .el-button + .el-button {
  margin-left: 0;
}
.uploader {
  width: 88px;
  height: 88px;
  border: 1px dashed #c0c4cc;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--xh-muted);
  cursor: pointer;
}
.uploader:hover {
  border-color: var(--xh-primary);
  color: var(--xh-primary);
}
.ai-row {
  display: flex;
  gap: 8px;
  width: 100%;
}
.ai-result {
  width: 100%;
  background: #fafbfc;
  border: 1px solid var(--xh-border);
  border-radius: 8px;
  padding: 12px;
}
.ai-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}
.ai-title {
  padding: 6px 10px;
  margin-top: 4px;
  border-radius: 6px;
  background: #fff;
  border: 1px solid var(--xh-border);
  cursor: pointer;
  line-height: 1.5;
}
.ai-title:hover,
.ai-title.on {
  border-color: var(--xh-primary);
  background: var(--el-color-primary-light-9);
}
.ai-desc {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.6;
  max-height: 160px;
  overflow: auto;
}
.mt-s {
  margin-top: 6px;
}
.range {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.drafts {
  position: sticky;
  top: 0;
}
.draft-list {
  min-height: 60px;
}
.draft {
  display: flex;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--xh-border);
}
.draft.editing {
  background: var(--el-color-primary-light-9);
}
.d-img {
  width: 64px;
  height: 64px;
  border-radius: 6px;
  flex-shrink: 0;
  background: #f2f3f5;
}
.d-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.d-title {
  font-weight: 600;
}
.d-status {
  display: flex;
  align-items: center;
  gap: 6px;
}
.d-ops {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.d-ops .el-button + .el-button {
  margin-left: 0;
}
.price {
  color: #f56c6c;
  font-weight: 600;
}
.err {
  color: var(--el-color-danger);
}
@media (max-width: 768px) {
  .ai-row {
    flex-direction: column;
  }
}
</style>
