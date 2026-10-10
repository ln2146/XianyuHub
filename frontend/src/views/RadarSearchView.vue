<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, Bell, Check, Clock, Close, Compass, Delete, Grid, List, MagicStick, Search, Upload } from '@element-plus/icons-vue'
import {
  createTask,
  emptyTask,
  liveSearch,
  QUICK_FILTERS,
  searchStatus,
  type SearchPage,
  type LiveSearchQuery,
  type SearchItem,
} from '@/api/buyer'
import { useAccountsStore } from '@/stores/accounts'
import { useKeepScroll } from '@/composables/useKeepScroll'
import ItemCard, { type CardItem, type CardMenuItem } from '@/components/ItemCard.vue'
import ItemDrawer, { type DrawerItem } from '@/components/ItemDrawer.vue'
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
// 个人闲置 / 包邮 用独立字段保存，转智能搜索时一并带上
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

// 闲鱼搜索卡片 → 统一商品卡片
function toCard(it: SearchItem): CardItem {
  const icons = it.icons || []
  const titleIcons = icons.filter((i) => i.row === 'r1')
  return {
    title: it.title,
    image: it.image_url,
    price: it.price,
    origPrice: it.orig_price,
    priceNote: it.price_note,
    wantCnt: it.want_cnt,
    attrs: it.attrs,
    titleIcons,
    serviceIcons: icons.filter((i) => i.row !== 'r1'),
    textBadges: !titleIcons.length && it.tags?.includes('包邮') ? ['包邮'] : [],
    area: it.area,
    sellerNick: it.seller_nick,
    avatar: it.avatar,
    sellerTag: it.seller_tags?.[0],
  }
}

const cardMenu: CardMenuItem[] = [
  { key: 'watch', label: '加入价格监控' },
  { key: 'resell', label: '转手发品' },
  { key: 'open', label: '去闲鱼查看', divided: true },
]

function onCardAction(it: SearchItem, key: string) {
  if (key === 'watch') watchPrice(it)
  else if (key === 'resell') quickResell(it)
  else if (key === 'open') window.open(safeItemLink(it), '_blank', 'noopener')
}

// 未搜索时的引导：分类热门词与技巧攻略
interface ExploreCategory {
  id: string
  name: string
  tagline: string
  icon: string
  color: 'blue' | 'amber' | 'emerald' | 'purple'
  items: { text: string; hot?: boolean }[]
}

const exploreCategories: ExploreCategory[] = [
  {
    id: 'digital',
    name: '数码极客',
    tagline: '高保值 · 捡漏高频',
    icon: '📱',
    color: 'blue',
    items: [
      { text: 'MacBook M1', hot: true },
      { text: 'iPhone 15' },
      { text: 'iPad Air' },
      { text: 'AirPods Pro', hot: true },
      { text: 'Apple Watch' },
      { text: 'ThinkPad' },
    ],
  },
  {
    id: 'gaming',
    name: '游戏电竞',
    tagline: '主机掌机 · 热门显卡',
    icon: '🎮',
    color: 'amber',
    items: [
      { text: 'Switch OLED', hot: true },
      { text: 'PS5' },
      { text: 'Steam Deck', hot: true },
      { text: '显卡 RTX' },
      { text: 'Xbox Series X' },
      { text: 'ROG 掌机' },
    ],
  },
  {
    id: 'camera',
    name: '摄影外设',
    tagline: '微单镜头 · 客制化外设',
    icon: '📷',
    color: 'emerald',
    items: [
      { text: '索尼微单', hot: true },
      { text: '佳能微单' },
      { text: '富士微单', hot: true },
      { text: '机械键盘' },
      { text: '戴森吹风机' },
      { text: '4K 显示器' },
    ],
  },
  {
    id: 'lifestyle',
    name: '潮流潮玩',
    tagline: '热销转手 · 溢价潜力',
    icon: '🛹',
    color: 'purple',
    items: [
      { text: '始祖鸟', hot: true },
      { text: '卡西欧' },
      { text: '乐高积木' },
      { text: '露营装备' },
      { text: '拍立得' },
      { text: '大疆无人机', hot: true },
    ],
  },
]

const radarTips = [
  {
    icon: '⚡',
    title: '最新发布捡漏',
    desc: '点击顶部「新发布」排序，毫秒级捕获卖家急售或标错价的一手好物。',
  },
  {
    icon: '📉',
    title: '追踪主动降价',
    desc: '切换「新降价」筛选，专门发现卖家主动调低价格、急于清仓的宝贝。',
  },
  {
    icon: '🛡️',
    title: '避坑验货认证',
    desc: '勾选「验货宝」或「个人闲置」，自动过滤非标转卖与批量引流号。',
  },
  {
    icon: '🎯',
    title: '一键监控转手',
    desc: '鼠标悬停结果即可一键「加入价格监控」或「一键转手到我的小店」。',
  },
]

// 搜索历史
const SEARCH_HISTORY_KEY = 'xh_radar_search_history'
const searchHistory = ref<string[]>([])

function loadSearchHistory() {
  try {
    const raw = localStorage.getItem(SEARCH_HISTORY_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        searchHistory.value = parsed.slice(0, 8)
      }
    }
  } catch {
    searchHistory.value = []
  }
}

function addSearchHistory(kw: string) {
  const clean = kw.trim()
  if (!clean) return
  const list = [clean, ...searchHistory.value.filter((k) => k !== clean)].slice(0, 8)
  searchHistory.value = list
  try {
    localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(list))
  } catch {
    // ignore
  }
}

function clearSearchHistory() {
  searchHistory.value = []
  try {
    localStorage.removeItem(SEARCH_HISTORY_KEY)
  } catch {
    // ignore
  }
}

// 搜索结果状态
const items = ref<SearchItem[]>([])
const loading = ref(false)
const searched = ref(false)
const hasMore = ref(false)
const searchError = ref('')

// 闲鱼限流后的暂停保护：显示真实剩余时间，到点再试
const cooldown = ref(0)
const needsVerify = ref(false)
// 「自动」通道：匿名受限时手动搜索改用的账号（来自状态接口），以及最近一次搜索实际用的通道
const fallbackAccount = ref<{ id: number; name: string } | null>(null)
const usedChannel = ref<SearchPage['channel'] | null>(null)
const fallbackName = computed(() =>
  usedChannel.value?.fallback ? usedChannel.value.name : searchForm.account_id === 0 ? fallbackAccount.value?.name : '',
)
let cooldownTimer: number | undefined
function startCooldown(seconds: number) {
  cooldown.value = Math.max(0, Math.round(seconds))
  window.clearInterval(cooldownTimer)
  if (cooldown.value > 0) {
    cooldownTimer = window.setInterval(() => {
      cooldown.value = Math.max(0, cooldown.value - 1)
      if (!cooldown.value) window.clearInterval(cooldownTimer)
    }, 1000)
  }
}
onBeforeUnmount(() => window.clearInterval(cooldownTimer))
const cooldownText = computed(() => {
  const m = Math.floor(cooldown.value / 60)
  const s = cooldown.value % 60
  return m ? `${m} 分 ${s} 秒` : `${s} 秒`
})
const channelAccountId = () => (searchForm.account_id > 0 ? searchForm.account_id : null)
async function refreshChannelStatus() {
  try {
    const st = await searchStatus(channelAccountId())
    needsVerify.value = st.needs_verify
    fallbackAccount.value = st.fallback_account
    startCooldown(st.cooldown_seconds)
  } catch {
    /* 静默 */
  }
}

let lastSearchTime = 0
let filterDebounceTimer: number | undefined

async function doSearch(page = 1) {
  const kw = searchForm.keyword.trim()
  if (!kw) {
    ElMessage.warning('请输入搜索关键词')
    return
  }
  addSearchHistory(kw)
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
      fallback: searchForm.account_id !== -1,
    })
    items.value = res.items || []
    usedChannel.value = res.channel || null
    if (res.channel?.fallback) refreshChannelStatus()
    hasMore.value = !!res.has_more
    // 顺便把参数同步到 URL，方便刷新与分享
    router.replace({ query: { q: kw, sort: searchForm.sort } })
  } catch (e: unknown) {
    items.value = []
    usedChannel.value = null
    const err = e as { response?: { data?: { detail?: string }; headers?: Record<string, string> }; message?: string }
    searchError.value = err.response?.data?.detail || err.message || '搜索失败，请稍后重试'
    const retry = Number(err.response?.headers?.['retry-after'] || 0)
    if (retry > 0) startCooldown(retry)
    if ([423, 429].includes((e as { response?: { status?: number } }).response?.status || 0)) refreshChannelStatus()
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
const detail = reactive({ open: false, item: null as SearchItem | null })

function openDetail(it: SearchItem) {
  Object.assign(detail, { open: true, item: it })
}

const drawerBase = computed<DrawerItem | null>(() => {
  const it = detail.item
  if (!it) return null
  return {
    title: it.title,
    image: it.image_url,
    images: it.images,
    price: it.price,
    origPrice: it.orig_price,
    wantCnt: it.want_cnt,
    area: it.area,
    sellerNick: it.seller_nick,
    desc: it.desc,
    link: it.link,
  }
})

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

// ---------------------------------------------------------------- 转为智能搜索
const taskModal = reactive({
  open: false,
  saving: false,
  form: emptyTask(),
})

function openCreateTask(fromItem?: SearchItem) {
  const kw = fromItem?.title || searchForm.keyword.trim() || '好货'
  const t = emptyTask()
  t.name = `${kw.slice(0, 16)}`
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
    ElMessage.success('已保存为智能搜索，结果在「智能搜索」页查看')
    taskModal.open = false
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(err.response?.data?.detail || '保存智能搜索失败')
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
  refreshChannelStatus()
  checkRouteQuery()
  loadSearchHistory()
})

onActivated(() => {
  refreshChannelStatus()
  checkRouteQuery()
})
</script>

<template>
  <div class="page radar-search">
    <RadarNav current="search">
      <template #actions>
        <el-button v-if="searchForm.keyword.trim()" :icon="MagicStick" @click="openCreateTask()">保存为智能搜索</el-button>
      </template>
    </RadarNav>

    <!-- 搜索与筛选：一张面板，布局对齐闲鱼网页版（排序 / 价格 / 区域 / 分页 + 快捷勾选） -->
    <section class="panel">
      <div class="search-row">
        <el-input
          v-model="searchForm.keyword"
          size="large"
          clearable
          :prefix-icon="Search"
          placeholder="搜索闲鱼商品，例如：iPhone 15、MacBook Air M1"
          @keyup.enter="doSearch(1)"
        />
        <el-button size="large" type="primary" :loading="loading" @click="doSearch(1)">搜索</el-button>
      </div>
      <div class="hot">
        <span class="hot-label">热门</span>
        <button v-for="kw in hotKeywords" :key="kw" type="button" class="hot-item" @click="onQuickSearch(kw)">{{ kw }}</button>
      </div>

      <div class="filter-row">
        <div class="sorts">
          <button type="button" class="sort" :class="{ on: searchForm.sort === 'default' }" @click="setSort('default')">综合</button>
          <button type="button" class="sort" :class="{ on: searchForm.sort === 'reduce' }" @click="setSort('reduce')">新降价</button>
          <el-dropdown trigger="hover" @command="setPublishDays">
            <button type="button" class="sort" :class="{ on: searchForm.sort === 'newest' }" @click="setSort('newest')">
              {{ publishLabel }}<el-icon class="caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="d in publishDayOptions" :key="d.value" :command="d.value">
                  <span :class="{ 'menu-on': searchForm.publish_days === d.value }">{{ d.label }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown trigger="hover" @command="setSort">
            <button type="button" class="sort" :class="{ on: searchForm.sort === 'price_asc' || searchForm.sort === 'price_desc' }">
              {{ priceSortLabel }}<el-icon class="caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="price_asc">价格从低到高</el-dropdown-item>
                <el-dropdown-item command="price_desc">价格从高到低</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <div class="price-range">
            <label class="price-input">
              <span>¥</span>
              <input v-model.number="searchForm.min_price" type="number" min="0" placeholder="最低" @keyup.enter="doSearch(1)" @change="debouncedFilterSearch" />
            </label>
            <span class="dash">–</span>
            <label class="price-input">
              <span>¥</span>
              <input v-model.number="searchForm.max_price" type="number" min="0" placeholder="最高" @keyup.enter="doSearch(1)" @change="debouncedFilterSearch" />
            </label>
          </div>
        </div>

        <div class="filter-right">
          <el-popover v-model:visible="region.open" placement="bottom-end" :width="440" trigger="click" popper-class="region-popper">
            <template #reference>
              <button type="button" class="sort" :class="{ on: !!searchForm.province }">
                {{ regionLabel }}<el-icon class="caret" :class="{ open: region.open }"><ArrowDown /></el-icon>
              </button>
            </template>
            <div class="region">
              <div class="region-head">
                <span>选择地区</span>
                <el-icon class="region-close" @click="region.open = false"><Close /></el-icon>
              </div>
              <div class="region-body">
                <div class="region-col left">
                  <div class="region-opt" :class="{ on: !region.province }" @click="pickProvince(null)">全国</div>
                  <div v-for="p in PROVINCES" :key="p.name" class="region-opt" :class="{ on: region.province === p.name }" @click="pickProvince(p.name)">
                    {{ p.name }}
                  </div>
                </div>
                <div class="region-col right">
                  <template v-if="regionProvince && regionProvince.cities.length">
                    <div class="region-opt" :class="{ on: searchForm.province === regionProvince.name && !searchForm.city }" @click="applyRegion(regionProvince.name, null)">
                      全{{ regionProvince.name }}
                      <el-icon v-if="searchForm.province === regionProvince.name && !searchForm.city"><Check /></el-icon>
                    </div>
                    <div v-for="c in regionProvince.cities" :key="c" class="region-opt" :class="{ on: searchForm.city === c }" @click="applyRegion(regionProvince.name, c)">
                      {{ c }}<el-icon v-if="searchForm.city === c"><Check /></el-icon>
                    </div>
                  </template>
                  <div v-else class="region-opt on">{{ searchForm.province || '全国' }}<el-icon><Check /></el-icon></div>
                </div>
              </div>
            </div>
          </el-popover>
          <div class="pager">
            <button type="button" class="page-arrow" :disabled="(searchForm.page || 1) <= 1" aria-label="上一页" @click="doSearch((searchForm.page || 1) - 1)">‹</button>
            <span class="page-text">{{ searchForm.page || 1 }}/50</span>
            <button type="button" class="page-arrow" :disabled="!hasMore" aria-label="下一页" @click="doSearch((searchForm.page || 1) + 1)">›</button>
          </div>
        </div>
      </div>

      <div class="check-row">
        <label v-for="f in QUICK_FILTERS" :key="f.key" class="check" :class="{ on: isQuickOn(f.key) }">
          <input type="checkbox" :checked="isQuickOn(f.key)" @change="toggleQuick(f.key)" />
          <span class="check-box"><el-icon v-if="isQuickOn(f.key)"><Check /></el-icon></span>
          <span>{{ f.label }}</span>
        </label>
        <button type="button" class="reset" @click="resetFilters">重置筛选</button>
      </div>
    </section>

    <!-- 结果 -->
    <div v-loading="loading" class="results">
      <el-alert v-if="needsVerify" type="error" show-icon :closable="false" class="cooldown">
        <template #title>闲鱼要求该账号完成安全验证，验证前这个账号无法搜索</template>
        <div class="error-tip">
          到「账号配置」点该账号的「打开验证页面」，在闲鱼完成滑块 / 安全验证后点「我已完成验证」。也可以先把「请求通道」切回匿名通道。
        </div>
      </el-alert>
      <!-- 「自动」通道下匿名受限会静默改用账号，只有确实没法搜时才提示 -->
      <el-alert v-else-if="cooldown > 0 && !fallbackName" type="warning" show-icon :closable="false" class="cooldown">
        <template #title>闲鱼临时限制了{{ searchForm.account_id > 0 ? '该账号' : '匿名通道' }}的搜索，{{ cooldownText }}后可以再试</template>
        <div class="error-tip">
          这是闲鱼的频率保护，系统已自动暂停这个通道，到点后再搜即可；连续被限制时暂停时间会逐步加长。
          如果到点后仍被限制，说明闲鱼限制的是你当前网络的 IP，可以换个网络（如手机热点）或在「账号配置」绑定闲鱼账号后用账号搜索。
        </div>
      </el-alert>
      <el-alert v-else-if="searchError" type="error" show-icon :closable="false">
        <template #title>搜索遇到问题</template>
        <div>{{ searchError }}</div>
        <el-button size="small" class="retry" :loading="loading" @click="doSearch(searchForm.page || 1)">重试</el-button>
      </el-alert>

      <div v-if="searched && !searchError" class="results-bar">
        <span class="count">找到 <b>{{ items.length }}</b> 件商品<span class="muted"> · 第 {{ searchForm.page || 1 }} 页</span></span>
        <div class="tools">
          <el-tooltip content="两次搜索之间自动保持温和节奏，降低触发闲鱼频控的概率">
            <span class="pacing">智能控频</span>
          </el-tooltip>
          <el-select v-model="searchForm.account_id" size="small" class="channel" @change="refreshChannelStatus(); debouncedFilterSearch()">
            <el-option :value="0" label="请求通道：自动（匿名优先，受限时用账号）" />
            <el-option :value="-1" label="请求通道：仅匿名" />
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="`请求通道：${a.nickname || a.remark || a.unb}`" />
          </el-select>
          <el-button-group size="small">
            <el-button :type="viewMode === 'grid' ? 'primary' : 'default'" :icon="Grid" aria-label="网格视图" @click="viewMode = 'grid'" />
            <el-button :type="viewMode === 'list' ? 'primary' : 'default'" :icon="List" aria-label="列表视图" @click="viewMode = 'list'" />
          </el-button-group>
        </div>
      </div>

      <div v-if="!searched && !loading" class="radar-welcome">
        <!-- 头部 Hero 区域：发光雷达与价值主张 -->
        <div class="welcome-hero">
          <div class="hero-radar-badge">
            <span class="radar-ripple ring-1"></span>
            <span class="radar-ripple ring-2"></span>
            <div class="radar-icon-box">
              <el-icon :size="30"><Compass /></el-icon>
            </div>
          </div>
          <h2 class="welcome-heading">闲鱼全网货源 · 实时精准捕获</h2>
          <p class="welcome-tagline">
            输入关键词即刻直连闲鱼底层检索链路，毫秒级扫描最新在售、降价急售与高保值好货
          </p>
          <div class="welcome-features">
            <span class="feat-pill"><span class="feat-dot dot-emerald"></span>官方链路直连</span>
            <span class="feat-pill"><span class="feat-dot dot-blue"></span>毫秒级上架捕获</span>
            <span class="feat-pill"><span class="feat-dot dot-amber"></span>智能防限流控频</span>
            <span class="feat-pill"><span class="feat-dot dot-purple"></span>一键转手 & 监控</span>
          </div>
        </div>

        <!-- 最近搜索历史 (若存在) -->
        <div v-if="searchHistory.length" class="history-bar">
          <div class="history-label">
            <el-icon class="history-icon"><Clock /></el-icon>
            <span>最近搜索：</span>
          </div>
          <div class="history-tags">
            <button
              v-for="kw in searchHistory"
              :key="kw"
              type="button"
              class="history-chip"
              @click="onQuickSearch(kw)"
            >
              {{ kw }}
            </button>
            <button type="button" class="history-clear-btn" title="清空搜索历史" @click="clearSearchHistory">
              <el-icon><Delete /></el-icon>
              <span>清空</span>
            </button>
          </div>
        </div>

        <!-- 热门分类探索卡片网格 -->
        <div class="explore-section">
          <div class="section-title-wrap">
            <span class="section-badge">HOT CATEGORIES</span>
            <h3 class="section-title">热门选品与高流转类目</h3>
          </div>
          <div class="explore-grid">
            <div
              v-for="cat in exploreCategories"
              :key="cat.id"
              class="explore-card"
              :class="`theme-${cat.color}`"
            >
              <div class="card-head">
                <span class="cat-icon-badge">{{ cat.icon }}</span>
                <div class="cat-title-wrap">
                  <div class="cat-name">{{ cat.name }}</div>
                  <div class="cat-tagline">{{ cat.tagline }}</div>
                </div>
              </div>
              <div class="card-chips">
                <button
                  v-for="item in cat.items"
                  :key="item.text"
                  type="button"
                  class="keyword-chip"
                  :class="{ hot: item.hot }"
                  @click="onQuickSearch(item.text)"
                >
                  <span class="chip-text">{{ item.text }}</span>
                  <span v-if="item.hot" class="chip-hot-tag" title="热搜">HOT</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 选品捡漏技巧攻略卡片 -->
        <div class="pro-tips-section">
          <div class="section-title-wrap">
            <span class="section-badge tips">PRO TIPS</span>
            <h3 class="section-title">选品雷达高效捡漏秘籍</h3>
          </div>
          <div class="tips-grid">
            <div v-for="(tip, idx) in radarTips" :key="idx" class="tip-card">
              <div class="tip-icon-box">{{ tip.icon }}</div>
              <div class="tip-body">
                <div class="tip-title">{{ tip.title }}</div>
                <div class="tip-desc">{{ tip.desc }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <el-empty v-else-if="searched && !loading && !items.length && !searchError" description="暂无符合条件的商品" :image-size="80">
        <el-button @click="resetFilters">重置筛选</el-button>
      </el-empty>

      <div v-else-if="viewMode === 'grid'" class="grid">
        <ItemCard
          v-for="it in items"
          :key="it.item_id"
          :item="toCard(it)"
          :menu="cardMenu"
          @open="openDetail(it)"
          @action="(k: string) => onCardAction(it, k)"
        />
      </div>

      <el-card v-else-if="viewMode === 'list'" shadow="never" class="list-card">
        <el-table :data="items" @row-click="(row: SearchItem) => openDetail(row)">
          <el-table-column label="商品" min-width="320">
            <template #default="{ row }">
              <div class="list-item">
                <el-image :src="row.image_url" fit="cover" class="list-thumb" lazy referrerpolicy="no-referrer" />
                <div class="list-info">
                  <div class="list-title">{{ row.title }}</div>
                  <div class="muted small">
                    {{ [row.area, row.want_cnt ? `${row.want_cnt}人想要` : '', ...(row.attrs || []).slice(0, 2)].filter(Boolean).join(' · ') }}
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="价格" width="120">
            <template #default="{ row }">
              <span class="list-price">{{ fmtMoney(row.price) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="卖家" min-width="120">
            <template #default="{ row }">
              <span class="small">{{ row.seller_nick || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="发布" width="110">
            <template #default="{ row }">
              <span class="muted small">{{ fmtRelative(row.publish_time) || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <div @click.stop>
                <el-button size="small" link type="primary" @click="openDetail(row as SearchItem)">详情</el-button>
                <el-button size="small" link :icon="Bell" @click="watchPrice(row as SearchItem)">监控</el-button>
                <el-button size="small" link :icon="Upload" @click="quickResell(row as SearchItem)">转手</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <div v-if="searched && items.length" class="pagination">
        <el-button :disabled="(searchForm.page || 1) <= 1" @click="doSearch((searchForm.page || 1) - 1)">上一页</el-button>
        <span class="muted">第 {{ searchForm.page || 1 }} 页</span>
        <el-button :disabled="!hasMore" @click="doSearch((searchForm.page || 1) + 1)">下一页</el-button>
      </div>
    </div>

    <ItemDrawer
      v-model="detail.open"
      :item-id="detail.item?.item_id || ''"
      :base="drawerBase"
      fetch-detail
      :keyword="searchForm.keyword"
      :account-id="searchForm.account_id > 0 ? searchForm.account_id : null"
    >
      <template #actions>
        <el-button v-if="detail.item" :icon="Bell" @click="watchPrice(detail.item)">加入价格监控</el-button>
        <el-button v-if="detail.item" :icon="Upload" @click="quickResell(detail.item)">转手发品</el-button>
      </template>
    </ItemDrawer>

    <el-dialog v-model="taskModal.open" title="保存为智能搜索" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="taskModal.form.name" placeholder="例如：M1 Air 笔记本" />
        </el-form-item>
        <el-form-item label="搜索关键词" required>
          <el-input
            :model-value="taskModal.form.keywords.join(' ')"
            placeholder="多个关键词用空格隔开"
            @update:model-value="(v: string) => (taskModal.form.keywords = v.split(/\s+/).filter(Boolean))"
          />
          <div class="form-tip">系统会按这些关键词定期搜索闲鱼新上架的商品。</div>
        </el-form-item>
        <el-form-item label="价格区间">
          <div class="range">
            <el-input-number v-model="taskModal.form.min_price" placeholder="最低" :controls="false" class="w120" />
            <span>至</span>
            <el-input-number v-model="taskModal.form.max_price" placeholder="最高" :controls="false" class="w120" />
          </div>
        </el-form-item>
        <el-form-item label="搜索频率">
          <el-select v-model="taskModal.form.cron" class="full">
            <el-option value="*/30 8-23 * * *" label="每 30 分钟（推荐，风控压力低）" />
            <el-option value="*/10 8-23 * * *" label="每 10 分钟（白天，急着捡漏）" />
            <el-option value="0 * * * *" label="每小时" />
            <el-option value="0 */2 * * *" label="每 2 小时" />
            <el-option value="0 9,21 * * *" label="每天早晚 9 点" />
          </el-select>
        </el-form-item>
        <el-form-item label="筛选条件">
          <el-checkbox v-model="taskModal.form.personal_only" label="仅看个人闲置" />
          <el-checkbox v-model="taskModal.form.free_shipping" label="仅看包邮" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="taskModal.open = false">取消</el-button>
        <el-button type="primary" :loading="taskModal.saving" @click="saveTask">保存并开始搜索</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.radar-search {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
}

/* ---------------- 搜索与筛选面板 */
.panel {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
  padding: var(--xh-space-4);
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
}
.search-row {
  display: flex;
  gap: var(--xh-space-2);
}
.search-row .el-button {
  min-width: 96px;
}
.hot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--xh-space-1) var(--xh-space-3);
  margin-top: -4px;
  font-size: var(--xh-fs-xs);
}
.hot-label {
  color: var(--xh-muted);
}
.hot-item {
  padding: 0;
  border: none;
  background: none;
  color: var(--xh-text-2);
  font-size: var(--xh-fs-xs);
  cursor: pointer;
}
.hot-item:hover {
  color: var(--xh-primary);
}
.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
  padding-top: var(--xh-space-3);
  border-top: 1px solid var(--xh-border);
}
.sorts,
.filter-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--xh-space-1);
}
.filter-right {
  gap: var(--xh-space-3);
}
.sort {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 32px;
  padding: 0 var(--xh-space-3);
  border: none;
  border-radius: var(--xh-radius-sm);
  background: transparent;
  color: var(--xh-text);
  font-size: var(--xh-fs-md);
  font-weight: 500;
  cursor: pointer;
  outline: none;
}
.sort:hover {
  background: var(--xh-fill);
}
.sort.on {
  background: var(--xh-primary-soft);
  color: var(--xh-primary);
  font-weight: 600;
}
.sort:focus-visible {
  outline: 2px solid var(--xh-primary);
}
.caret {
  font-size: var(--xh-fs-xs);
  margin-left: 2px;
  transition: transform 0.15s;
}
.caret.open {
  transform: rotate(180deg);
}
:global(.menu-on) {
  color: var(--xh-primary);
  font-weight: 600;
}
.price-range {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: var(--xh-space-2);
}
.price-input {
  display: flex;
  align-items: center;
  gap: var(--xh-space-1);
  width: 100px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  color: var(--xh-muted);
  font-size: var(--xh-fs-sm);
}
.price-input:focus-within {
  border-color: var(--xh-primary);
}
.price-input input {
  width: 100%;
  min-width: 0;
  border: none;
  outline: none;
  color: var(--xh-text);
  font-size: var(--xh-fs-sm);
  -moz-appearance: textfield;
}
.price-input input::-webkit-outer-spin-button,
.price-input input::-webkit-inner-spin-button {
  -webkit-appearance: none;
}
.dash {
  color: var(--xh-disabled);
}
.pager {
  display: flex;
  align-items: center;
  gap: 6px;
}
.page-arrow {
  width: 30px;
  height: 30px;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  background: var(--xh-card);
  color: var(--xh-text);
  font-size: var(--xh-fs-lg);
  line-height: 1;
  cursor: pointer;
}
.page-arrow:hover:not(:disabled) {
  border-color: var(--xh-primary);
  color: var(--xh-primary);
}
.page-arrow:disabled {
  color: var(--xh-disabled);
  cursor: not-allowed;
}
.page-text {
  min-width: 36px;
  text-align: center;
  font-size: var(--xh-fs-sm);
}
.check-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--xh-space-2) var(--xh-space-5);
  padding: 0 var(--xh-space-3);
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text);
  cursor: pointer;
  user-select: none;
}
.check input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.check-box {
  width: 16px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--xh-border-strong);
  border-radius: 4px;
  font-size: var(--xh-fs-xs);
  color: #fff;
  transition: all 0.15s;
}
.check:hover .check-box {
  border-color: var(--xh-primary);
}
.check.on .check-box {
  background: var(--xh-primary);
  border-color: var(--xh-primary);
}
.check input:focus-visible + .check-box {
  outline: 2px solid var(--xh-primary);
  outline-offset: 2px;
}
.reset {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--xh-muted);
  font-size: var(--xh-fs-xs);
  cursor: pointer;
}
.reset:hover {
  color: var(--xh-primary);
}

/* 区域弹层 */
:global(.region-popper.el-popover) {
  padding: 0 !important;
  border-radius: var(--xh-radius-md) !important;
  overflow: hidden;
}
.region-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--xh-space-3) var(--xh-space-4);
  border-bottom: 1px solid var(--xh-border);
  font-weight: 600;
}
.region-close {
  cursor: pointer;
  color: var(--xh-muted);
}
.region-body {
  display: grid;
  grid-template-columns: 112px 1fr;
  height: 320px;
}
.region-col {
  overflow-y: auto;
  padding: 6px 0;
}
.region-col.left {
  background: var(--xh-fill);
}
.region-col.right {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  align-content: start;
  padding: 6px var(--xh-space-2);
}
.region-opt {
  display: flex;
  align-items: center;
  gap: var(--xh-space-1);
  padding: 8px var(--xh-space-4);
  font-size: var(--xh-fs-sm);
  color: var(--xh-text);
  cursor: pointer;
}
.region-col.right .region-opt {
  padding: 8px 10px;
}
.region-opt:hover,
.region-opt.on {
  color: var(--xh-primary);
}
.region-col.left .region-opt.on {
  background: var(--xh-card);
  font-weight: 600;
}

/* ---------------- 结果 */
.results {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
  min-height: 240px;
}
.cooldown {
  background: var(--xh-fill) !important;
  border: 1px solid var(--xh-border) !important;
  border-radius: var(--xh-radius-md) !important;
  padding: 10px 14px !important;
}
.cooldown.el-alert--info {
  background: #f0f9ff !important;
  border-color: #bae6fd !important;
}
.cooldown.el-alert--warning {
  background: #fffbeb !important;
  border-color: #fde68a !important;
}
.cooldown.el-alert--error {
  background: #fef2f2 !important;
  border-color: #fecaca !important;
}
.cooldown :deep(.el-alert__title) {
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
}
.cooldown :deep(.el-alert__description) {
  margin: 4px 0 0;
  color: var(--xh-text-2);
}
.error-tip {
  margin-top: 4px;
  font-size: var(--xh-fs-xs);
  line-height: 1.6;
}
.retry {
  margin-top: var(--xh-space-2);
}
.results-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
}
.count b {
  color: var(--xh-primary);
}
.tools {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}
.pacing {
  font-size: var(--xh-fs-xs);
  color: var(--xh-primary);
  cursor: help;
}
.channel {
  width: 260px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: var(--xh-space-4);
}
/* ==================== 选品雷达初始欢迎页 ==================== */
.radar-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--xh-space-5);
  padding: 36px var(--xh-space-4) 48px;
  max-width: 1120px;
  margin: 0 auto;
}

/* 头部 Hero 区域 */
.welcome-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  max-width: 640px;
}

.hero-radar-badge {
  position: relative;
  width: 68px;
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--xh-space-3);
}

.radar-icon-box {
  width: 52px;
  height: 52px;
  border-radius: var(--xh-radius-lg);
  background: linear-gradient(135deg, var(--xh-primary-soft) 0%, #d8f3e5 100%);
  border: 1px solid var(--xh-primary-border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--xh-primary);
  box-shadow: 0 4px 12px rgba(30, 158, 106, 0.15);
  z-index: 2;
  transition: transform 0.3s ease;
}

.hero-radar-badge:hover .radar-icon-box {
  transform: scale(1.06) rotate(6deg);
}

.radar-ripple {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 52px;
  height: 52px;
  border-radius: var(--xh-radius-lg);
  border: 1.5px solid var(--xh-primary);
  transform: translate(-50%, -50%);
  opacity: 0;
  pointer-events: none;
  animation: radarWave 2.8s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;
}

.radar-ripple.ring-2 {
  animation-delay: 1.4s;
}

@keyframes radarWave {
  0% {
    width: 50px;
    height: 50px;
    opacity: 0.6;
    border-radius: var(--xh-radius-lg);
  }
  100% {
    width: 88px;
    height: 88px;
    opacity: 0;
    border-radius: 24px;
  }
}

.welcome-heading {
  margin: 0 0 var(--xh-space-2);
  font-size: var(--xh-fs-xl);
  font-weight: 700;
  color: var(--xh-text);
  letter-spacing: -0.01em;
}

.welcome-tagline {
  margin: 0 0 var(--xh-space-3);
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  line-height: 1.5;
}

.welcome-features {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--xh-space-2);
}

.feat-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-pill);
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
  font-weight: 500;
  box-shadow: var(--xh-shadow-1);
}

.feat-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.feat-dot.dot-emerald { background: #1e9e6a; }
.feat-dot.dot-blue { background: #3b82f6; }
.feat-dot.dot-amber { background: #f59e0b; }
.feat-dot.dot-purple { background: #8b5cf6; }

/* 搜索历史条 */
.history-bar {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--xh-space-2);
  padding: 10px 16px;
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  box-shadow: var(--xh-shadow-1);
}

.history-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  white-space: nowrap;
}

.history-icon {
  font-size: 14px;
}

.history-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
  flex: 1;
}

.history-chip {
  padding: 2px 10px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
}

.history-chip:hover {
  color: var(--xh-primary);
  border-color: var(--xh-primary-border);
  background: var(--xh-primary-soft);
}

.history-clear-btn {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
  padding: 2px 6px;
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  border-radius: var(--xh-radius-sm);
  transition: color 0.2s;
}

.history-clear-btn:hover {
  color: var(--xh-danger);
}

/* 分类卡片区域 */
.explore-section {
  width: 100%;
}

.section-title-wrap {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  margin-bottom: var(--xh-space-3);
}

.section-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  background: rgba(30, 158, 106, 0.1);
  color: var(--xh-primary);
  border-radius: 4px;
  letter-spacing: 0.05em;
}

.section-badge.tips {
  background: rgba(59, 130, 246, 0.1);
  color: #2563eb;
}

.section-title {
  margin: 0;
  font-size: var(--xh-fs-md);
  font-weight: 600;
  color: var(--xh-text);
}

.explore-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--xh-space-4);
}

.explore-card {
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  padding: 18px;
  box-shadow: var(--xh-shadow-1);
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
  overflow: hidden;
}

.explore-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: transparent;
  transition: background 0.25s ease;
}

.explore-card.theme-blue:hover::before { background: #3b82f6; }
.explore-card.theme-amber:hover::before { background: #f59e0b; }
.explore-card.theme-emerald:hover::before { background: #1e9e6a; }
.explore-card.theme-purple:hover::before { background: #8b5cf6; }

.explore-card:hover {
  transform: translateY(-3px);
  border-color: var(--xh-border-strong);
  box-shadow: var(--xh-shadow-2);
}

.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cat-icon-badge {
  font-size: 24px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill);
}

.cat-name {
  font-size: var(--xh-fs-md);
  font-weight: 600;
  color: var(--xh-text);
}

.cat-tagline {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  margin-top: 1px;
}

.card-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.keyword-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border-radius: var(--xh-radius-pill);
  background: var(--xh-fill);
  border: 1px solid var(--xh-border);
  color: var(--xh-text-2);
  font-size: var(--xh-fs-sm);
  cursor: pointer;
  transition: all 0.2s ease;
  line-height: 1.2;
}

.keyword-chip:hover {
  background: var(--xh-primary-soft);
  border-color: var(--xh-primary-border);
  color: var(--xh-primary);
  transform: translateY(-1px);
}

.chip-hot-tag {
  font-size: 9px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #ff5722, #f44336);
  padding: 1px 4px;
  border-radius: 4px;
  line-height: 1;
}

/* 选品攻略卡片区域 */
.pro-tips-section {
  width: 100%;
}

.tips-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--xh-space-3);
}

.tip-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: var(--xh-card);
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
  box-shadow: var(--xh-shadow-1);
  transition: all 0.2s ease;
}

.tip-card:hover {
  background: var(--xh-fill);
  border-color: var(--xh-border-strong);
}

.tip-icon-box {
  font-size: 20px;
  line-height: 1;
  flex-shrink: 0;
  margin-top: 1px;
}

.tip-title {
  font-size: var(--xh-fs-sm);
  font-weight: 600;
  color: var(--xh-text);
  margin-bottom: 3px;
}

.tip-desc {
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
  line-height: 1.45;
}
.list-item {
  display: flex;
  align-items: center;
  gap: var(--xh-space-3);
}
.list-thumb {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  border-radius: var(--xh-radius-sm);
}
.list-info {
  min-width: 0;
}
.list-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--xh-text);
}
.list-price {
  color: var(--xh-price);
  font-weight: 600;
}
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--xh-space-4);
  margin-top: var(--xh-space-2);
}
.range {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}
.w120 {
  width: 120px;
}
.full {
  width: 100%;
}
@media (max-width: 768px) {
  .price-range {
    margin-left: 0;
  }
  .channel {
    width: 150px;
  }
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--xh-space-2);
  }
}
</style>
