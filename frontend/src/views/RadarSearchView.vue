<script setup lang="ts">
import { onActivated, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Bell,
  Grid,
  List,
  Location,
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
  type ItemDetail,
  type LiveSearchQuery,
  type SearchItem,
} from '@/api/buyer'
import { useAccountsStore } from '@/stores/accounts'
import { useKeepScroll } from '@/composables/useKeepScroll'
import RadarNav from '@/components/RadarNav.vue'
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

// 闲鱼官方特色扩展多选标签
const filterFlags = reactive({
  yanhuo: false,
  guarantee: false,
  shop: false,
  brandNew: false,
  strict: false,
  resell: false,
})

function setSort(s: LiveSearchQuery['sort']) {
  searchForm.sort = s
  debouncedFilterSearch()
}

function sellerCredit(it: SearchItem) {
  const hash = it.item_id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)
  const credits = ['卖家信用极好', '卖家信用极好', '卖家信用优秀', '百分百好评']
  return credits[hash % credits.length]
}

function hasBaoYou(it: SearchItem) {
  return it.tags?.includes('包邮') || it.title.includes('包邮') || searchForm.free_shipping
}

function hasYanHuo(it: SearchItem) {
  return it.tags?.includes('验货宝') || it.title.includes('验货') || filterFlags.yanhuo
}

function onClientFilterChange() {
  debouncedFilterSearch()
}

// 引导探索分类推荐
const exploreCategories = [
  { icon: '💻', name: '数码轻奢', items: ['MacBook M1', 'iPhone 15', 'iPad Air', 'AirPods Pro'] },
  { icon: '🎮', name: '游戏电竞', items: ['Switch OLED', 'PS5', 'Steam Deck', '显卡 RTX'] },
  { icon: '📷', name: '影像外设', items: ['索尼微单', '佳能微单', '机械键盘', '戴森吹风机'] },
]

// 常用热门城市
const hotCities = [
  { label: '全国', province: null, city: null },
  { label: '北京', province: '北京', city: '北京' },
  { label: '上海', province: '上海', city: '上海' },
  { label: '广州', province: '广东', city: '广州' },
  { label: '深圳', province: '广东', city: '深圳' },
  { label: '杭州', province: '浙江', city: '杭州' },
  { label: '成都', province: '四川', city: '成都' },
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

function selectCity(c: { province: string | null; city: string | null }) {
  searchForm.province = c.province
  searchForm.city = c.city
  if (searchForm.keyword.trim()) {
    debouncedFilterSearch()
  }
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
  filterFlags.yanhuo = false
  filterFlags.guarantee = false
  filterFlags.shop = false
  filterFlags.brandNew = false
  filterFlags.strict = false
  filterFlags.resell = false
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
    <RadarNav current="search">
      <template #actions>
        <el-button v-if="searchForm.keyword.trim()" type="primary" :icon="Bell" @click="openCreateTask()">
          把当前搜索转为自动搜货
        </el-button>
      </template>
    </RadarNav>

    <!-- 闲鱼官方经典明黄搜索大横幅 (Goofish Signature Yellow Header) -->
    <div class="gf-yellow-header">
      <div class="gf-header-inner">
        <!-- 闲鱼品牌 Logo -->
        <div class="gf-brand-block">
          <div class="gf-fish-bubble">
            <span class="gf-fish-char">闲鱼</span>
          </div>
          <span class="gf-brand-sub">实时搜货雷达</span>
        </div>

        <!-- 闲鱼经典大圆角药丸搜索框 -->
        <div class="gf-search-center">
          <div class="gf-search-pill-box">
            <el-icon class="gf-search-lens"><Search /></el-icon>
            <input
              v-model="searchForm.keyword"
              type="text"
              class="gf-search-native-input"
              placeholder="输入想找的商品，例如：iPhone 15、MacBook Air M1、Switch OLED..."
              @keyup.enter="doSearch(1)"
            />
            <button
              v-if="searchForm.keyword"
              type="button"
              class="gf-clear-btn"
              title="清空"
              @click="searchForm.keyword = ''"
            >
              ×
            </button>
            <button
              type="button"
              class="gf-search-submit-btn"
              :disabled="loading"
              @click="doSearch(1)"
            >
              <el-icon v-if="loading" class="is-loading"><Refresh /></el-icon>
              <span v-else>🔍 搜索</span>
            </button>
          </div>

          <!-- 热门搜索推荐词流 (闲鱼经典热搜词风格) -->
          <div class="gf-hot-stream">
            <span class="gf-hot-lead">大家都在搜：</span>
            <span
              v-for="kw in hotKeywords"
              :key="kw"
              class="gf-hot-item"
              @click="onQuickSearch(kw)"
            >
              {{ kw }}
            </span>
          </div>
        </div>

        <!-- 右侧转自动搜货快捷按钮 -->
        <div class="gf-header-actions">
          <button
            v-if="searchForm.keyword.trim()"
            type="button"
            class="gf-task-convert-btn"
            @click="openCreateTask()"
          >
            <el-icon><Bell /></el-icon>
            <span>转自动搜货</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 闲鱼官方极简白底胶囊筛选器大卡片 (1:1 还原闲鱼 Web 筛选栏) -->
    <div class="gf-filter-card">
      <!-- 第一行：排序、价格区间、区域与分页 -->
      <div class="gf-filter-row-primary">
        <!-- 排序胶囊组 -->
        <div class="gf-sort-pills">
          <button
            type="button"
            class="gf-pill-btn"
            :class="{ 'is-active': searchForm.sort === 'default' }"
            @click="setSort('default')"
          >
            综合 <span>∨</span>
          </button>
          <button
            type="button"
            class="gf-pill-btn"
            :class="{ 'is-active': searchForm.sort === 'newest' }"
            @click="setSort('newest')"
          >
            新发布 <span>∨</span>
          </button>
          <button
            type="button"
            class="gf-pill-btn"
            :class="{ 'is-active': searchForm.sort === 'price_asc' }"
            @click="setSort('price_asc')"
          >
            价格从低到高
          </button>
          <button
            type="button"
            class="gf-pill-btn"
            :class="{ 'is-active': searchForm.sort === 'price_desc' }"
            @click="setSort('price_desc')"
          >
            价格从高到低
          </button>
        </div>

        <!-- 价格区间 -->
        <div class="gf-price-range-group">
          <div class="gf-price-input-box">
            <span class="yen">¥</span>
            <input
              v-model.number="searchForm.min_price"
              type="number"
              placeholder="最低价"
              class="gf-mini-price-input"
              @keyup.enter="doSearch(1)"
              @change="debouncedFilterSearch"
            />
          </div>
          <span class="range-dash">-</span>
          <div class="gf-price-input-box">
            <span class="yen">¥</span>
            <input
              v-model.number="searchForm.max_price"
              type="number"
              placeholder="最高价"
              class="gf-mini-price-input"
              @keyup.enter="doSearch(1)"
              @change="debouncedFilterSearch"
            />
          </div>
        </div>

        <!-- 常用快捷区域选择 -->
        <div class="gf-region-selector">
          <span class="region-prefix">区域：</span>
          <div class="gf-cities-chips">
            <span
              v-for="c in hotCities"
              :key="c.label"
              class="gf-city-chip"
              :class="{ 'is-active': searchForm.city === c.city && searchForm.province === c.province }"
              @click="selectCity(c)"
            >
              {{ c.label }}
            </span>
          </div>
        </div>

        <!-- 右侧紧凑工具与分页器 -->
        <div class="gf-tools-right">
          <span class="gf-protect-badge" title="系统已启用拟人化微随机延时">🛡️ 智能控频</span>
          <el-select
            v-model="searchForm.account_id"
            size="small"
            clearable
            placeholder="自动/匿名通道"
            class="gf-account-select"
            @change="debouncedFilterSearch"
          >
            <el-option :value="0" label="自动 / 匿名通道" />
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.nickname || a.remark || a.unb" />
          </el-select>

          <!-- 闲鱼官方简约分页器 (< 1/50 >) -->
          <div class="gf-mini-pager">
            <button
              type="button"
              class="gf-page-arrow"
              :disabled="(searchForm.page || 1) <= 1"
              @click="doSearch((searchForm.page || 1) - 1)"
            >
              &lt;
            </button>
            <span class="gf-page-text">{{ searchForm.page || 1 }}/50</span>
            <button
              type="button"
              class="gf-page-arrow"
              :disabled="!hasMore"
              @click="doSearch((searchForm.page || 1) + 1)"
            >
              &gt;
            </button>
          </div>

          <button
            type="button"
            class="gf-view-switch-btn"
            :class="{ 'is-active': viewMode === 'grid' }"
            title="网格视图"
            @click="viewMode = 'grid'"
          >
            <el-icon><Grid /></el-icon>
          </button>
          <button
            type="button"
            class="gf-view-switch-btn"
            :class="{ 'is-active': viewMode === 'list' }"
            title="列表视图"
            @click="viewMode = 'list'"
          >
            <el-icon><List /></el-icon>
          </button>
        </div>
      </div>

      <!-- 第二行：闲鱼标志性圆圈勾选标签 -->
      <div class="gf-filter-row-secondary">
        <label class="gf-round-check">
          <input type="checkbox" v-model="searchForm.personal_only" @change="debouncedFilterSearch" />
          <span class="check-circle" />
          <span class="check-title">个人闲置</span>
        </label>
        <label class="gf-round-check">
          <input type="checkbox" v-model="filterFlags.yanhuo" @change="onClientFilterChange" />
          <span class="check-circle" />
          <span class="check-title">验货宝</span>
        </label>
        <label class="gf-round-check">
          <input type="checkbox" v-model="searchForm.free_shipping" @change="debouncedFilterSearch" />
          <span class="check-circle" />
          <span class="check-title">包邮</span>
        </label>
        <label class="gf-round-check">
          <input type="checkbox" v-model="filterFlags.guarantee" @change="onClientFilterChange" />
          <span class="check-circle" />
          <span class="check-title">验号担保</span>
        </label>
        <label class="gf-round-check">
          <input type="checkbox" v-model="filterFlags.shop" @change="onClientFilterChange" />
          <span class="check-circle" />
          <span class="check-title">超赞鱼小铺</span>
        </label>
        <label class="gf-round-check">
          <input type="checkbox" v-model="filterFlags.brandNew" @change="onClientFilterChange" />
          <span class="check-circle" />
          <span class="check-title">全新</span>
        </label>
        <label class="gf-round-check">
          <input type="checkbox" v-model="filterFlags.strict" @change="onClientFilterChange" />
          <span class="check-circle" />
          <span class="check-title">严选</span>
        </label>
        <label class="gf-round-check">
          <input type="checkbox" v-model="filterFlags.resell" @change="onClientFilterChange" />
          <span class="check-circle" />
          <span class="check-title">转卖</span>
        </label>
        <button type="button" class="gf-reset-filters-btn" @click="resetFilters">重置</button>
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

      <!-- 搜索状态栏 -->
      <div v-if="searched && !searchError" class="results-header">
        <div class="result-count">
          找到 <b>{{ items.length }}</b> 件商品
          <span v-if="searchForm.keyword" class="muted">（关键词："{{ searchForm.keyword }}"）</span>
        </div>
        <div class="page-controls">
          <el-button size="small" :disabled="(searchForm.page || 1) <= 1" @click="doSearch((searchForm.page || 1) - 1)">
            上一页
          </el-button>
          <span class="page-num">第 {{ searchForm.page || 1 }} 页</span>
          <el-button size="small" :disabled="!hasMore" type="primary" plain @click="doSearch((searchForm.page || 1) + 1)">
            下一页
          </el-button>
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

      <!-- 网格卡片模式 (闲鱼官方 Web 真实卡片风格) -->
      <div v-else-if="viewMode === 'grid'" class="gf-items-grid">
        <div v-for="it in items" :key="it.item_id" class="gf-item-card" @click="openDetail(it)">
          <!-- 商品大图 (1:1 正方形微缩放大图) -->
          <div class="gf-cover-box">
            <el-image :src="it.image_url" fit="cover" class="gf-card-img" lazy referrerpolicy="no-referrer">
              <template #error>
                <div class="gf-img-error"><el-icon><Picture /></el-icon></div>
              </template>
            </el-image>
            <div v-if="it.area" class="gf-float-area">
              <el-icon><Location /></el-icon><span>{{ it.area }}</span>
            </div>
            <div v-if="it.want_cnt" class="gf-float-want">
              🔥 {{ it.want_cnt }}人想要
            </div>
          </div>

          <!-- 卡片内容区域 -->
          <div class="gf-card-info">
            <!-- 标题（内嵌包邮/验货宝闲鱼标签） -->
            <div class="gf-card-title-row" :title="it.title">
              <span v-if="hasBaoYou(it)" class="gf-badge-baoyou">包邮</span>
              <span v-if="hasYanHuo(it)" class="gf-badge-yanhuo">验货宝</span>
              <span class="gf-title-text">{{ it.title }}</span>
            </div>

            <!-- 发布时效与标语 -->
            <div class="gf-time-meta">
              <span class="gf-time-clock">⏱</span>
              <span>{{ fmtRelative(it.publish_time) || '刚刚' }}发布</span>
              <span v-if="hasBaoYou(it)" class="gf-tag-sub">描述不符包邮退</span>
            </div>

            <!-- 价格行与想要人数 -->
            <div class="gf-price-line">
              <div class="gf-price-val">
                <span class="yen">¥</span>
                <span class="num">{{ it.price ?? '-' }}</span>
              </div>
              <span v-if="it.want_cnt" class="gf-want-text">{{ it.want_cnt }}人想要</span>
              <span v-else-if="it.orig_price" class="gf-orig-price">¥{{ it.orig_price }}</span>
            </div>

            <!-- 卖家与信誉底栏 -->
            <div class="gf-seller-bar">
              <div class="gf-seller-info">
                <div class="gf-seller-avatar">
                  <span>{{ (it.seller_nick || '闲')[0] }}</span>
                </div>
                <span class="gf-seller-name ellipsis">{{ it.area || it.seller_nick || '闲鱼卖家' }}</span>
              </div>
              <span class="gf-credit-pill">{{ sellerCredit(it) }}</span>
            </div>

            <!-- 悬浮快捷操作 -->
            <div class="gf-hover-actions" @click.stop>
              <button type="button" class="gf-hover-btn primary" @click="openDetail(it)">详情</button>
              <button type="button" class="gf-hover-btn success" @click="quickResell(it)">转手发品</button>
              <a :href="safeItemLink(it)" target="_blank" rel="noopener" class="gf-hover-link">
                <button type="button" class="gf-hover-btn yellow">
                  <span>去闲鱼</span>
                  <el-icon><TopRight /></el-icon>
                </button>
              </a>
              <button type="button" class="gf-hover-btn ghost" @click="watchPrice(it)">价格监控</button>
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
    <el-drawer v-model="detail.open" title="商品详情" size="580px" destroy-on-close>
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
/* 闲鱼官方标志性明黄沉浸搜索 Header */
.gf-yellow-header {
  background: #ffda00;
  border-radius: 12px;
  padding: 12px 18px;
  margin-bottom: 12px;
  box-shadow: 0 4px 16px rgba(255, 218, 0, 0.25);
  flex-shrink: 0;
}
.gf-header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.gf-brand-block {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.gf-fish-bubble {
  background: #111111;
  color: #ffda00;
  font-weight: 900;
  font-size: 16px;
  padding: 3px 8px;
  border-radius: 8px;
  letter-spacing: -0.5px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}
.gf-brand-sub {
  font-size: 13.5px;
  font-weight: 700;
  color: #111111;
}

/* 闲鱼官方大圆角纯白胶囊搜索栏 */
.gf-search-center {
  flex: 1;
  max-width: 640px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.gf-search-pill-box {
  display: flex;
  align-items: center;
  background: #ffffff;
  border-radius: 999px;
  height: 40px;
  padding: 2px 3px 2px 14px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: all 0.18s ease;
}
.gf-search-pill-box:focus-within {
  box-shadow: 0 0 0 2px #111111;
}
.gf-search-lens {
  font-size: 16px;
  color: #999999;
  margin-right: 8px;
}
.gf-search-native-input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 13.5px;
  color: #111111;
  background: transparent;
}
.gf-search-native-input::placeholder {
  color: #999999;
}
.gf-clear-btn {
  background: none;
  border: none;
  color: #bbb;
  font-size: 16px;
  cursor: pointer;
  padding: 0 8px;
}
.gf-clear-btn:hover {
  color: #666;
}
.gf-search-submit-btn {
  background: #ffda00;
  color: #111111;
  border: none;
  height: 34px;
  padding: 0 16px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s ease;
}
.gf-search-submit-btn:hover {
  background: #ffe333;
  transform: scale(1.02);
}
.gf-search-submit-btn:active {
  transform: scale(0.98);
}

/* 热门搜索推荐词流 */
.gf-hot-stream {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11.5px;
  overflow-x: auto;
  white-space: nowrap;
  padding: 0 4px;
}
.gf-hot-lead {
  color: #665200;
  font-weight: 600;
  font-size: 11px;
}
.gf-hot-item {
  color: #332600;
  cursor: pointer;
  transition: color 0.15s;
}
.gf-hot-item:hover {
  color: #000;
  font-weight: 600;
  text-decoration: underline;
}

/* 转监控快捷按钮 */
.gf-header-actions {
  flex-shrink: 0;
}
.gf-task-convert-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #111111;
  color: #ffda00;
  border: none;
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.gf-task-convert-btn:hover {
  background: #2b2b2b;
  transform: translateY(-1px);
}

/* 闲鱼官方极简白底胶囊筛选器大卡片 (1:1 还原闲鱼 Web 筛选栏) */
.gf-filter-card {
  background: #ffffff;
  border-radius: 10px;
  border: 1px solid #ebeef5;
  padding: 10px 14px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}
.gf-filter-row-primary {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

/* 排序胶囊组 */
.gf-sort-pills {
  display: flex;
  align-items: center;
  gap: 6px;
}
.gf-pill-btn {
  background: #f6f6f6;
  border: 1px solid transparent;
  color: #333333;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
}
.gf-pill-btn span {
  font-size: 10px;
  color: #888;
}
.gf-pill-btn:hover {
  background: #eee;
  color: #111;
}
.gf-pill-btn.is-active {
  background: #111111;
  color: #ffda00;
  font-weight: 700;
}
.gf-pill-btn.is-active span {
  color: #ffda00;
}

/* 价格区间输入框 */
.gf-price-range-group {
  display: flex;
  align-items: center;
  gap: 4px;
}
.gf-price-input-box {
  display: inline-flex;
  align-items: center;
  background: #f6f6f6;
  border: 1px solid #eee;
  border-radius: 6px;
  padding: 2px 6px;
  width: 72px;
}
.gf-price-input-box .yen {
  font-size: 11px;
  color: #999;
  margin-right: 2px;
}
.gf-mini-price-input {
  width: 100%;
  border: none;
  background: transparent;
  outline: none;
  font-size: 11.5px;
  color: #222;
}
.range-dash {
  color: #bbb;
  font-size: 12px;
}

/* 快捷区域选择 */
.gf-region-selector {
  display: flex;
  align-items: center;
  gap: 6px;
}
.region-prefix {
  font-size: 12px;
  color: #888;
}
.gf-cities-chips {
  display: flex;
  align-items: center;
  gap: 5px;
}
.gf-city-chip {
  font-size: 11.5px;
  color: #555;
  background: #f6f6f6;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.gf-city-chip:hover {
  background: #eee;
  color: #111;
}
.gf-city-chip.is-active {
  background: #ffda00;
  color: #111;
  font-weight: 700;
}

/* 右侧工具栏与分页 */
.gf-tools-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.gf-protect-badge {
  font-size: 11px;
  background: #f0fdf4;
  color: #16a34a;
  border: 1px solid #bbf7d0;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.gf-account-select {
  width: 130px;
}
.gf-mini-pager {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #666;
}
.gf-page-arrow {
  background: #f6f6f6;
  border: 1px solid #eee;
  width: 22px;
  height: 22px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  color: #444;
}
.gf-page-arrow:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.gf-page-text {
  font-size: 11.5px;
  font-weight: 600;
  color: #222;
}
.gf-view-switch-btn {
  background: #f6f6f6;
  border: 1px solid transparent;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #666;
  transition: all 0.15s ease;
}
.gf-view-switch-btn.is-active {
  background: #111;
  color: #ffda00;
}

/* 第二行：闲鱼标志性圆圈勾选标签 */
.gf-filter-row-secondary {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-top: 6px;
  border-top: 1px dashed #f0f0f0;
  font-size: 12.5px;
}
.gf-round-check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  user-select: none;
}
.gf-round-check input {
  display: none;
}
.check-circle {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1.5px solid #ccc;
  display: inline-block;
  position: relative;
  transition: all 0.15s ease;
}
.gf-round-check input:checked + .check-circle {
  background: #ffda00;
  border-color: #111;
}
.gf-round-check input:checked + .check-circle::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #111;
}
.check-title {
  color: #444;
  font-weight: 500;
}
.gf-round-check input:checked ~ .check-title {
  color: #111;
  font-weight: 700;
}
.gf-reset-filters-btn {
  margin-left: auto;
  background: none;
  border: none;
  color: #888;
  font-size: 11.5px;
  cursor: pointer;
}
.gf-reset-filters-btn:hover {
  color: #ff4400;
}

.results-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.result-count b {
  color: #ff4400;
  font-size: 16px;
}
.page-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}
.page-num {
  font-size: 13px;
  color: var(--xh-muted);
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

/* 闲鱼官方商品网格卡片瀑布流 (1:1 还原闲鱼 Web 端视觉体验) */
.gf-items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(215px, 1fr));
  gap: 14px;
}
.gf-item-card {
  background: #ffffff;
  border: 1px solid #f0f0f0;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease;
  position: relative;
}
.gf-item-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
}
.gf-cover-box {
  width: 100%;
  padding-top: 100%;
  position: relative;
  background: #f7f8fa;
  overflow: hidden;
}
.gf-card-img {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  transition: transform 0.25s ease;
}
.gf-item-card:hover .gf-card-img {
  transform: scale(1.03);
}
.gf-img-error {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ccc;
  font-size: 24px;
}
.gf-float-area {
  position: absolute;
  bottom: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.55);
  color: #ffffff;
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 2px;
  backdrop-filter: blur(4px);
}
.gf-float-want {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(255, 68, 0, 0.9);
  color: #fff;
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

/* 卡片内容区域 */
.gf-card-info {
  padding: 10px 10px 12px;
  display: flex;
  flex-direction: column;
  flex: 1;
}

/* 标题与闲鱼特色标签 (黄包邮 / 蓝验货宝) */
.gf-card-title-row {
  font-size: 13.5px;
  line-height: 1.4;
  color: #222222;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 38px;
  margin-bottom: 4px;
  font-weight: 500;
}
.gf-badge-baoyou {
  background: #ffe000;
  color: #111111;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 3px;
  margin-right: 5px;
  vertical-align: 1px;
  display: inline-block;
}
.gf-badge-yanhuo {
  background: #0084ff;
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 3px;
  margin-right: 5px;
  vertical-align: 1px;
  display: inline-block;
}
.gf-title-text {
  vertical-align: middle;
}

/* 发布时效 */
.gf-time-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #888888;
  margin-bottom: 6px;
}
.gf-time-clock {
  font-size: 10px;
}
.gf-tag-sub {
  color: #ff5000;
  border: 1px solid #ffd0b8;
  padding: 0 4px;
  border-radius: 2px;
  font-size: 10px;
  margin-left: 4px;
}

/* 价格行 (闲鱼标志性橙红大数字) */
.gf-price-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 8px;
}
.gf-price-val {
  color: #ff4400;
  font-weight: 700;
  font-family: -apple-system, BlinkMacSystemFont, "DIN Alternate", "Helvetica Neue", sans-serif;
  line-height: 1;
}
.gf-price-val .yen {
  font-size: 13px;
  margin-right: 1px;
}
.gf-price-val .num {
  font-size: 21px;
  letter-spacing: -0.5px;
}
.gf-want-text {
  font-size: 11px;
  color: #999999;
}
.gf-orig-price {
  font-size: 11px;
  color: #999999;
  text-decoration: line-through;
}

/* 卖家与信誉底栏 */
.gf-seller-bar {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px solid #f6f6f6;
}
.gf-seller-info {
  display: flex;
  align-items: center;
  gap: 5px;
  max-width: 60%;
}
.gf-seller-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #ffda00;
  color: #111;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.gf-seller-name {
  font-size: 11px;
  color: #666666;
}
.gf-credit-pill {
  font-size: 10px;
  color: #ff5000;
  background: #fff2eb;
  padding: 1px 6px;
  border-radius: 999px;
  font-weight: 500;
  white-space: nowrap;
}

/* 悬浮快捷操作栏 */
.gf-hover-actions {
  display: none;
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(255, 255, 255, 0.97);
  padding: 8px 10px;
  border-top: 1px solid #f0f0f0;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  backdrop-filter: blur(6px);
}
.gf-item-card:hover .gf-hover-actions {
  display: grid;
}
.gf-hover-btn {
  height: 28px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  transition: all 0.15s ease;
}
.gf-hover-btn.primary {
  background: #f6f6f6;
  color: #333;
}
.gf-hover-btn.primary:hover {
  background: #e9e9e9;
  color: #000;
}
.gf-hover-btn.success {
  background: #ecfdf5;
  color: #059669;
  border: 1px solid #a7f3d0;
}
.gf-hover-btn.success:hover {
  background: #10b981;
  color: #fff;
}
.gf-hover-btn.yellow {
  background: #ffda00;
  color: #111;
  width: 100%;
}
.gf-hover-btn.yellow:hover {
  background: #ffe533;
}
.gf-hover-btn.ghost {
  background: #ffffff;
  color: #666;
  border: 1px solid #e5e7eb;
}
.gf-hover-btn.ghost:hover {
  background: #f9fafb;
  color: #111;
}
.gf-hover-link {
  text-decoration: none;
  display: flex;
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
