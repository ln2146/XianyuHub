<script setup lang="ts">
// 闲鱼要求身份认证时的扫码弹窗：与网页版发布页相同的二维码，手机扫码后在闲鱼 App 里完成实名 / 刷脸
import { computed, ref, watch } from 'vue'
import QRCode from 'qrcode'

const props = defineProps<{
  modelValue: boolean
  url: string
  /** 认证后重新执行的操作，如「继续发布」 */
  actionText?: string
  loading?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'done'): void
}>()

const open = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) })
const image = ref('')

watch(
  () => [props.modelValue, props.url] as const,
  async ([isOpen, url]) => {
    if (!isOpen || !url) return
    image.value = await QRCode.toDataURL(url, { width: 220, margin: 1 })
  },
  { immediate: true },
)
</script>

<template>
  <el-dialog v-model="open" title="完成认证才可继续发布" width="400px" append-to-body align-center>
    <div class="body">
      <p class="sub">闲鱼要求账号本人完成实名或刷脸认证后才能发布商品。</p>
      <img v-if="image" :src="image" class="qr" alt="闲鱼身份认证二维码" />
      <ol class="steps">
        <li>用登录这个账号的手机打开闲鱼 App，扫描上方二维码</li>
        <li>按提示完成认证（通常是刷脸）</li>
        <li>回到这里点「我已完成认证」，会自动{{ actionText || '继续发布' }}</li>
      </ol>
      <p class="muted small">扫码没反应时，也可以在闲鱼 App 里点「卖闲置」发布一次，按提示完成认证。</p>
    </div>
    <template #footer>
      <el-button @click="open = false">稍后再说</el-button>
      <el-button type="primary" :loading="loading" @click="emit('done')">我已完成认证</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--xh-space-3);
}
.sub {
  margin: 0;
  font-size: var(--xh-fs-sm);
  color: var(--xh-text-2);
  text-align: center;
}
.qr {
  width: 220px;
  height: 220px;
  border: 1px solid var(--xh-border);
  border-radius: var(--xh-radius-md);
}
.steps {
  align-self: stretch;
  margin: 0;
  padding-left: 20px;
  font-size: var(--xh-fs-sm);
  line-height: 1.8;
  color: var(--xh-text);
}
.small {
  margin: 0;
  font-size: var(--xh-fs-xs);
}
</style>
