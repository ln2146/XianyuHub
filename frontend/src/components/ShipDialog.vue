<script setup lang="ts">
// 实物订单发货：网页端没有填运单号的功能，这里给出收货信息（一键复制）和扫码去闲鱼 App 发货
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Refresh } from '@element-plus/icons-vue'
import QRCode from 'qrcode'
import { getShipping, syncOrders, type Order, type ShippingInfo } from '@/api/order'

const props = defineProps<{ modelValue: boolean; order: Order | null }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'refreshed'): void
}>()

const open = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) })
const info = ref<ShippingInfo | null>(null)
const qr = ref('')
const loading = ref(false)
const syncing = ref(false)
const error = ref('')

watch(
  () => [props.modelValue, props.order?.id] as const,
  async ([isOpen]) => {
    if (!isOpen || !props.order) return
    info.value = null
    qr.value = ''
    error.value = ''
    loading.value = true
    try {
      info.value = await getShipping(props.order.id)
      qr.value = await QRCode.toDataURL(info.value.deliver_url, { width: 200, margin: 1 })
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      error.value = err.response?.data?.detail || err.message || '获取收货信息失败'
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

const fullAddress = computed(() => (info.value ? `${info.value.name} ${info.value.phone} ${info.value.address}` : ''))

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制${what}`)
  } catch {
    ElMessage.warning('浏览器不允许自动复制，请手动选中复制')
  }
}

// 在 App 发完货后同步一次订单，状态会变成「已发货」
async function shipped() {
  if (!props.order) return
  syncing.value = true
  try {
    await syncOrders(props.order.account_id)
    emit('refreshed')
    open.value = false
    ElMessage.success('已同步订单状态')
  } finally {
    syncing.value = false
  }
}
</script>

<template>
  <el-dialog v-model="open" title="去发货" width="460px" append-to-body align-center>
    <div v-loading="loading" class="body">
      <p class="muted small sub">
        闲鱼网页版不支持填写运单号，实物订单需要在闲鱼 App 里发货。寄出包裹后，用手机扫下面的二维码，选快递公司、填运单号即可。
      </p>
      <p v-if="error" class="err small">{{ error }}</p>

      <template v-if="info">
        <section class="addr">
          <div class="addr-head">
            <span class="label">收货信息</span>
            <el-button size="small" type="primary" plain :icon="CopyDocument" @click="copy(fullAddress, '收货信息')">一键复制</el-button>
          </div>
          <div class="line"><span class="k">收货人</span><span class="v">{{ info.name || '-' }}</span></div>
          <div class="line">
            <span class="k">电话</span><span class="v mono">{{ info.phone || '-' }}</span>
            <el-button v-if="info.phone" link size="small" @click="copy(info.phone, '电话')">复制</el-button>
          </div>
          <div class="line">
            <span class="k">地址</span><span class="v">{{ info.address || '-' }}</span>
            <el-button v-if="info.address" link size="small" @click="copy(info.address, '地址')">复制</el-button>
          </div>
        </section>

        <section class="scan">
          <img v-if="qr" :src="qr" class="qr" alt="扫码去闲鱼 App 发货" />
          <ol class="steps">
            <li>打包寄出，拿到快递单号</li>
            <li>用登录这个账号的闲鱼 App 扫左边二维码</li>
            <li>选快递公司、填运单号，确认发货</li>
          </ol>
        </section>
        <p class="muted smaller">收货信息仅用于寄件，请勿外传。发货后系统每 10 分钟同步一次订单，也可以点下面的按钮立即刷新。</p>
      </template>
    </div>
    <template #footer>
      <el-button @click="open = false">关闭</el-button>
      <el-button type="primary" :icon="Refresh" :loading="syncing" :disabled="!order" @click="shipped">我已在 App 发货，刷新状态</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.body {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-3);
  min-height: 120px;
}
.sub {
  margin: 0;
  line-height: 1.6;
}
.err {
  margin: 0;
  color: var(--xh-danger);
}
.addr {
  display: flex;
  flex-direction: column;
  gap: var(--xh-space-1);
  padding: var(--xh-space-3);
  border-radius: var(--xh-radius-md);
  background: var(--xh-fill);
}
.addr-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--xh-space-1);
}
.label {
  font-weight: 600;
  color: var(--xh-text);
}
.line {
  display: flex;
  align-items: baseline;
  gap: var(--xh-space-2);
  font-size: var(--xh-fs-sm);
}
.k {
  flex-shrink: 0;
  width: 48px;
  color: var(--xh-muted);
}
.v {
  flex: 1;
  min-width: 0;
  color: var(--xh-text);
  word-break: break-all;
}
.scan {
  display: flex;
  align-items: center;
  gap: var(--xh-space-4);
}
.qr {
  width: 140px;
  height: 140px;
  flex-shrink: 0;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
}
.steps {
  margin: 0;
  padding-left: 18px;
  font-size: var(--xh-fs-sm);
  line-height: 1.9;
  color: var(--xh-text);
}
.smaller {
  margin: 0;
  font-size: var(--xh-fs-xs);
}
.mono {
  font-family: var(--xh-font-mono, monospace);
}
</style>
