<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { getMarket, listItems, offlineItem, polishItem, syncItems, updateItem, type MarketView, type MyItem } from '@/api/goods'
import MarketPanel from '@/components/MarketPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAccountsStore } from '@/stores/accounts'
import { useMobile } from '@/composables/useMobile'
import { fmtMoney, fmtRelative, fmtTime, goodsStatusMap, itemUrl } from '@/utils/format'

const accounts = useAccountsStore()
const isMobile = useMobile()
const items = ref<MyItem[]>([])
const loading = ref(false)
const syncing = ref(false)
const busy = reactive<Record<string, boolean>>({})
const filter = reactive({ account_id: undefined as number | undefined, status: '', q: '' })

async function load() {
  loading.value = true
  try {
    items.value = await listItems({
      account_id: filter.account_id,
      status: filter.status || undefined,
      q: filter.q.trim() || undefined,
    })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  load()
  await accounts.load().catch(() => undefined)
})

async function sync() {
  if (!filter.account_id) {
    ElMessage.warning('请先选择要同步的账号')
    return
  }
  syncing.value = true
  try {
    const r = await syncItems(filter.account_id)
    const summary = Object.entries(r)
      .map(([k, v]) => `${{ total: '共', created: '新增', updated: '更新', removed: '移除' }[k] || k} ${v}`)
      .join('，')
    ElMessage.success(`同步完成：${summary || '无变化'}`)
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    syncing.value = false
  }
}

async function polish(it: MyItem) {
  busy[`p-${it.id}`] = true
  try {
    await polishItem(it.id)
    ElMessage.success('已擦亮')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`p-${it.id}`] = false
  }
}

async function offline(it: MyItem) {
  await ElMessageBox.confirm(`将在闲鱼上下架「${it.title}」，确定？`, '下架商品', { type: 'warning' })
  busy[`o-${it.id}`] = true
  try {
    await offlineItem(it.id)
    ElMessage.success('已下架')
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    busy[`o-${it.id}`] = false
  }
}

// ---------------------------------------------------------------- 议价策略 & 知识库
const edit = reactive({
  open: false,
  saving: false,
  item: null as MyItem | null,
  floor_price: null as number | null,
  max_rounds: 3,
  step_ratios: [] as number[],
  gifts: '',
  knowledge: '',
  desc: '',
  is_virtual: false,
})

function openEdit(it: MyItem) {
  Object.assign(edit, {
    open: true,
    item: it,
    floor_price: it.floor_price,
    max_rounds: it.max_rounds,
    step_ratios: [...(it.step_ratios?.length ? it.step_ratios : [0.4, 0.3, 0.2, 0.1])],
    gifts: it.gifts,
    knowledge: it.knowledge,
    desc: it.desc,
    is_virtual: it.is_virtual,
  })
}

const ratioSum = computed(() => edit.step_ratios.reduce((a, b) => a + (b || 0), 0))

/** 议价阶梯预览：每轮让出 (售价-底价) × 比例 */
const ladder = computed(() => {
  const price = edit.item?.price
  const floor = edit.floor_price
  if (!price || floor === null || floor === undefined || floor > price) return []
  const gap = price - floor
  let cur = price
  return edit.step_ratios.slice(0, edit.max_rounds).map((r, i) => {
    cur = Math.max(floor, cur - gap * (r || 0))
    return { round: i + 1, price: Math.round(cur * 100) / 100 }
  })
})

async function save() {
  const it = edit.item
  if (!it) return
  if (edit.floor_price !== null && it.price !== null && edit.floor_price > it.price) {
    ElMessage.warning('底价不能高于售价')
    return
  }
  if (ratioSum.value > 1.0001) {
    ElMessage.warning('让价比例合计不能超过 100%')
    return
  }
  edit.saving = true
  try {
    await updateItem(it.id, {
      floor_price: edit.floor_price,
      max_rounds: edit.max_rounds,
      step_ratios: edit.step_ratios.filter((x) => x > 0),
      gifts: edit.gifts,
      knowledge: edit.knowledge,
      desc: edit.desc,
      is_virtual: edit.is_virtual,
    })
    ElMessage.success('已保存')
    edit.open = false
    await load()
  } catch {
    /* 拦截器已提示 */
  } finally {
    edit.saving = false
  }
}

// ---------------------------------------------------------------- 行情
const market = reactive({ open: false, loading: false, item: null as MyItem | null, keyword: '', data: null as MarketView | null })

function openMarket(it: MyItem) {
  Object.assign(market, { open: true, item: it, keyword: it.title.slice(0, 30), data: null })
  queryMarket()
}

async function queryMarket() {
  if (!market.keyword.trim()) return
  market.loading = true
  try {
    market.data = await getMarket(market.keyword.trim(), market.item?.price)
  } catch {
    market.data = null
  } finally {
    market.loading = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>商品中心 · 商品</h2>
        <div class="sub">同步在售商品，为每个商品配置底价、议价阶梯和客服知识库（AI 回复时使用，底价不会透露给买家）</div>
      </div>
    </div>

    <el-card shadow="never" class="filters">
      <div class="toolbar">
        <el-select v-model="filter.account_id" clearable placeholder="全部账号" class="w180" @change="load">
          <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.remark || a.nickname || a.unb" />
        </el-select>
        <el-button type="primary" :icon="Refresh" :loading="syncing" :disabled="!filter.account_id" @click="sync">同步商品</el-button>
        <el-select v-model="filter.status" clearable placeholder="全部状态" class="w120" @change="load">
          <el-option v-for="(v, k) in goodsStatusMap" :key="k" :value="k" :label="v.label" />
        </el-select>
        <el-input v-model="filter.q" placeholder="搜索标题" clearable class="w180" :prefix-icon="Search" @keyup.enter="load" @clear="load" />
      </div>
    </el-card>

    <el-card shadow="never">
      <div class="table-wrap">
        <el-table v-loading="loading" :data="items" empty-text="暂无商品，选择账号后点击「同步商品」">
          <el-table-column label="商品" min-width="280">
            <template #default="{ row }">
              <div class="goods">
                <el-image :src="row.image_url" fit="cover" class="thumb" lazy referrerpolicy="no-referrer" />
                <div class="goods-info">
                  <el-link :href="itemUrl(row.item_id)" target="_blank" class="goods-title">{{ row.title }}</el-link>
                  <div class="muted small">
                    {{ accounts.nameOf(row.account_id) }} · ID {{ row.item_id }}
                    <el-tag v-if="row.is_virtual" size="small" type="primary" effect="plain">虚拟</el-tag>
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="售价" width="90">
            <template #default="{ row }"><span class="price">{{ fmtMoney(row.price) }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><StatusTag :value="row.status" :map="goodsStatusMap" /></template>
          </el-table-column>
          <el-table-column label="议价策略" min-width="150">
            <template #default="{ row }">
              <template v-if="row.floor_price !== null">
                <div class="small">底价 {{ fmtMoney(row.floor_price) }} · 最多 {{ row.max_rounds }} 轮</div>
                <div v-if="row.gifts" class="muted small ellipsis">赠品：{{ row.gifts }}</div>
              </template>
              <span v-else class="muted small">未设置底价（AI 不让价）</span>
            </template>
          </el-table-column>
          <el-table-column label="知识库" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.knowledge" size="small" type="success" effect="plain">{{ row.knowledge.length }} 字</el-tag>
              <span v-else class="muted small">未填写</span>
            </template>
          </el-table-column>
          <el-table-column label="同步 / 擦亮" width="140">
            <template #default="{ row }">
              <div class="small">{{ fmtRelative(row.synced_at) || '-' }}</div>
              <div class="muted small">擦亮 {{ fmtRelative(row.last_polished_at) || '-' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="操作" :width="isMobile ? 110 : 250" :fixed="isMobile ? undefined : 'right'">
            <template #default="{ row }">
              <div class="ops">
                <el-button size="small" type="primary" plain @click="openEdit(row as MyItem)">策略</el-button>
                <el-button size="small" @click="openMarket(row as MyItem)">行情</el-button>
                <el-button size="small" :loading="busy[`p-${row.id}`]" :disabled="row.status !== 'on_sale'" @click="polish(row as MyItem)">擦亮</el-button>
                <el-button size="small" type="danger" plain :loading="busy[`o-${row.id}`]" :disabled="row.status !== 'on_sale'" @click="offline(row as MyItem)">下架</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 策略编辑 -->
    <el-drawer v-model="edit.open" :title="edit.item?.title" size="560px">
      <el-form label-position="top" v-if="edit.item">
        <el-divider content-position="left">议价策略</el-divider>
        <el-form-item label="底价（元）">
          <el-input-number v-model="edit.floor_price" :min="0" :max="edit.item.price || undefined" :precision="2" :value-on-clear="null" placeholder="不设置" />
          <div class="form-tip">当前售价 {{ fmtMoney(edit.item.price) }}。AI 议价绝不低于底价；未设置底价时 AI 不会让价。</div>
        </el-form-item>
        <el-form-item label="最多议价轮数">
          <el-input-number v-model="edit.max_rounds" :min="0" :max="10" />
          <div class="form-tip">超过轮数后 AI 坚持当前价格，0 表示不议价。</div>
        </el-form-item>
        <el-form-item label="每轮让价比例">
          <div class="ratios">
            <div v-for="(_, i) in edit.step_ratios" :key="i" class="ratio">
              <span class="muted small">第 {{ i + 1 }} 轮</span>
              <el-input-number v-model="edit.step_ratios[i]" :min="0" :max="1" :step="0.05" :precision="2" size="small" />
              <el-button :icon="Delete" size="small" circle @click="edit.step_ratios.splice(i, 1)" />
            </div>
            <el-button size="small" :icon="Plus" :disabled="edit.step_ratios.length >= 10" @click="edit.step_ratios.push(0.1)">添加一轮</el-button>
          </div>
          <div class="form-tip">每轮让出（售价 − 底价）的比例，合计 {{ Math.round(ratioSum * 100) }}%（不超过 100%）。前期让得多、后期让得少更像真人。</div>
          <div v-if="ladder.length" class="ladder">
            <span class="small muted">报价预览：</span>
            <el-tag v-for="s in ladder" :key="s.round" size="small" effect="plain">第{{ s.round }}轮 {{ fmtMoney(s.price) }}</el-tag>
          </div>
        </el-form-item>
        <el-form-item label="赠品 / 让步筹码">
          <el-input v-model="edit.gifts" maxlength="128" placeholder="例如：送手机壳、包邮" />
          <div class="form-tip">买家坚持砍价但已到底价时，AI 可以用赠品代替降价。</div>
        </el-form-item>

        <el-divider content-position="left">客服知识</el-divider>
        <el-form-item label="知识库">
          <el-input v-model="edit.knowledge" type="textarea" :rows="8" maxlength="8000" show-word-limit placeholder="FAQ、参数、成色与瑕疵说明、使用教程、售后政策等。AI 回复只依据这里和商品描述，不会编造。" />
        </el-form-item>
        <el-form-item label="商品描述">
          <el-input v-model="edit.desc" type="textarea" :rows="4" placeholder="同步自闲鱼，可补充修改（仅本地，供 AI 参考）" />
        </el-form-item>
        <el-form-item label="虚拟商品">
          <el-switch v-model="edit.is_virtual" />
          <div class="form-tip">虚拟商品（卡密 / 账号 / 资料等）可配合卡券自动发货。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.open = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="save">保存</el-button>
      </template>
    </el-drawer>

    <!-- 行情 -->
    <el-dialog v-model="market.open" title="查看行情" width="600px">
      <div class="mk-search">
        <el-input v-model="market.keyword" placeholder="搜索关键词（品牌 + 型号效果最好）" @keyup.enter="queryMarket" />
        <el-button type="primary" :loading="market.loading" @click="queryMarket">查询</el-button>
      </div>
      <div v-loading="market.loading" class="mk-body">
        <MarketPanel v-if="market.data" :data="market.data" :my-price="market.item?.price" />
        <el-empty v-else-if="!market.loading" description="查询失败或无数据" :image-size="50" />
      </div>
      <div class="form-tip">行情来自实时搜索（会消耗一次搜索频率）。最后同步：{{ fmtTime(market.item?.synced_at) }}</div>
    </el-dialog>
  </div>
</template>

<style scoped>
.filters :deep(.el-card__body) {
  padding: 12px;
}
.w120 {
  width: 120px;
}
.w180 {
  width: 180px;
}
.goods {
  display: flex;
  gap: 10px;
  align-items: center;
}
.thumb {
  width: 54px;
  height: 54px;
  border-radius: 6px;
  flex-shrink: 0;
  background: #f2f3f5;
}
.thumb-err {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 12px;
  color: var(--xh-muted);
}
.goods-info {
  min-width: 0;
}
.goods-title {
  font-weight: 600;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.price {
  color: #f56c6c;
  font-weight: 600;
}
.ops {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ops .el-button + .el-button {
  margin-left: 0;
}
.ratios {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}
.ratio {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ladder {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  margin-top: 6px;
}
.mk-search {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.mk-body {
  min-height: 100px;
}
@media (max-width: 768px) {
  .w120,
  .w180 {
    width: calc(50% - 4px);
  }
}
</style>
