<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowDown,
  Bell,
  Check,
  Close,
  Grid,
  List,
  Picture,
  Refresh,
  Search,
  TopRight,
  Upload,
  User,
} from '@element-plus/icons-vue'
import {
  createTask,
  emptyTask,
  getItemDetail,
  liveSearch,
  QUICK_FILTERS,
  type ItemDetail,
  type LiveSearchQuery,
  type SearchItem,
} from '@/api/buyer'
import { useAccountsStore } from '@/stores/accounts'
import { useKeepScroll } from '@/composables/useKeepScroll'
import ItemAnalysisPanel from '@/components/ItemAnalysisPanel.vue'
import RadarNav from '@/components/RadarNav.vue'
import { isMunicipality, PROVINCES } from '@/utils/regions'
import { fmtMoney, fmtRelative } from '@/utils/format'

defineOptions({ name: 'RadarSearchView' })
useKeepScroll()

const route = useRoute()
const router = useRouter()
const accounts = useAccountsStore()

// 视图模式：卡片网格 vs 紧凑列表
const viewMode = ref<'grid' | 'list'>('grid')

// 搜索条件
const searchForm = reactive({
  keyword: '',
  page: 1,
  sort: 'default' as LiveSearchQuery['sort'],
  min_price: null as number | null,
  max_price: null as number | null,
  province: null as string | null,
  city: null as string | null,
  publish_days: 0,
  personal_only: false,
  free_shipping: false,
  account_id: 0,
})

// 快捷热门词
const hotKeywords = ['MacBook M1', 'iPhone 15', 'Switch OLED', 'PS5', '显卡 RTX', 'iPad Air', 'AirPods Pro', '机械键盘']

// 快捷筛选：与闲鱼网页版同一组勾选项，全部作为接口参数提交。
// 个人闲置 / 包邮 用独立字段保存，转自动搜货时一并带上
const quickExtra = ref<string[]>([])

function isQuickOn(key: string) {
  if (key === 'filterPersonal') return searchForm.personal_only
  if (key === 'filterFreePostage') return searchForm.free_shipping
  return quickExtra.value.includes(key)
}

function toggleQuick(key: string) {
  if (key === 'filterPersonal') searchForm.personal_only = !searchForm.personal_only
  else if (key === 'filterFreePostage') searchForm.free_shipping = !searchForm.free_shipping
  else if (quickExtra.value.includes(key)) quickExtra.value = quickExtra.value.filter((k) => k !== key)
  else quickExtra.value = [...quickExtra.value, key]
  debouncedFilterSearch()
}

function setSort(s: LiveSearchQuery['sort']) {
  searchForm.sort = s
  debouncedFilterSearch()
}

// 新发布 ∨：点标题按最新发布排序，下拉选发布时间范围
const publishDayOptions = [
  { label: '不限时间', value: 0 },
  { label: '1 天内', value: 1 },
  { label: '3 天内', value: 3 },
  { label: '7 天内', value: 7 },
  { label: '14 天内', value: 14 },
]
const publishLabel = computed(() => (searchForm.publish_days ? `${searchForm.publish_days}天内` : '新发布'))

function setPublishDays(days: number) {
  searchForm.publish_days = days
  searchForm.sort = 'newest'
  debouncedFilterSearch()
}

const priceSortLabel = computed(() =>
  searchForm.sort === 'price_asc' ? '价格从低到高' : searchForm.sort === 'price_desc' ? '价格从高到低' : '价格',
)

// 区域：左栏省份，右栏城市（直辖市点一下即选中）
const region = reactive({ open: false, province: null as string | null })
const regionProvince = computed(() => PROVINCES.find((p) => p.name === region.province) || null)
const regionLabel = computed(() => {
  if (searchForm.city && searchForm.city !== searchForm.province) return searchForm.city
  return searchForm.province || '区域'
})

function applyRegion(province: string | null, city: string | null) {
  searchForm.province = province
  searchForm.city = city
  region.open = false
  debouncedFilterSearch()
}

function pickProvince(name: string | null) {
  region.province = name
  const p = PROVINCES.find((x) => x.name === name)
  if (!p) applyRegion(null, null)
  else if (isMunicipality(p)) applyRegion(p.name, p.name)
}

type CardIcon = NonNullable<SearchItem['icons']>[number]
const titleIcons = (it: SearchItem) => (it.icons || []).filter((i) => i.row === 'r1')
const serviceIcons = (it: SearchItem) => (it.icons || []).filter((i) => i.row !== 'r1')
/** 按闲鱼给的宽高等比缩放到目标高度 */
function iconStyle(ic: CardIcon, height: number) {
  const ratio = ic.width && ic.height ? ic.width / ic.height : 2
  return { height: `${height}px`, width: `${Math.round(height * ratio)}px` }
}

// 引导探索分类推荐
const exploreCategories = [
  { icon: '💻', name: '数码轻奢', items: ['MacBook M1', 'iPhone 15', 'iPad Air', 'AirPods Pro'] },
  { icon: '🎮', name: '游戏电竞', items: ['Switch OLED', 'PS5', 'Steam Deck', '显卡 RTX'] },
  { icon: '📷', name: '影像外设', items: ['索尼微单', '佳能微单', '机械键盘', '戴森吹风机'] },
]

// 搜索结果状态
const items = ref<SearchItem[]>([])
const loading = ref(false)
const searched = ref(false)
const hasMore = ref(false)
const searchError = ref('')

let lastSearchTime = 0
let filterDebounceTimer: number | undefined

async function doSearch(page = 1) {
  const kw = searchForm.keyword.trim()
  if (!kw) {
    ElMessage.warning('请输入搜索关键词')
    return
  }
  lastQueryQ = kw

  // 智能降速保护：如果两次搜索发起间隔小于 1.8 秒，自动平滑缓冲，模拟真人操作节奏，降低触发平台风控几率
  const now = Date.now()
  const timeSinceLast = now - lastSearchTime
  if (timeSinceLast < 1800) {
    await new Promise((resolve) => setTimeout(resolve, 1800 - timeSinceLast))
  }
  lastSearchTime = Date.now()

  searchForm.page = page
  loading.value = true
  searchError.value = ''
  searched.value = true
  try {
    const res = await liveSearch({
      keyword: kw,
      page: searchForm.page,
      sort: searchForm.sort,
      min_price: searchForm.min_price || null,
      max_price: searchForm.max_price || null,
      province: searchForm.province?.trim() || null,
      city: searchForm.city?.trim() || null,
      publish_days: searchForm.publish_days > 0 ? searchForm.publish_days : null,
      personal_only: searchForm.personal_only,
      free_shipping: searchForm.free_shipping,
      quick_filters: quickExtra.value.join(',') || undefined,
      account_id: searchForm.account_id > 0 ? searchForm.account_id : null,
    })
    items.value = res.items || []
    hasMore.value = !!res.has_more
    // 顺便把参数同步到 URL，方便刷新与分享
    router.replace({ query: { q: kw, sort: searchForm.sort } })
  } catch (e: unknown) {
    items.value = []
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    searchError.value = err.response?.data?.detail || err.message || '搜索失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function debouncedFilterSearch() {
  window.clearTimeout(filterDebounceTimer)
  filterDebounceTimer = window.setTimeout(() => {
    if (searchForm.keyword.trim()) {
      doSearch(1)
    }
  }, 350)
}

function onQuickSearch(kw: string) {
  searchForm.keyword = kw
  doSearch(1)
}

function resetFilters() {
  searchForm.min_price = null
  searchForm.max_price = null
  searchForm.province = null
  searchForm.city = null
  searchForm.publish_days = 0
  searchForm.personal_only = false
  searchForm.free_shipping = false
  searchForm.account_id = 0
  searchForm.sort = 'default'
  quickExtra.value = []
  region.province = null
  if (searchForm.keyword.trim()) {
    doSearch(1)
  }
}

// ---------------------------------------------------------------- 详情抽屉
const detail = reactive({
  open: false,
  loading: false,
  itemId: '',
  data: null as ItemDetail | null,
})

async function openDetail(it: SearchItem) {
  detail.open = true
  detail.loading = true
  detail.itemId = it.item_id
  detail.data = null
  try {
    detail.data = await getItemDetail(it.item_id, searchForm.account_id > 0 ? searchForm.account_id : null)
  } catch {
    // 降级使用搜索列表给出的基本数据
    detail.data = {
      item: it,
      seller: {
        seller_id: it.seller_id,
        nick: it.seller_nick,
        zhima_level: '',
        reg_days: null,
        sold_cnt: null,
      },
      status: '在售',
    }
  } finally {
    detail.loading = false
  }
}

function safeItemLink(it: SearchItem | null) {
  if (!it) return '#'
  if (it.link) return it.link
  return `https://www.goofish.com/item?id=${it.item_id}`
}

function quickResell(it: SearchItem) {
  const p = it.price || 0
  const suggestedPrice = Math.round(p * 1.15) || p
  router.push({
    path: '/goods/publish',
    query: {
      from: 'resell',
      title: it.title,
      price: suggestedPrice || undefined,
      hint: `原低价捡漏入手，原价 ${p}，成色完好，转手诚出`,
    },
  })
}

// ---------------------------------------------------------------- 转为自动搜货
const taskModal = reactive({
  open: false,
  saving: false,
  form: emptyTask(),
})

function openCreateTask(fromItem?: SearchItem) {
  const kw = fromItem?.title || searchForm.keyword.trim() || '好货'
  const t = emptyTask()
  t.name = `自动搜货：${kw.slice(0, 16)}`
  t.keywords = [searchForm.keyword.trim() || kw.slice(0, 20)]
  t.min_price = searchForm.min_price ?? null
  t.max_price = searchForm.max_price ?? null
  t.province = searchForm.province ?? null
  t.city = searchForm.city ?? null
  t.personal_only = !!searchForm.personal_only
  t.free_shipping = !!searchForm.free_shipping
  t.sort = searchForm.sort || 'newest'
  t.cron = '*/30 8-23 * * *'
  taskModal.form = t
  taskModal.open = true
}

async function saveTask() {
  if (!taskModal.form.name.trim()) {
    ElMessage.warning('请输入任务名称')
    return
  }
  if (!taskModal.form.keywords.length || !taskModal.form.keywords[0]?.trim()) {
    ElMessage.warning('请至少指定一个关键词')
    return
  }
  taskModal.saving = true
  try {
    await createTask(taskModal.form)
    ElMessage.success('已保存为自动搜货，搜到的好货会出现在好货看板')
    taskModal.open = false
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(err.response?.data?.detail || '保存自动搜货失败')
  } finally {
    taskModal.saving = false
  }
}

/** 看中某一件：带着商品去价格监控，自动打开添加弹窗 */
function watchPrice(it: SearchItem) {
  router.push({ path: '/radar/watch', query: { add: it.item_id, title: it.title, price: it.price ?? undefined } })
}

let lastQueryQ: string | null = null

function checkRouteQuery() {
  const q = typeof route.query.q === 'string' ? route.query.q.trim() : ''
  if (q && q !== lastQueryQ) {
    lastQueryQ = q
    searchForm.keyword = q
    if (typeof route.query.sort === 'string') {
      searchForm.sort = route.query.sort as LiveSearchQuery['sort']
    }
    doSearch(1)
  }
}

onMounted(() => {
  accounts.load().catch(() => undefined)
  checkRouteQuery()
})

onActivated(() => {
  checkRouteQuery()
})
</script>

<template>
  <div class="page radar-search-page">
    <RadarNav current="search" />

    <!-- 搜索头：对齐闲鱼网页版（黄底 + 黑描边搜索框 + 下方热搜词） -->
    <div class="gf-yellow-header">
      <div class="gf-brand-block">
        <span class="gf-fish-char">闲鱼</span>
        <span class="gf-brand-sub">实时搜货</span>
      </div>

      <div class="gf-search-center">
        <div class="gf-search-box">
          <input
            v-model="searchForm.keyword"
            type="text"
            class="gf-search-input"
            placeholder="搜索想要的宝贝，例如：iPhone 15、MacBook Air M1"
            @keyup.enter="doSearch(1)"
          />
          <button v-if="searchForm.keyword" type="button" class="gf-clear-btn" title="清空" @click="searchForm.keyword = ''">
            <el-icon><Close /></el-icon>
          </button>
          <button type="button" class="gf-search-btn" :disabled="loading" @click="doSearch(1)">
            <el-icon :class="{ 'is-loading': loading }"><Refresh v-if="loading" /><Search v-else /></el-icon>
            <span>搜索</span>
          </button>
        </div>
        <div class="gf-hot-stream">
          <span v-for="kw in hotKeywords" :key="kw" class="gf-hot-item" @click="onQuickSearch(kw)">{{ kw }}</span>
        </div>
      </div>

      <div class="gf-header-actions">
        <button v-if="searchForm.keyword.trim()" type="button" class="gf-task-convert-btn" @click="openCreateTask()">
          <el-icon><Bell /></el-icon>
          <span>转自动搜货</span>
        </button>
      </div>
    </div>

    <!-- 筛选卡片：对齐闲鱼网页版（排序 / 价格 / 区域 / 分页 + 快捷勾选） -->
    <div class="gf-filter-card">
      <div class="gf-filter-row">
        <div class="gf-sorts">
          <button type="button" class="gf-sort" :class="{ 'is-active': searchForm.sort === 'default' }" @click="setSort('default')">综合</button>
          <button type="button" class="gf-sort" :class="{ 'is-active': searchForm.sort === 'reduce' }" @click="setSort('reduce')">新降价</button>
          <el-dropdown trigger="hover" @command="setPublishDays">
            <button
              type="button"
              class="gf-sort"
              :class="{ 'is-active': searchForm.sort === 'newest' }"
              @click="setSort('newest')"
            >
              {{ publishLabel }}<el-icon class="gf-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="d in publishDayOptions" :key="d.value" :command="d.value">
                  <span :class="{ 'gf-menu-on': searchForm.publish_days === d.value }">{{ d.label }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown trigger="hover" @command="setSort">
            <button
              type="button"
              class="gf-sort"
              :class="{ 'is-active': searchForm.sort === 'price_asc' || searchForm.sort === 'price_desc' }"
            >
              {{ priceSortLabel }}<el-icon class="gf-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="price_asc">价格从低到高</el-dropdown-item>
                <el-dropdown-item command="price_desc">价格从高到低</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <div class="gf-price-range">
            <label class="gf-price-input">
              <span class="yen">¥</span>
              <input v-model.number="searchForm.min_price" type="number" min="0" @keyup.enter="doSearch(1)" @change="debouncedFilterSearch" />
            </label>
            <span class="range-dash">-</span>
            <label class="gf-price-input">
              <span class="yen">¥</span>
              <input v-model.number="searchForm.max_price" type="number" min="0" @keyup.enter="doSearch(1)" @change="debouncedFilterSearch" />
            </label>
          </div>
        </div>

        <div class="gf-filter-right">
          <el-popover v-model:visible="region.open" placement="bottom-end" :width="460" trigger="click" popper-class="gf-region-popper">
            <template #reference>
              <button type="button" class="gf-sort gf-region-btn" :class="{ 'is-active': !!searchForm.province }">
                {{ regionLabel }}<el-icon class="gf-caret" :class="{ open: region.open }"><ArrowDown /></el-icon>
              </button>
            </template>
            <div class="gf-region">
              <div class="gf-region-head">
                <span class="gf-region-tab">选地区</span>
                <el-icon class="gf-region-close" @click="region.open = false"><Close /></el-icon>
              </div>
              <div class="gf-region-body">
                <div class="gf-region-col left">
                  <div class="gf-region-opt" :class="{ on: !region.province }" @click="pickProvince(null)">全国</div>
                  <div
                    v-for="p in PROVINCES"
                    :key="p.name"
                    class="gf-region-opt"
                    :class="{ on: region.province === p.name }"
                    @click="pickProvince(p.name)"
                  >
                    {{ p.name }}
                  </div>
                </div>
                <div class="gf-region-col right">
                  <template v-if="regionProvince && regionProvince.cities.length">
                    <div
                      class="gf-region-opt"
                      :class="{ on: searchForm.province === regionProvince.name && !searchForm.city }"
                      @click="applyRegion(regionProvince.name, null)"
                    >
                      全{{ regionProvince.name }}
                      <el-icon v-if="searchForm.province === regionProvince.name && !searchForm.city"><Check /></el-icon>
                    </div>
                    <div
                      v-for="c in regionProvince.cities"
                      :key="c"
                      class="gf-region-opt"
                      :class="{ on: searchForm.city === c }"
                      @click="applyRegion(regionProvince.name, c)"
                    >
                      {{ c }}<el-icon v-if="searchForm.city === c"><Check /></el-icon>
                    </div>
                  </template>
                  <div v-else class="gf-region-opt on">
                    {{ searchForm.province || '全国' }}<el-icon><Check /></el-icon>
                  </div>
                </div>
              </div>
            </div>
          </el-popover>

          <div class="gf-pager">
            <button type="button" class="gf-page-arrow" :disabled="(searchForm.page || 1) <= 1" @click="doSearch((searchForm.page || 1) - 1)">‹</button>
            <span class="gf-page-text">{{ searchForm.page || 1 }}/50</span>
            <button type="button" class="gf-page-arrow" :disabled="!hasMore" @click="doSearch((searchForm.page || 1) + 1)">›</button>
          </div>
        </div>
      </div>

      <div class="gf-check-row">
        <label v-for="f in QUICK_FILTERS" :key="f.key" class="gf-check" :class="{ on: isQuickOn(f.key) }">
          <input type="checkbox" :checked="isQuickOn(f.key)" @change="toggleQuick(f.key)" />
          <span class="gf-check-box"><el-icon v-if="isQuickOn(f.key)"><Check /></el-icon></span>
          <span>{{ f.label }}</span>
        </label>
        <button type="button" class="gf-reset-btn" @click="resetFilters">重置筛选</button>
      </div>
    </div>

    <!-- 结果区域 -->
    <div class="results-container" v-loading="loading">
      <!-- 错误提示 -->
      <el-alert v-if="searchError" type="error" show-icon :closable="false" class="mb">
        <template #title>搜索遇到问题</template>
        <div class="search-error-msg">{{ searchError }}</div>
        <div v-if="searchError.includes('RGV587') || searchError.includes('风控') || searchError.includes('安全限制') || searchError.includes('挤爆')" class="search-error-tip">
          💡 <strong>应对建议</strong>：当前请求通道（如本地 IP 或当前账号）被闲鱼官方识别并临时限流。如果您有多个闲鱼账号，请在上方<strong>「账号通道」</strong>下拉框中切换其他正常账号重试；或稍等 2~5 分钟等限制自动解除。
        </div>
      </el-alert>

      <!-- 结果栏：数量 + 请求通道 + 视图切换 -->
      <div v-if="searched && !searchError" class="results-bar">
        <div class="result-count">
          找到 <b>{{ items.length }}</b> 件商品<span class="muted"> · 第 {{ searchForm.page || 1 }} 页</span>
        </div>
        <div class="results-tools">
          <span class="pacing-protect-pill" title="两次搜索之间自动保持温和节奏，降低触发闲鱼频控的概率">🛡️ 智能控频</span>
          <el-select v-model="searchForm.account_id" size="small" class="gf-account-select" @change="debouncedFilterSearch">
            <el-option :value="0" label="自动 / 匿名通道" />
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.nickname || a.remark || a.unb" />
          </el-select>
          <el-button-group size="small">
            <el-button :type="viewMode === 'grid' ? 'primary' : 'default'" :icon="Grid" title="网格" @click="viewMode = 'grid'" />
            <el-button :type="viewMode === 'list' ? 'primary' : 'default'" :icon="List" title="列表" @click="viewMode = 'list'" />
          </el-button-group>
        </div>
      </div>

      <!-- 未搜索时的引导占位（沉浸式高维 Hero 视界，撑满视口剩余高度） -->
      <div v-if="!searched && !loading" class="welcome-box">
        <div class="welcome-inner">
          <div class="icon-circle">
            <el-icon :size="36" class="welcome-search-ico"><Search /></el-icon>
          </div>
          <h3 class="welcome-title">输入关键词，立即探索闲鱼一手好货</h3>
          <p class="welcome-desc">
            无需先建自动搜货等待！直接输入商品名称或型号，秒级同步闲鱼全量最新挂牌底价、成色与卖家信誉。
          </p>

          <!-- 热门探索专区分类药丸矩阵 (充实下半部分空间，美观实用) -->
          <div class="welcome-categories">
            <div v-for="cat in exploreCategories" :key="cat.name" class="cat-explore-row">
              <span class="cat-pill-badge">
                <span class="cat-icon">{{ cat.icon }}</span>
                <span>{{ cat.name }}</span>
              </span>
              <div class="cat-chips-list">
                <button
                  v-for="k in cat.items"
                  :key="k"
                  type="button"
                  class="explore-chip-btn"
                  @click="onQuickSearch(k)"
                >
                  {{ k }}
                </button>
              </div>
            </div>
          </div>

          <div class="welcome-bottom-tip">
            <span>💡 捡漏小贴士：在上方筛选开启「仅看个人闲置」，可智能过滤商家批量加价文案与批量铺货引流品</span>
          </div>
        </div>
      </div>

      <!-- 搜索无结果 -->
      <div v-else-if="searched && !loading && !items.length && !searchError" class="no-result-box">
        <el-empty description="没有找到符合条件的商品，试试调整筛选或点击热门搜索词：">
          <div class="quick-try" style="margin-top: 12px; flex-wrap: wrap;">
            <el-button v-for="k in hotKeywords.slice(0, 6)" :key="k" size="small" round @click="onQuickSearch(k)">
              {{ k }}
            </el-button>
          </div>
        </el-empty>
      </div>

      <!-- 网格卡片：对齐闲鱼网页版卡片（标签全部来自接口，不做推测） -->
      <div v-else-if="viewMode === 'grid'" class="gf-items-grid">
        <div v-for="it in items" :key="it.item_id" class="gf-item-card" @click="openDetail(it)">
          <div class="gf-cover-box">
            <el-image :src="it.image_url" fit="cover" class="gf-card-img" lazy referrerpolicy="no-referrer">
              <template #error>
                <div class="gf-img-error"><el-icon><Picture /></el-icon></div>
              </template>
            </el-image>
          </div>

          <div class="gf-card-info">
            <div class="gf-card-title" :title="it.title">
              <img
                v-for="ic in titleIcons(it)"
                :key="ic.name"
                :src="ic.url"
                :style="iconStyle(ic, 18)"
                class="gf-title-icon"
                referrerpolicy="no-referrer"
                alt=""
              />
              <span v-if="!titleIcons(it).length && it.tags?.includes('包邮')" class="gf-badge-baoyou">包邮</span>
              {{ it.title }}
            </div>
            <div v-if="it.attrs?.length" class="gf-attrs">
              <span v-for="a in it.attrs" :key="a" class="gf-attr">{{ a }}</span>
            </div>
            <div v-if="serviceIcons(it).length" class="gf-service-icons">
              <img
                v-for="ic in serviceIcons(it)"
                :key="ic.name"
                :src="ic.url"
                :style="iconStyle(ic, 16)"
                referrerpolicy="no-referrer"
                alt=""
              />
            </div>

            <div class="gf-price-line">
              <span class="gf-price-val"><span class="yen">¥</span><span class="num">{{ it.price ?? '-' }}</span></span>
              <span v-if="it.price_note" class="gf-price-note">{{ it.price_note }}</span>
              <span v-else-if="it.want_cnt" class="gf-want-text">{{ it.want_cnt }}人想要</span>
            </div>

            <div class="gf-seller-bar">
              <div class="gf-seller-info">
                <img v-if="it.avatar" :src="it.avatar" class="gf-seller-avatar" referrerpolicy="no-referrer" alt="" />
                <span v-else class="gf-seller-avatar fallback">{{ (it.seller_nick || '闲')[0] }}</span>
                <span class="gf-seller-area ellipsis">{{ it.area || it.seller_nick || '闲鱼卖家' }}</span>
              </div>
              <span v-if="it.seller_tags?.length" class="gf-credit-pill">{{ it.seller_tags[0] }}</span>
            </div>

            <div class="gf-hover-actions" @click.stop>
              <button type="button" class="gf-hover-btn primary" @click="openDetail(it)">详情 · 分析</button>
              <button type="button" class="gf-hover-btn ghost" @click="watchPrice(it)">价格监控</button>
              <button type="button" class="gf-hover-btn success" @click="quickResell(it)">转手发品</button>
              <a :href="safeItemLink(it)" target="_blank" rel="noopener" class="gf-hover-link">
                <button type="button" class="gf-hover-btn yellow">去闲鱼<el-icon><TopRight /></el-icon></button>
              </a>
            </div>
          </div>
        </div>
      </div>

      <!-- 紧凑列表模式 -->
      <el-card v-else-if="viewMode === 'list'" shadow="never" class="list-card">
        <el-table :data="items" @row-click="(row: SearchItem) => openDetail(row)">
          <el-table-column label="商品" min-width="320">
            <template #default="{ row }">
              <div class="list-item-title-box">
                <el-image :src="row.image_url" fit="cover" class="list-thumb" lazy referrerpolicy="no-referrer" />
                <div class="list-item-info">
                  <div class="list-title">{{ row.title }}</div>
                  <div class="muted small list-tags">
                    <span v-if="row.area">{{ row.area }}</span>
                    <span v-if="row.want_cnt"> · {{ row.want_cnt }}人想要</span>
                    <el-tag v-for="t in (row.tags || []).slice(0, 2)" :key="t" size="small" effect="plain" class="ml-s">{{ t }}</el-tag>
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="价格" width="120">
            <template #default="{ row }">
              <span class="price-val">{{ fmtMoney(row.price) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="卖家" min-width="120">
            <template #default="{ row }">
              <div class="small">{{ row.seller_nick || '-' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="发布时间" width="120">
            <template #default="{ row }">
              <span class="muted small">{{ fmtRelative(row.publish_time) || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }">
              <div @click.stop>
                <el-button size="small" type="primary" link @click="openDetail(row as SearchItem)">详情</el-button>
                <el-button size="small" type="success" link :icon="Upload" @click="quickResell(row as SearchItem)">转手发品</el-button>
                <a :href="safeItemLink(row as SearchItem)" target="_blank" rel="noopener" class="ml-s">
                  <el-button size="small" link>去闲鱼</el-button>
                </a>
                <el-button size="small" link type="warning" @click="watchPrice(row as SearchItem)">价格监控</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 底部翻页栏 -->
      <div v-if="searched && items.length" class="pagination-footer">
        <el-button :disabled="(searchForm.page || 1) <= 1" :icon="Refresh" @click="doSearch((searchForm.page || 1) - 1)">
          上一页
        </el-button>
        <span class="page-indicator">第 {{ searchForm.page || 1 }} 页</span>
        <el-button :disabled="!hasMore" type="primary" @click="doSearch((searchForm.page || 1) + 1)">
          下一页
        </el-button>
      </div>
    </div>

    <!-- 商品详情抽屉 -->
    <el-drawer v-model="detail.open" title="商品详情" size="600px" destroy-on-close>
      <div v-loading="detail.loading" class="detail-container">
        <template v-if="detail.data">
          <!-- 轮播大图 -->
          <div class="carousel-wrap">
            <el-carousel v-if="detail.data.item.images?.length" height="340px" trigger="click">
              <el-carousel-item v-for="(img, idx) in detail.data.item.images" :key="idx">
                <el-image :src="img" fit="contain" class="carousel-img" referrerpolicy="no-referrer" />
              </el-carousel-item>
            </el-carousel>
            <el-image v-else :src="detail.data.item.image_url" fit="contain" class="carousel-img single" referrerpolicy="no-referrer" />
          </div>

          <!-- 价格与标题 -->
          <div class="detail-price-box">
            <div class="d-price">{{ fmtMoney(detail.data.item.price) }}</div>
            <div v-if="detail.data.item.orig_price" class="d-orig">原价 {{ fmtMoney(detail.data.item.orig_price) }}</div>
            <div class="d-stats muted small">
              <span v-if="detail.data.item.want_cnt">{{ detail.data.item.want_cnt }} 人想要</span>
              <span v-if="detail.data.item.browse_cnt"> · {{ detail.data.item.browse_cnt }} 次浏览</span>
              <span v-if="detail.data.item.area"> · {{ detail.data.item.area }}</span>
            </div>
          </div>

          <h3 class="detail-title">{{ detail.data.item.title }}</h3>

          <!-- 卖家信息卡片 -->
          <el-card shadow="never" class="seller-card">
            <div class="seller-row">
              <div class="s-avatar">
                <el-avatar :size="40" :icon="User" />
              </div>
              <div class="s-info">
                <div class="s-name">{{ detail.data.seller.nick || detail.data.item.seller_nick || '闲鱼卖家' }}</div>
                <div class="s-tags">
                  <el-tag v-if="detail.data.seller.zhima_level" size="small" type="success" effect="plain">
                    芝麻{{ detail.data.seller.zhima_level }}
                  </el-tag>
                  <el-tag v-if="detail.data.seller.sold_cnt !== null" size="small" type="info" effect="plain">
                    已售出 {{ detail.data.seller.sold_cnt }} 件
                  </el-tag>
                  <el-tag v-if="detail.data.seller.reg_days" size="small" type="info" effect="plain">
                    来闲鱼 {{ Math.round(detail.data.seller.reg_days / 365) || 1 }} 年
                  </el-tag>
                </div>
              </div>
            </div>
          </el-card>

          <!-- 宝贝描述 -->
          <div class="detail-desc-box">
            <h4>商品描述</h4>
            <div class="desc-content">
              {{ detail.data.item.desc || '卖家未填写更多文字描述。' }}
            </div>
          </div>

          <div class="detail-analysis-box">
            <ItemAnalysisPanel
              :key="detail.itemId"
              :item-id="detail.data.item.item_id || detail.itemId"
              :keyword="searchForm.keyword"
              :account-id="searchForm.account_id > 0 ? searchForm.account_id : null"
              :ip-location="detail.data.seller.ip_location || ''"
              :sold-cnt="detail.data.seller.sold_cnt"
            />
          </div>

          <!-- 底部操作按钮 -->
          <div class="detail-drawer-footer">
            <div class="footer-btn-group">
              <a :href="safeItemLink(detail.data.item)" target="_blank" rel="noopener" class="half-btn">
                <el-button type="primary" size="large" class="full">
                  去闲鱼购买
                  <el-icon class="el-icon--right"><TopRight /></el-icon>
                </el-button>
              </a>
              <el-button type="success" size="large" :icon="Upload" class="half-btn" @click="quickResell(detail.data.item)">
                一键转手发品
              </el-button>
            </div>
            <el-button size="large" :icon="Bell" class="mt-s full" @click="watchPrice(detail.data.item)">
              监控这件商品的价格
            </el-button>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 一键转自动搜货弹窗 -->
    <el-dialog v-model="taskModal.open" title="保存为自动搜货" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="taskModal.form.name" placeholder="例如：M1 Air 笔记本" />
        </el-form-item>
        <el-form-item label="搜索关键词" required>
          <el-input
            :model-value="taskModal.form.keywords.join(' ')"
            placeholder="多个关键词用空格隔开"
            @update:model-value="(v: string) => taskModal.form.keywords = v.split(/\s+/).filter(Boolean)"
          />
          <div class="form-tip">系统将按这些关键词定期搜索闲鱼新上架的商品。</div>
        </el-form-item>
        <el-form-item label="价格区间">
          <div class="range">
            <el-input-number v-model="taskModal.form.min_price" placeholder="最低" :controls="false" class="w120" />
            <span>至</span>
            <el-input-number v-model="taskModal.form.max_price" placeholder="最高" :controls="false" class="w120" />
          </div>
        </el-form-item>
        <el-form-item label="巡检频率">
          <el-select v-model="taskModal.form.cron" class="full">
            <el-option value="*/30 8-23 * * *" label="日常巡检 · 每 30 分钟一次（推荐，低风控）" />
            <el-option value="*/10 8-23 * * *" label="急切捡漏 · 每 10 分钟一次（白天）" />
            <el-option value="0 * * * *" label="平稳巡检 · 每小时一次" />
            <el-option value="0 */2 * * *" label="闲时巡检 · 每 2 小时一次" />
            <el-option value="0 9,21 * * *" label="定时汇总 · 每天早晚 9 点 / 21 点" />
          </el-select>
        </el-form-item>
        <el-form-item label="筛选条件">
          <el-checkbox v-model="taskModal.form.personal_only" label="仅看个人闲置" />
          <el-checkbox v-model="taskModal.form.free_shipping" label="仅看包邮" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="taskModal.open = false">取消</el-button>
        <el-button type="primary" :loading="taskModal.saving" @click="saveTask">保存并开始自动搜货</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.radar-search-page {
  min-height: calc(100vh - 96px);
  display: flex;
  flex-direction: column;
}
/* ---------------- 搜索头（闲鱼网页版：黄底、黑描边搜索框、黄色搜索按钮） */
.gf-yellow-header {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr) 160px;
  align-items: center;
  gap: 16px;
  background: #ffe60f;
  border-radius: 12px;
  padding: 14px 20px 10px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.gf-brand-block {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.gf-fish-char {
  font-size: 26px;
  font-weight: 900;
  letter-spacing: 2px;
  color: #1a1a1a;
}
.gf-brand-sub {
  font-size: 13px;
  font-weight: 600;
  color: #1a1a1a;
  opacity: 0.75;
}
.gf-search-center {
  width: 100%;
  max-width: 720px;
  justify-self: center;
}
.gf-search-box {
  display: flex;
  align-items: center;
  height: 44px;
  background: #fff;
  border: 2px solid #1a1a1a;
  border-radius: 12px;
  padding: 0 4px 0 16px;
}
.gf-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: #1a1a1a;
}
.gf-search-input::placeholder {
  color: #a3a3a3;
}
.gf-clear-btn {
  border: none;
  background: transparent;
  color: #a3a3a3;
  cursor: pointer;
  display: inline-flex;
  padding: 6px;
  font-size: 14px;
}
.gf-clear-btn:hover {
  color: #1a1a1a;
}
.gf-search-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 34px;
  padding: 0 16px;
  border: none;
  border-radius: 9px;
  background: #ffe60f;
  color: #1a1a1a;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.gf-search-btn:hover {
  background: #ffd900;
}
.gf-search-btn:disabled {
  cursor: progress;
}
.gf-hot-stream {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 4px 16px;
  margin-top: 8px;
  font-size: 13px;
}
.gf-hot-item {
  color: #1a1a1a;
  cursor: pointer;
}
.gf-hot-item:hover {
  text-decoration: underline;
}
.gf-header-actions {
  display: flex;
  justify-content: flex-end;
}
.gf-task-convert-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 12px;
  border: none;
  border-radius: 8px;
  background: #1a1a1a;
  color: #ffe60f;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.gf-task-convert-btn:hover {
  background: #333;
}

/* ---------------- 筛选卡片（闲鱼网页版：文字排序 + 灰底激活、方形勾选框） */
.gf-filter-card {
  background: #fff;
  border-radius: 12px;
  padding: 14px 20px 12px;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.gf-filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.gf-sorts,
.gf-filter-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.gf-filter-right {
  gap: 12px;
}
.gf-sort {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 36px;
  padding: 0 14px;
  border: none;
  border-radius: 18px;
  background: transparent;
  color: #1a1a1a;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  outline: none;
}
.gf-sort:hover,
.gf-sort.is-active {
  background: #f2f3f5;
}
.gf-caret {
  font-size: 12px;
  margin-left: 2px;
  transition: transform 0.15s;
}
.gf-caret.open {
  transform: rotate(180deg);
}
:global(.gf-menu-on) {
  color: #ff4400;
  font-weight: 600;
}
.gf-price-range {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 6px;
}
.gf-price-input {
  display: flex;
  align-items: center;
  width: 104px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  background: #fff;
}
.gf-price-input:focus-within {
  border-color: #1a1a1a;
}
.gf-price-input .yen {
  color: #8a8f99;
  font-size: 13px;
  margin-right: 4px;
}
.gf-price-input input {
  width: 100%;
  min-width: 0;
  border: none;
  outline: none;
  font-size: 13px;
  -moz-appearance: textfield;
}
.gf-price-input input::-webkit-outer-spin-button,
.gf-price-input input::-webkit-inner-spin-button {
  -webkit-appearance: none;
}
.range-dash {
  color: #c0c4cc;
}
.gf-pager {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gf-page-arrow {
  width: 30px;
  height: 30px;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  background: #fff;
  color: #1a1a1a;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.gf-page-arrow:hover:not(:disabled) {
  border-color: #1a1a1a;
}
.gf-page-arrow:disabled {
  color: #c9cdd4;
  cursor: not-allowed;
}
.gf-page-text {
  font-size: 14px;
  color: #1a1a1a;
  min-width: 36px;
  text-align: center;
}
.gf-check-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 22px;
  margin-top: 10px;
  padding: 0 14px;
}
.gf-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #1a1a1a;
  cursor: pointer;
  user-select: none;
}
.gf-check input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.gf-check-box {
  width: 16px;
  height: 16px;
  border: 1px solid #c9cdd4;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #1a1a1a;
  transition: all 0.15s;
}
.gf-check:hover .gf-check-box {
  border-color: #1a1a1a;
}
.gf-check.on .gf-check-box {
  background: #ffe60f;
  border-color: #1a1a1a;
}
.gf-check input:focus-visible + .gf-check-box {
  outline: 2px solid #1a1a1a;
  outline-offset: 2px;
}
.gf-reset-btn {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #8a8f99;
  font-size: 13px;
  cursor: pointer;
}
.gf-reset-btn:hover {
  color: #1a1a1a;
}

/* 区域弹层（选地区：左省右市） */
:global(.gf-region-popper.el-popover) {
  padding: 0 !important;
  border-radius: 12px !important;
  overflow: hidden;
}
.gf-region-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px 10px;
  border-bottom: 1px solid #f2f3f5;
}
.gf-region-tab {
  font-size: 15px;
  font-weight: 700;
  color: #1a1a1a;
  box-shadow: inset 0 -6px 0 #ffe60f;
}
.gf-region-close {
  cursor: pointer;
  color: #8a8f99;
}
.gf-region-close:hover {
  color: #1a1a1a;
}
.gf-region-body {
  display: grid;
  grid-template-columns: 120px 1fr;
  height: 320px;
}
.gf-region-col {
  overflow-y: auto;
  padding: 6px 0;
}
.gf-region-col.left {
  background: #f7f8fa;
}
.gf-region-col.right {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  align-content: start;
  padding: 6px 8px;
}
.gf-region-opt {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  font-size: 14px;
  color: #1a1a1a;
  cursor: pointer;
}
.gf-region-opt:hover {
  color: #ff4400;
}
.gf-region-col.left .gf-region-opt.on {
  background: #fff;
  color: #ff4400;
  font-weight: 600;
}
.gf-region-col.right .gf-region-opt {
  padding: 8px 10px;
}
.gf-region-col.right .gf-region-opt.on {
  color: #ff4400;
  font-weight: 600;
}

.results-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.results-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.result-count {
  font-size: 14px;
  color: #1a1a1a;
}
.result-count b {
  color: #ff4400;
  font-size: 16px;
}
.results-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gf-account-select {
  width: 150px;
}

/* 欢迎/引导区 (闲鱼明黄微光 Hero 视界) */
.welcome-box {
  flex: 1;
  min-height: 460px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at 50% 18%, #fffdeb 0%, #ffffff 75%);
  border-radius: 12px;
  border: 1px solid #fef08a;
  box-shadow: 0 2px 12px rgba(254, 240, 138, 0.2);
  padding: 32px 24px;
  box-sizing: border-box;
  text-align: center;
}
.welcome-inner {
  max-width: 600px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.icon-circle {
  width: 64px;
  height: 64px;
  background: #ffda00;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  box-shadow: 0 4px 12px rgba(255, 218, 0, 0.4);
}
.welcome-search-ico {
  color: #111111;
}
.welcome-title {
  font-size: 17px;
  font-weight: 700;
  color: #111111;
  margin: 0 0 6px 0;
}
.welcome-desc {
  font-size: 12.5px;
  color: #666666;
  line-height: 1.5;
  margin: 0 0 18px 0;
  max-width: 480px;
}
.welcome-categories {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  margin-bottom: 18px;
}
.cat-explore-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
  border: 1px solid #f0f0f0;
  border-radius: 999px;
  padding: 4px 8px 4px 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}
.cat-pill-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  color: #111111;
  background: #ffda00;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.cat-chips-list {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.explore-chip-btn {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #333333;
  background: #f7f7f7;
  border: 1px solid #eeeeee;
  cursor: pointer;
  transition: all 0.15s ease;
}
.explore-chip-btn:hover {
  background: #ffda00;
  border-color: #ffda00;
  color: #111111;
  font-weight: 600;
  transform: translateY(-1px);
}
.welcome-bottom-tip {
  font-size: 11.5px;
  color: #666666;
  background: rgba(255, 255, 255, 0.85);
  border: 1px dashed #ddd;
  padding: 6px 14px;
  border-radius: 8px;
}

/* ---------------- 商品卡片（闲鱼网页版：方图、两行标题、灰色属性、橙红价格、底部卖家） */
.gf-items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}
.gf-item-card {
  position: relative;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: box-shadow 0.2s;
}
.gf-item-card:hover {
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
}
.gf-cover-box {
  aspect-ratio: 1 / 1;
  background: #f2f3f5;
  overflow: hidden;
}
.gf-card-img {
  width: 100%;
  height: 100%;
  display: block;
}
.gf-img-error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  font-size: 28px;
  color: #c9cdd4;
}
.gf-card-info {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px 12px;
  flex: 1;
}
.gf-card-title {
  font-size: 15px;
  line-height: 22px;
  color: #1a1a1a;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 44px;
}
.gf-title-icon {
  vertical-align: -3px;
  margin-right: 4px;
}
.gf-badge-baoyou {
  display: inline-block;
  margin-right: 4px;
  padding: 0 4px;
  border-radius: 4px;
  background: #ffe60f;
  color: #1a1a1a;
  font-size: 12px;
  font-weight: 700;
  line-height: 18px;
  vertical-align: 1px;
}
.gf-attrs {
  display: flex;
  flex-wrap: wrap;
  font-size: 12px;
  color: #999;
  line-height: 16px;
  overflow: hidden;
  max-height: 16px;
}
.gf-attr + .gf-attr::before {
  content: '';
  display: inline-block;
  width: 1px;
  height: 10px;
  margin: 0 5px;
  background: #d6d6d6;
  vertical-align: -1px;
}
.gf-service-icons {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.gf-price-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: auto;
  padding-top: 2px;
}
.gf-price-val {
  color: #ff4400;
  font-weight: 700;
  white-space: nowrap;
}
.gf-price-val .yen {
  font-size: 13px;
}
.gf-price-val .num {
  font-size: 22px;
  font-family: 'DIN Alternate', 'Helvetica Neue', Arial, sans-serif;
}
.gf-price-note {
  font-size: 12px;
  color: #ff4400;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.gf-want-text {
  font-size: 12px;
  color: #999;
  white-space: nowrap;
}
.gf-seller-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.gf-seller-info {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.gf-seller-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}
.gf-seller-avatar.fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #ffe60f;
  color: #1a1a1a;
  font-size: 11px;
  font-weight: 700;
}
.gf-seller-area {
  font-size: 13px;
  color: #666;
}
.gf-credit-pill {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 8px;
  background: #fff4eb;
  color: #ff7900;
  font-size: 11px;
  line-height: 16px;
}
/* 悬浮操作（本工具附加能力，悬停时盖在卡片信息区上） */
.gf-hover-actions {
  position: absolute;
  inset: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-content: center;
  gap: 6px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.96);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}
.gf-item-card:hover .gf-hover-actions,
.gf-item-card:focus-within .gf-hover-actions {
  opacity: 1;
  pointer-events: auto;
}
.gf-hover-btn {
  width: 100%;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  border-radius: 8px;
  border: 1px solid #e5e6eb;
  background: #fff;
  color: #1a1a1a;
  font-size: 12.5px;
  cursor: pointer;
}
.gf-hover-btn.primary {
  background: #1a1a1a;
  border-color: #1a1a1a;
  color: #ffe60f;
  font-weight: 600;
}
.gf-hover-btn.yellow {
  background: #ffe60f;
  border-color: #ffe60f;
  font-weight: 600;
}
.gf-hover-btn.success:hover,
.gf-hover-btn.ghost:hover {
  border-color: #1a1a1a;
}
.gf-hover-link {
  text-decoration: none;
  display: block;
}
.detail-analysis-box {
  margin: 4px 0 16px;
  padding-top: 12px;
  border-top: 1px solid var(--xh-border, #ebeef5);
}

/* 列表模式 */
.list-card {
  border-radius: 10px;
}
.list-item-title-box {
  display: flex;
  align-items: center;
  gap: 10px;
}
.list-thumb {
  width: 50px;
  height: 50px;
  border-radius: 6px;
  flex-shrink: 0;
}
.list-item-info {
  min-width: 0;
}
.list-title {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.price-val {
  color: #f56c6c;
  font-weight: 700;
  font-size: 15px;
}

/* 抽屉详情 */
.detail-container {
  padding: 0 4px;
}
.carousel-wrap {
  border-radius: 10px;
  overflow: hidden;
  background: #f7f8fa;
  margin-bottom: 16px;
}
.carousel-img {
  width: 100%;
  height: 100%;
}
.carousel-img.single {
  height: 320px;
}
.detail-price-box {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.d-price {
  color: #f56c6c;
  font-size: 26px;
  font-weight: 700;
}
.d-orig {
  color: #909399;
  text-decoration: line-through;
  font-size: 14px;
}
.d-stats {
  margin-left: auto;
}
.detail-title {
  font-size: 17px;
  line-height: 1.5;
  margin: 0 0 16px;
}
.seller-card {
  border-radius: 10px;
  margin-bottom: 16px;
  background: #fafbfc;
}
.seller-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.s-name {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 4px;
}
.s-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.detail-desc-box h4 {
  margin: 0 0 10px;
  font-size: 15px;
}
.desc-content {
  font-size: 14px;
  line-height: 1.7;
  color: #4b4d52;
  white-space: pre-wrap;
  background: #f9f9fb;
  padding: 14px;
  border-radius: 8px;
}
.detail-drawer-footer {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}
.footer-btn-group {
  display: flex;
  gap: 12px;
}
.half-btn {
  flex: 1;
  text-decoration: none;
}
.full-btn {
  text-decoration: none;
  display: block;
}
.full {
  width: 100%;
}
.pagination-footer {
  margin-top: 24px;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
}
.page-indicator {
  font-size: 14px;
  color: var(--xh-muted);
}
.range {
  display: flex;
  align-items: center;
  gap: 8px;
}
.w90 {
  width: 90px;
}
.w100 {
  width: 100px;
}
.w110 {
  width: 110px;
}
.w120 {
  width: 120px;
}
.w140 {
  width: 140px;
}
.ml-s {
  margin-left: 6px;
}
.mt-s {
  margin-top: 8px;
}
.mb {
  margin-bottom: 16px;
}
.search-error-msg {
  font-size: 14px;
  line-height: 1.6;
}
.search-error-tip {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.65);
  border-radius: 6px;
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
}
.pacing-protect-pill {
  font-size: 12px;
  color: #10b981;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  padding: 2px 8px;
  border-radius: 12px;
  margin-right: 8px;
  user-select: none;
  display: inline-flex;
  align-items: center;
}
</style>
