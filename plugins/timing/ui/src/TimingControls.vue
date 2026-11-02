<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ params: Record<string, unknown>; errors: Record<string, string>; disabled: boolean }>()
const { t } = useI18n()
const radius = computed(() => props.params.algorithm === 'radius')
const algorithms = computed(() => ['rubberband', 'radius'].map(value => ({ value, label: t(`plugin.algorithms.${value}`) })))
watch(() => [props.params.algorithm, props.params.speed_percent], () => {
  if (radius.value && props.params.speed_percent !== 100) props.params.speed_percent = 100
}, { immediate: true, flush: 'sync' })
</script>

<template>
  <div class="audio-tool-field">
    <label for="param-algorithm">{{ t('parameters.algorithm') }}</label>
    <n-select id="param-algorithm" :value="String(params.algorithm || 'rubberband')" :options="algorithms" :disabled="disabled" @update:value="params.algorithm = $event" />
    <small class="timing-hint">{{ t('plugin.algorithmHint') }}</small>
  </div>
  <div class="audio-tool-grid">
    <div class="audio-tool-field">
      <label for="param-n_steps">{{ t('parameters.n_steps') }}</label>
      <n-input-number id="param-n_steps" :value="params.n_steps as number | null" :disabled="disabled" :min="-24" :max="24" :step="0.5" @update:value="params.n_steps = $event" />
      <small v-if="errors.n_steps" class="timing-error">{{ t('pluginTools.invalid') }}</small>
    </div>
    <div class="audio-tool-field">
      <label for="param-speed_percent">{{ t('parameters.speed_percent') }}</label>
      <n-input-number id="param-speed_percent" :value="params.speed_percent as number | null" :disabled="disabled || radius" :min="25" :max="400" :step="1" @update:value="params.speed_percent = $event" />
      <small class="timing-hint">{{ t(radius ? 'plugin.radiusSpeedHint' : 'plugin.speedHint') }}</small>
      <small v-if="errors.speed_percent" class="timing-error">{{ t('pluginTools.invalid') }}</small>
    </div>
  </div>
</template>

<style scoped>
.timing-hint { display: block; margin-top: 6px; color: var(--on-surface-muted); font-size: 12px; line-height: 1.6; }
.timing-error { color: var(--danger); font-size: 12px; }
</style>
