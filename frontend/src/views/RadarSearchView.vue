<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
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
import { fmtMoney, fmtRelative } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const accounts = useAccountsStore()

// 视图模式：卡片网格 vs 紧凑列表
const viewMode = ref<'grid' | 'list'>('grid')

// 搜索条件
const searchForm = reactive({
  keyword: '',
  page: 1,
  sort: 'newest' as LiveSearchQuery['sort'],
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

// 排序选项
const sortOptions = [
  { label: '最新发布', value: 'newest' },
  { label: '价格从低到高', value: 'price_asc' },
  { label: '价格从高到低', value: 'price_desc' },
  { label: '综合排序', value: 'default' },
]

// 发布时间选项
const publishDayOptions = [
  { label: '不限时间', value: 0 },
  { label: '1 天内', value: 1 },
  { label: '3 天内', value: 3 },
  { label: '7 天内', value: 7 },
  { label: '14 天内', value: 14 },
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

async function doSearch(page = 1) {
  const kw = searchForm.keyword.trim()
  if (!kw) {
    ElMessage.warning('请输入搜索关键词')
    return
  }
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

function onQuickSearch(kw: string) {
  searchForm.keyword = kw
  doSearch(1)
}

function selectCity(c: { province: string | null; city: string | null }) {
  searchForm.province = c.province
  searchForm.city = c.city
  if (searchForm.keyword.trim()) {
    doSearch(1)
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
  searchForm.sort = 'newest'
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

// ---------------------------------------------------------------- 转为监控任务
const taskModal = reactive({
  open: false,
  saving: false,
  form: emptyTask(),
})

function openCreateTask(fromItem?: SearchItem) {
  const kw = fromItem?.title || searchForm.keyword.trim() || '商品监控'
  const t = emptyTask()
  t.name = `监控：${kw.slice(0, 16)}`
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
    ElMessage.success('已成功转为监控任务！后台将定期自动巡检')
    taskModal.open = false
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(err.response?.data?.detail || '保存监控任务失败')
  } finally {
    taskModal.saving = false
  }
}

onMounted(() => {
  accounts.load().catch(() => undefined)
  const q = route.query.q
  if (typeof q === 'string' && q.trim()) {
    searchForm.keyword = q.trim()
    if (typeof route.query.sort === 'string') {
      searchForm.sort = route.query.sort as LiveSearchQuery['sort']
    }
    doSearch(1)
  }
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>选品雷达 · 商品搜索</h2>
        <div class="sub">实时搜索闲鱼商品，即查即看，无需创建长期监控任务；遇到满意条件也可一键转为自动监控</div>
      </div>
      <div class="toolbar">
        <el-button v-if="searchForm.keyword.trim()" type="primary" plain :icon="Bell" @click="openCreateTask()">
          把当前搜索转为监控任务
        </el-button>
        <router-link to="/radar/tasks">
          <el-button>管理监控任务</el-button>
        </router-link>
      </div>
    </div>

    <!-- 搜索与筛选大卡片 -->
    <el-card shadow="never" class="search-box-card">
      <div class="search-input-wrap">
        <el-input
          v-model="searchForm.keyword"
          size="large"
          clearable
          placeholder="输入想找的商品，例如：MacBook Air M1、iPad、索尼微单、戴森吹风机..."
          class="main-search-input"
          @keyup.enter="doSearch(1)"
        >
          <template #prefix>
            <el-icon :size="20" class="search-icon"><Search /></el-icon>
          </template>
          <template #append>
            <el-button type="primary" :loading="loading" class="search-action-btn" @click="doSearch(1)">
              立即搜索
            </el-button>
          </template>
        </el-input>
      </div>

      <!-- 热门关键词快捷胶囊 -->
      <div class="hot-keywords">
        <span class="hot-label">大家都在搜：</span>
        <el-tag
          v-for="kw in hotKeywords"
          :key="kw"
          size="small"
          effect="plain"
          class="hot-tag"
          @click="onQuickSearch(kw)"
        >
          {{ kw }}
        </el-tag>
      </div>

      <!-- 快速筛选器条 -->
      <div class="filter-row">
        <div class="filter-item">
          <span class="filter-label">排序：</span>
          <el-radio-group v-model="searchForm.sort" size="small" @change="doSearch(1)">
            <el-radio-button v-for="o in sortOptions" :key="o.value" :value="o.value">
              {{ o.label }}
            </el-radio-button>
          </el-radio-group>
        </div>

        <div class="filter-item price-range">
          <span class="filter-label">价格：</span>
          <el-input-number
            v-model="searchForm.min_price"
            size="small"
            :min="0"
            :controls="false"
            placeholder="最低价"
            class="w90"
            @keyup.enter="doSearch(1)"
          />
          <span class="dash">-</span>
          <el-input-number
            v-model="searchForm.max_price"
            size="small"
            :min="0"
            :controls="false"
            placeholder="最高价"
            class="w90"
            @keyup.enter="doSearch(1)"
          />
        </div>

        <div class="filter-item">
          <span class="filter-label">发布：</span>
          <el-select v-model="searchForm.publish_days" size="small" class="w110" placeholder="发布时间" @change="doSearch(1)">
            <el-option v-for="d in publishDayOptions" :key="String(d.value)" :label="d.label" :value="d.value" />
          </el-select>
        </div>

        <div class="filter-item checks">
          <el-checkbox v-model="searchForm.personal_only" label="仅看个人闲置" @change="doSearch(1)" />
          <el-checkbox v-model="searchForm.free_shipping" label="包邮" @change="doSearch(1)" />
        </div>

        <div class="filter-item">
          <span class="filter-label">账号通道：</span>
          <el-select v-model="searchForm.account_id" size="small" clearable placeholder="自动 / 匿名通道" class="w140" @change="doSearch(1)">
            <el-option :value="0" label="自动 / 匿名通道" />
            <el-option v-for="a in accounts.list" :key="a.id" :value="a.id" :label="a.nickname || a.remark || a.unb" />
          </el-select>
        </div>

        <div class="filter-item ops-right">
          <el-button size="small" link @click="resetFilters">重置筛选</el-button>
          <el-button-group size="small" class="ml-s">
            <el-button :type="viewMode === 'grid' ? 'primary' : 'default'" :icon="Grid" @click="viewMode = 'grid'" />
            <el-button :type="viewMode === 'list' ? 'primary' : 'default'" :icon="List" @click="viewMode = 'list'" />
          </el-button-group>
        </div>
      </div>

      <!-- 热门城市快速筛选 -->
      <div class="cities-bar">
        <span class="filter-label">快捷地区：</span>
        <el-tag
          v-for="c in hotCities"
          :key="c.label"
          size="small"
          :effect="searchForm.city === c.city && searchForm.province === c.province ? 'dark' : 'plain'"
          class="city-tag"
          @click="selectCity(c)"
        >
          {{ c.label }}
        </el-tag>
        <span class="custom-city">
          <el-input v-model="searchForm.city" size="small" placeholder="输入城市" clearable class="w100" @keyup.enter="doSearch(1)" />
        </span>
      </div>
    </el-card>

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

      <!-- 未搜索时的引导占位 -->
      <el-card v-if="!searched && !loading" shadow="never" class="welcome-box">
        <div class="welcome-inner">
          <div class="icon-circle">
            <el-icon :size="48" color="#409eff"><Search /></el-icon>
          </div>
          <h3>输入关键词，立即探索闲鱼好货</h3>
          <p class="muted">
            无需像以前那样先建监控任务等待！直接输入商品名称或型号，一键查看最新挂牌价、成色与卖家信息。
          </p>
          <div class="quick-try">
            <span>试一试：</span>
            <el-button v-for="k in hotKeywords.slice(0, 4)" :key="k" size="small" round @click="onQuickSearch(k)">
              {{ k }}
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- 搜索无结果 -->
      <el-empty v-else-if="searched && !loading && !items.length && !searchError" description="没有找到符合条件的商品，换个词试试？" />

      <!-- 网格卡片模式 -->
      <div v-else-if="viewMode === 'grid'" class="items-grid">
        <div v-for="it in items" :key="it.item_id" class="item-card" @click="openDetail(it)">
          <div class="card-cover-wrap">
            <el-image :src="it.image_url" fit="cover" class="card-cover" lazy referrerpolicy="no-referrer">
              <template #error>
                <div class="img-slot"><el-icon><Picture /></el-icon></div>
              </template>
            </el-image>
            <div v-if="it.area" class="card-badge-area">
              <el-icon><Location /></el-icon>{{ it.area }}
            </div>
            <div v-if="it.want_cnt" class="card-badge-want">
              🔥 {{ it.want_cnt }}人想要
            </div>
          </div>

          <div class="card-body">
            <div class="card-price-row">
              <div class="card-price">
                <span class="yen">¥</span>{{ it.price ?? '-' }}
              </div>
              <span v-if="it.orig_price" class="card-orig-price">¥{{ it.orig_price }}</span>
              <el-tag v-if="it.tags?.includes('包邮')" size="small" type="success" effect="plain" class="card-tag">包邮</el-tag>
            </div>

            <div class="card-title" :title="it.title">
              {{ it.title }}
            </div>

            <div class="card-footer">
              <div class="card-seller" :title="it.seller_nick">
                <el-icon><User /></el-icon>
                <span class="ellipsis">{{ it.seller_nick || '闲鱼卖家' }}</span>
              </div>
              <div class="card-time">
                {{ fmtRelative(it.publish_time) || '刚刚' }}
              </div>
            </div>

            <div class="card-hover-actions" @click.stop>
              <el-button size="small" type="primary" plain @click="openDetail(it)">详情</el-button>
              <a :href="safeItemLink(it)" target="_blank" rel="noopener">
                <el-button size="small" :icon="TopRight">去闲鱼</el-button>
              </a>
              <el-button size="small" :icon="Bell" @click="openCreateTask(it)">监控此款</el-button>
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
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <div @click.stop>
                <el-button size="small" type="primary" link @click="openDetail(row as SearchItem)">详情</el-button>
                <a :href="safeItemLink(row as SearchItem)" target="_blank" rel="noopener" class="ml-s">
                  <el-button size="small" link>去闲鱼</el-button>
                </a>
                <el-button size="small" link type="warning" @click="openCreateTask(row as SearchItem)">监控</el-button>
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
            <a :href="safeItemLink(detail.data.item)" target="_blank" rel="noopener" class="full-btn">
              <el-button type="primary" size="large" class="full">
                前往闲鱼沟通 / 购买
                <el-icon class="el-icon--right"><TopRight /></el-icon>
              </el-button>
            </a>
            <el-button size="large" :icon="Bell" class="mt-s full" @click="openCreateTask(detail.data.item)">
              监控此款商品价格
            </el-button>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 一键转监控任务弹窗 -->
    <el-dialog v-model="taskModal.open" title="保存为自动监控任务" width="560px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item label="任务名称" required>
          <el-input v-model="taskModal.form.name" placeholder="例如：监控 M1 Air 笔记本" />
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
            <el-option value="*/10 8-23 * * *" label="每 10 分钟一次（白天）" />
            <el-option value="*/30 8-23 * * *" label="每 30 分钟一次（推荐，低风控）" />
            <el-option value="0 * * * *" label="每小时一次" />
            <el-option value="0 */3 * * *" label="每 3 小时一次" />
          </el-select>
        </el-form-item>
        <el-form-item label="筛选条件">
          <el-checkbox v-model="taskModal.form.personal_only" label="仅看个人闲置" />
          <el-checkbox v-model="taskModal.form.free_shipping" label="仅看包邮" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="taskModal.open = false">取消</el-button>
        <el-button type="primary" :loading="taskModal.saving" @click="saveTask">立即保存并启动监控</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.search-box-card {
  margin-bottom: 20px;
  border-radius: 12px;
}
.search-input-wrap {
  margin-bottom: 12px;
}
.main-search-input :deep(.el-input__wrapper) {
  padding-left: 14px;
  border-radius: 8px 0 0 8px;
  box-shadow: 0 0 0 1px var(--el-border-color) inset;
}
.main-search-input :deep(.el-input-group__append) {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
  color: #fff;
  border-radius: 0 8px 8px 0;
  padding: 0 24px;
  font-size: 15px;
  font-weight: 600;
}
.main-search-input :deep(.el-input-group__append:hover) {
  background: var(--el-color-primary-light-3);
}
.search-action-btn {
  color: #fff !important;
}
.search-icon {
  color: var(--xh-muted);
}
.hot-keywords {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  font-size: 13px;
}
.hot-label {
  color: var(--xh-muted);
}
.hot-tag {
  cursor: pointer;
  transition: all 0.15s;
}
.hot-tag:hover {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary);
}
.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--xh-border);
}
.filter-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.filter-label {
  color: var(--xh-muted);
  white-space: nowrap;
}
.dash {
  color: var(--xh-muted);
}
.ops-right {
  margin-left: auto;
}
.cities-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--xh-border);
  font-size: 13px;
}
.city-tag {
  cursor: pointer;
}
.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.result-count b {
  color: var(--el-color-primary);
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

/* 欢迎/引导区 */
.welcome-box {
  padding: 40px 20px;
  text-align: center;
  border-radius: 12px;
}
.welcome-inner {
  max-width: 520px;
  margin: 0 auto;
}
.icon-circle {
  width: 80px;
  height: 80px;
  background: var(--el-color-primary-light-9);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
}
.welcome-inner h3 {
  font-size: 18px;
  margin-bottom: 8px;
}
.quick-try {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
}

/* 网格瀑布流 */
.items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 16px;
}
.item-card {
  background: #fff;
  border: 1px solid var(--xh-border);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
  position: relative;
}
.item-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.08);
}
.card-cover-wrap {
  width: 100%;
  padding-top: 100%;
  position: relative;
  background: #f7f8fa;
}
.card-cover {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.card-badge-area {
  position: absolute;
  bottom: 8px;
  left: 8px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 3px;
  backdrop-filter: blur(4px);
}
.card-badge-want {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(245, 108, 108, 0.9);
  color: #fff;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.card-body {
  padding: 12px;
  display: flex;
  flex-direction: column;
  flex: 1;
}
.card-price-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 6px;
}
.card-price {
  color: #f56c6c;
  font-size: 18px;
  font-weight: 700;
}
.card-price .yen {
  font-size: 13px;
  margin-right: 1px;
}
.card-orig-price {
  color: #909399;
  font-size: 12px;
  text-decoration: line-through;
}
.card-tag {
  margin-left: auto;
}
.card-title {
  font-size: 14px;
  line-height: 1.4;
  color: #303133;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  height: 40px;
  margin-bottom: 10px;
  font-weight: 500;
}
.card-footer {
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #909399;
  border-top: 1px solid #f2f3f5;
  padding-top: 8px;
}
.card-seller {
  display: flex;
  align-items: center;
  gap: 4px;
  max-width: 60%;
}
.card-hover-actions {
  display: none;
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(255, 255, 255, 0.96);
  padding: 8px 12px;
  border-top: 1px solid #ebeef5;
  justify-content: space-between;
  gap: 6px;
  backdrop-filter: blur(4px);
}
.item-card:hover .card-hover-actions {
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
</style>
