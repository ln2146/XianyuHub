<script setup lang="ts">
import { computed } from 'vue'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
const props = defineProps<{ value: string | null | undefined; map: Record<string, { label: string; type: TagType }> }>()
const meta = computed(() => (props.value ? props.map[props.value] : undefined))
</script>

<template>
  <el-tag :type="meta?.type || 'info'" size="small" disable-transitions>{{ meta?.label || value || '-' }}</el-tag>
</template>
