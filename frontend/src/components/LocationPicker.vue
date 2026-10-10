<script setup lang="ts">
// 宝贝所在地选择：选城市或用当前位置 → 列出附近地点（与闲鱼网页版发布页同一接口）
import { computed, ref, watch } from 'vue'
import { Aim, Check } from '@element-plus/icons-vue'
import { getLocations, type ItemLocation, type LocationOptions } from '@/api/goods'
import { PROVINCES, wgs84ToGcj02 } from '@/utils/cities'

const props = defineProps<{
  modelValue: boolean
  accountId: number | null
  current: ItemLocation | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'select', v: ItemLocation): void
}>()

const open = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) })
const options = ref<LocationOptions>({ saved: null, common: [], nearby: [] })
const loading = ref(false)
const locating = ref(false)
const error = ref('')
const city = ref<string[]>([])

const cascader = PROVINCES.map((p) => ({
  value: p.name,
  label: p.name,
  children: p.cities.map((c) => ({ value: c.name, label: c.name })),
}))

async function load(coords?: { longitude: number; latitude: number }) {
  if (!props.accountId) return
  loading.value = true
  error.value = ''
  try {
    options.value = await getLocations(props.accountId, coords)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    error.value = err.response?.data?.detail || err.message || '获取地点失败'
  } finally {
    loading.value = false
  }
}

watch(open, (v) => {
  if (!v) return
  error.value = ''
  const cur = props.current
  // 已有所在地：直接列出它附近的地点，方便微调
  load(cur ? { longitude: cur.longitude, latitude: cur.latitude } : undefined)
})

function pickCity(v: unknown) {
  const path = Array.isArray(v) ? (v as string[]) : []
  if (!path.length) return
  const p = PROVINCES.find((x) => x.name === path[0])
  const c = p?.cities.find((x) => x.name === path[path.length - 1])
  if (c) load({ longitude: c.lng, latitude: c.lat })
}

function useCurrent() {
  if (!navigator.geolocation) {
    error.value = '当前浏览器不支持定位，请选择城市'
    return
  }
  locating.value = true
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      locating.value = false
      const g = wgs84ToGcj02(pos.coords.longitude, pos.coords.latitude)
      city.value = []
      load({ longitude: g.lng, latitude: g.lat })
    },
    () => {
      locating.value = false
      error.value = '无法获取当前位置（可能未授权定位），请选择城市'
    },
    { timeout: 10000, maximumAge: 600000 },
  )
}

const sameAs = (a: ItemLocation | null, b: ItemLocation) =>
  !!a && (a.poiId ? a.poiId === b.poiId : a.poi === b.poi && a.divisionId === b.divisionId)

const groups = computed(() => {
  const seen = new Set<string>()
  const uniq = (list: ItemLocation[]) =>
    list.filter((x) => {
      const k = x.poiId || `${x.divisionId}-${x.poi}`
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
  return [
    { title: '上次使用', list: uniq(options.value.saved ? [options.value.saved] : []) },
    { title: '闲鱼常用地址', list: uniq(options.value.common) },
    { title: '附近地点', list: uniq(options.value.nearby) },
  ].filter((g) => g.list.length)
})

function choose(loc: ItemLocation) {
  emit('select', loc)
  open.value = false
}
</script>

<template>
  <el-dialog v-model="open" title="宝贝所在地" width="520px" append-to-body class="location-picker">
    <p class="sub">闲鱼会把商品优先推给附近的买家；只显示到区县，不会公开具体门牌。</p>
    <div class="bar">
      <el-cascader
        v-model="city"
        :options="cascader"
        placeholder="选择城市"
        filterable
        class="city"
        @change="pickCity"
      />
      <el-button :icon="Aim" :loading="locating" @click="useCurrent">使用当前位置</el-button>
    </div>

    <div v-loading="loading" class="list">
      <p v-if="error" class="error">{{ error }}</p>
      <template v-for="g in groups" :key="g.title">
        <div class="group-title">{{ g.title }}</div>
        <button
          v-for="loc in g.list"
          :key="loc.poiId || `${loc.divisionId}-${loc.poi}`"
          type="button"
          class="loc"
          :class="{ on: sameAs(current, loc) }"
          @click="choose(loc)"
        >
          <span class="text">
            <span class="poi">{{ loc.poi || loc.area }}</span>
            <span class="addr">{{ loc.city }}{{ loc.area ? ` ${loc.area}` : '' }}{{ loc.address ? ` · ${loc.address}` : '' }}</span>
          </span>
          <el-icon v-if="sameAs(current, loc)" class="check"><Check /></el-icon>
        </button>
      </template>
      <p v-if="!loading && !error && !groups.length" class="empty">选择城市或使用当前位置，查看附近的地点</p>
    </div>
  </el-dialog>
</template>

<style scoped>
.sub {
  margin: 0 0 var(--xh-space-3);
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.bar {
  display: flex;
  gap: var(--xh-space-2);
}
.city {
  flex: 1;
}
.list {
  min-height: 160px;
  max-height: 360px;
  margin-top: var(--xh-space-3);
  overflow-y: auto;
}
.group-title {
  margin: var(--xh-space-3) 0 var(--xh-space-1);
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
}
.group-title:first-of-type {
  margin-top: 0;
}
.loc {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
  width: 100%;
  padding: var(--xh-space-2) var(--xh-space-3);
  border: none;
  border-radius: var(--xh-radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.loc:hover {
  background: var(--xh-fill);
}
.loc.on {
  background: var(--xh-primary-soft);
}
.text {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.poi {
  font-size: var(--xh-fs-sm);
  font-weight: 500;
  color: var(--xh-text);
}
.addr {
  font-size: var(--xh-fs-xs);
  color: var(--xh-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.check {
  color: var(--xh-primary);
}
.error {
  margin: 0;
  font-size: var(--xh-fs-sm);
  color: var(--xh-danger);
}
.empty {
  margin: var(--xh-space-5) 0;
  text-align: center;
  font-size: var(--xh-fs-sm);
  color: var(--xh-muted);
}
</style>
