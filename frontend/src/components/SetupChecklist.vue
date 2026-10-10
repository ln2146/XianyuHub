<script setup lang="ts">
// 上手清单：按使用模式列出必做的配置，每一步的完成状态都来自真实数据；全部完成或手动收起后不再显示
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Check, Close } from '@element-plus/icons-vue'
import type { Dashboard } from '@/api/dashboard'
import { listItems } from '@/api/goods'
import { listChannels } from '@/api/notify'
import { listPools } from '@/api/order'
import { usageModeLabels, usePrefsStore, type UsageMode } from '@/stores/prefs'
import { getItem, setItem, SETUP_DISMISSED_KEY } from '@/utils/storage'

const props = defineProps<{ data: Dashboard | null }>()
const router = useRouter()
const prefs = usePrefsStore()

const facts = reactive({ loaded: false, channels: 0, items: 0, itemsConfigured: 0, pools: 0 })
const dismissed = ref(getItem(SETUP_DISMISSED_KEY) === '1')

onMounted(async () => {
  const [channels, items, pools] = await Promise.all([
    listChannels().catch(() => []),
    listItems({}).catch(() => []),
    listPools().catch(() => []),
  ])
  facts.channels = channels.filter((c) => c.enabled).length
  facts.items = items.length
  facts.itemsConfigured = items.filter((i) => i.floor_price != null || (i.knowledge || '').trim()).length
  facts.pools = pools.length
  facts.loaded = true
})

interface Step {
  key: string
  title: string
  desc: string
  done: boolean
  to: string
  action: string
  modes: UsageMode[]
  optional?: boolean
}

const steps = computed<Step[]>(() => {
  const accounts = props.data?.accounts || []
  const all: Step[] = [
    {
      key: 'account',
      title: '绑定闲鱼账号',
      desc: '扫码登录或导入 Cookie；只买东西也可以先跳过，搜索默认用匿名通道',
      done: accounts.length > 0,
      to: '/accounts',
      action: '去绑定',
      modes: ['seller', 'all'],
    },
    {
      key: 'notify',
      title: '设置推送到微信',
      desc: '好货、降价、新订单、风控提醒第一时间通知你（推荐 Server酱 / PushPlus）',
      done: facts.channels > 0,
      to: '/notify',
      action: '去设置',
      modes: ['buyer', 'seller', 'all'],
    },
    {
      key: 'smart',
      title: '创建一个智能搜索',
      desc: '说一句想买什么，系统定时搜闲鱼并用 AI 挑出值得买的',
      done: (props.data?.monitor_tasks || 0) > 0,
      to: '/radar/smart',
      action: '去创建',
      modes: ['buyer', 'all'],
    },
    {
      key: 'sync',
      title: '同步在售商品',
      desc: '把闲鱼上正在卖的商品拉进来，后面的底价、自动回复、自动发货都基于它',
      done: facts.items > 0,
      to: '/goods/items',
      action: '去同步',
      modes: ['seller', 'all'],
    },
    {
      key: 'floor',
      title: '给商品设底价和知识库',
      desc: 'AI 回复与议价的依据；底价不会透露给买家',
      done: facts.itemsConfigured > 0,
      to: '/goods/items',
      action: '去设置',
      modes: ['seller', 'all'],
    },
    {
      key: 'reply',
      title: '试运行后开启自动回复',
      desc: '先在在线客服点「试运行」看 AI 会怎么回，满意了再在账号设置里打开',
      done: accounts.some((a) => a.auto_reply),
      to: '/messages/inbox',
      action: '去试运行',
      modes: ['seller', 'all'],
    },
    {
      key: 'delivery',
      title: '配置自动发货（虚拟商品）',
      desc: '卖卡密、网盘资料时，买家付款后自动发送并确认发货；实物商品可跳过',
      done: facts.pools > 0,
      to: '/orders/cards',
      action: '去配置',
      modes: ['seller', 'all'],
      optional: true,
    },
  ]
  return all.filter((s) => s.modes.includes(prefs.mode))
})

const required = computed(() => steps.value.filter((s) => !s.optional))
const doneCount = computed(() => required.value.filter((s) => s.done).length)
const visible = computed(
  () => facts.loaded && !!props.data && !dismissed.value && doneCount.value < required.value.length,
)

const modeOptions = (Object.keys(usageModeLabels) as UsageMode[]).map((m) => ({ label: usageModeLabels[m], value: m }))

function dismiss() {
  dismissed.value = true
  setItem(SETUP_DISMISSED_KEY, '1')
}
</script>

<template>
  <section v-if="visible" class="setup">
    <header class="head">
      <div>
        <h3>开始使用</h3>
        <span class="muted small">已完成 {{ doneCount }} / {{ required.length }} 步</span>
      </div>
      <div class="head-right">
        <el-segmented
          :model-value="prefs.mode"
          :options="modeOptions"
          size="small"
          @change="(v: string | number | boolean) => prefs.setMode(v as UsageMode)"
        />
        <el-button link :icon="Close" aria-label="不再显示" title="不再显示" @click="dismiss" />
      </div>
    </header>
    <el-progress :percentage="Math.round((doneCount / Math.max(1, required.length)) * 100)" :show-text="false" :stroke-width="4" />
    <ol class="steps">
      <li v-for="(s, i) in steps" :key="s.key" class="step" :class="{ done: s.done }">
        <span class="mark">
          <el-icon v-if="s.done"><Check /></el-icon>
          <template v-else>{{ i + 1 }}</template>
        </span>
        <div class="text">
          <div class="title">
            {{ s.title }}<el-tag v-if="s.optional" size="small" type="info" class="opt">可选</el-tag>
          </div>
          <div class="desc">{{ s.desc }}</div>
        </div>
        <el-button v-if="!s.done" size="small" :type="s.optional ? 'default' : 'primary'" plain @click="router.push(s.to)">
          {{ s.action }}
        </el-button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.setup {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
  padding: var(--xh-space-4);
  background: var(--xh-card);
  border: 1px solid var(--xh-primary-border);
  border-radius: var(--xh-radius-md);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--xh-space-2);
}
.head h3 {
  display: inline;
  margin: 0 var(--xh-space-2) 0 0;
  font-size: var(--xh-fs-lg);
  color: var(--xh-text);
}
.head-right {
  display: flex;
  align-items: center;
  gap: var(--xh-space-2);
}
.steps {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--xh-space-2) var(--xh-space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}
.step {
  display: flex;
  align-items: center;
  gap: var(--xh-space-3);
  padding: var(--xh-space-2) 0;
}
.mark {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid var(--xh-border-strong);
  font-size: var(--xh-fs-xs);
  color: var(--xh-text-2);
}
.step.done .mark {
  background: var(--xh-primary);
  border-color: var(--xh-primary);
  color: #fff;
}
.text {
  flex: 1;
  min-width: 0;
}
.title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: var(--xh-text);
}
.step.done .title {
  color: var(--xh-muted);
  text-decoration: line-through;
}
.desc {
  margin-top: 2px;
  font-size: var(--xh-fs-xs);
  line-height: 1.5;
  color: var(--xh-muted);
}
</style>
