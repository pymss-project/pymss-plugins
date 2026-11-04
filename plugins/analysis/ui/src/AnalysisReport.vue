<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { measurementRows, spectrumChart, spectrumSample, reportText } from './report'

const props = defineProps<{ operation: string; name: string | number; output: { kind?: string; value?: unknown } }>()
const { t, locale } = useI18n()
const value = computed(() => props.output.kind === 'object' ? props.output.value : undefined)
const rows = computed(() => props.name === 'report' ? measurementRows(props.operation, value.value, locale.value) : null)
const chart = computed(() => props.name === 'report' && props.operation === 'pymss.analysis.spectrum' ? spectrumChart(value.value) : null)
const raw = computed(() => reportText(props.output.value ?? props.output))
const formatFrequency = (value: number) => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }).format(value)
const formatSample = (value: number) => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 2 }).format(value)
const inspectedFrequency = ref<number | null>(null)
const cursor = computed(() => {
  if (!chart.value || inspectedFrequency.value === null) return null
  const sample = spectrumSample(chart.value, inspectedFrequency.value)
  return sample && { ...sample,
    x: 50 + sample.frequency / chart.value.maximumFrequency * 700,
    y: 20 + (chart.value.maximumDb - sample.magnitudeDb) / (chart.value.maximumDb - chart.value.minimumDb) * 200,
  }
})
watch(chart, () => { inspectedFrequency.value = null })
function inspectSpectrum(event: PointerEvent) {
  const matrix = (event.currentTarget as SVGSVGElement).getScreenCTM()
  if (!chart.value || !matrix) return
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
  inspectedFrequency.value = point.x >= 50 && point.x <= 750 && point.y >= 20 && point.y <= 220
    ? (point.x - 50) / 700 * chart.value.maximumFrequency : null
}
</script>
<template>
  <template v-if="rows">
    <dl class="analysis-measurements">
      <div v-for="row in rows" :key="row.key" class="analysis-measurement">
        <dt>{{ t(`analysis.metrics.${row.key}`) }}</dt>
        <dd><strong>{{ row.text }}</strong><span v-if="row.unit">{{ row.unit }}</span></dd>
      </div>
    </dl>
    <p class="analysis-hint">{{ t(`analysis.hints.${operation.split('.').at(-1)}`) }}</p>
  </template>
  <template v-else-if="chart">
    <strong>{{ t('plugin.operations.spectrum') }}</strong>
    <div class="analysis-spectrum-wrap">
      <svg class="analysis-spectrum" viewBox="0 0 780 270" role="img" :aria-label="t('analysis.spectrumLabel')"
        @pointermove="inspectSpectrum" @pointerdown="inspectSpectrum" @pointerleave="inspectedFrequency = null" @pointercancel="inspectedFrequency = null">
        <g class="analysis-spectrum-grid">
          <line x1="50" y1="20" x2="750" y2="20" /><line x1="50" y1="120" x2="750" y2="120" /><line x1="50" y1="220" x2="750" y2="220" /><line x1="50" y1="20" x2="50" y2="220" />
        </g>
        <g class="analysis-spectrum-labels">
          <text x="40" y="24" text-anchor="end">{{ chart.maximumDb }}</text><text x="40" y="124" text-anchor="end">{{ (chart.maximumDb + chart.minimumDb) / 2 }}</text><text x="40" y="224" text-anchor="end">{{ chart.minimumDb }}</text>
          <text x="50" y="245">0 Hz</text><text x="400" y="245" text-anchor="middle">{{ formatFrequency(chart.maximumFrequency / 2) }} Hz</text><text x="750" y="245" text-anchor="end">{{ formatFrequency(chart.maximumFrequency) }} Hz</text><text x="10" y="12">dB</text>
        </g>
        <polyline :points="chart.points" fill="none" class="analysis-spectrum-line" />
        <g v-if="cursor" class="analysis-spectrum-cursor" aria-hidden="true">
          <line :x1="cursor.x" y1="20" :x2="cursor.x" y2="220" />
          <circle :cx="cursor.x" :cy="cursor.y" r="4" />
        </g>
      </svg>
      <div v-if="cursor" class="analysis-spectrum-tooltip" :style="{ left: `clamp(8px, ${cursor.x / 780 * 100}%, calc(100% - 188px))` }">
        <dl>
          <div><dt>{{ t('analysis.frequency') }}</dt><dd>{{ formatSample(cursor.frequency) }} Hz</dd></div>
          <div><dt>{{ t('analysis.magnitude') }}</dt><dd>{{ formatSample(cursor.magnitudeDb) }} dB</dd></div>
        </dl>
      </div>
    </div>
    <p class="analysis-hint">{{ t('analysis.spectrumHint') }}</p>
  </template>
  <pre v-else class="tool-result-json">{{ raw }}</pre>
  <details v-if="rows || chart" class="analysis-raw"><summary>{{ t('analysis.rawData') }}</summary><pre class="tool-result-json">{{ raw }}</pre></details>
</template>
<style scoped>
.analysis-measurements { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin: 0; }
.analysis-measurement dt { color: var(--on-surface-muted); font-size: 12px; margin-bottom: 10px; }
.analysis-measurement dd { display: flex; align-items: baseline; gap: 8px; margin: 0; }
.analysis-measurement strong { font-size: 26px; font-variant-numeric: tabular-nums; }
.analysis-measurement dd span { color: var(--on-surface-muted); font-size: 12px; }
.analysis-hint { color: var(--on-surface-muted); font-size: 12px; line-height: 1.7; margin: 14px 0 0; }
.analysis-raw { margin-top: 14px; font-size: 12px; color: var(--on-surface-muted); }
.analysis-raw summary { cursor: pointer; }
.analysis-raw pre { max-height: 260px; overflow: auto; }
.analysis-spectrum-wrap { position: relative; margin-top: 16px; }
.analysis-spectrum { display: block; width: 100%; }
.analysis-spectrum-grid { stroke: var(--outline); stroke-width: 1; }
.analysis-spectrum-labels { fill: var(--on-surface-muted); font-size: 12px; }
.analysis-spectrum-line { stroke: var(--primary); stroke-width: 2; vector-effect: non-scaling-stroke; }
.analysis-spectrum-cursor { pointer-events: none; stroke: var(--primary); vector-effect: non-scaling-stroke; }
.analysis-spectrum-cursor line { stroke-dasharray: 4 4; }
.analysis-spectrum-cursor circle { fill: var(--surface-1); stroke-width: 2; }
.analysis-spectrum-tooltip { position: absolute; top: 32px; width: 180px; max-width: calc(100% - 16px); box-sizing: border-box; padding: 10px 12px; border: 1px solid var(--outline); border-radius: 8px; background: var(--surface-1); color: var(--on-surface); box-shadow: var(--shadow-panel); font-size: 12px; pointer-events: none; }
.analysis-spectrum-tooltip dl { display: grid; gap: 6px; margin: 0; }
.analysis-spectrum-tooltip dl > div { display: flex; justify-content: space-between; gap: 12px; }
.analysis-spectrum-tooltip dt { color: var(--on-surface-muted); }
.analysis-spectrum-tooltip dd { margin: 0; font-variant-numeric: tabular-nums; }
</style>
