<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { TerminalOutline } from '@vicons/ionicons5'
import { useMessage } from 'naive-ui'
import { openToolOverlay, closeToolOverlay } from '../sdk'

defineProps<{ busy?: boolean; percentage?: number | null }>()
const { t } = useI18n()
const message = useMessage()
const show = ref(false)
const opening = ref(false)
let disposed = false
async function openLog() {
  if (opening.value || show.value) return
  opening.value = true
  try {
    await openToolOverlay()
    if (!disposed) show.value = true
  } catch (error) {
    if (!disposed) message.error(error instanceof Error ? error.message : String(error))
  } finally { opening.value = false }
}
onBeforeUnmount(() => { disposed = true; closeToolOverlay() })
</script>
<template>
  <n-button class="tool-log-button" secondary size="small" :loading="opening" :type="busy ? 'primary' : 'default'" @click="openLog">
    <template #icon><n-icon :component="TerminalOutline" /></template>
    {{ t('tools.logButton') }}<span v-if="busy && percentage != null" class="tool-log-percentage">{{ percentage }}%</span><span v-else-if="busy" class="tool-log-running" aria-hidden="true" />
  </n-button>
  <n-modal v-model:show="show" preset="card" :title="t('tools.activityLog')" class="tool-activity-dialog" :style="{ width: 'min(760px, calc(100vw - 32px))', maxHeight: 'calc(100dvh - 48px)' }" :content-style="{ overflow: 'auto', minHeight: '0' }" @after-leave="closeToolOverlay">
    <slot v-if="show" />
  </n-modal>
</template>
<style scoped>
.tool-log-button { gap: 4px; }
.tool-log-percentage { margin-left: 7px; font-variant-numeric: tabular-nums; }
.tool-log-running { width: 6px; height: 6px; margin-left: 8px; border-radius: 50%; background: currentColor; }
</style>
