import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { parse } from 'vue/compiler-sfc'

const source = parse(readFileSync(new URL('../../../plugins/slicer/ui/src/SlicerTool.vue', import.meta.url), 'utf8')).descriptor.scriptSetup.content
const code = ts.transpileModule(`${source}\nexports.valid = valid; exports.run = run;`, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText

function slicer(completion) {
  const values = new Map(), calls = [], exports = {}
  vm.runInNewContext(code, {
    exports,
    require: name => ({
      '@/sdk': { toolRef: (key, value) => { const ref = { value }; values.set(key, ref); return ref } },
      vue: { computed: getter => ({ get value() { return getter() } }), watch() {} },
      'vue-i18n': { useI18n: () => ({ t: key => key }) },
      'naive-ui': { useMessage: () => ({ error() {} }) },
      '@/stores/settings': { useSettingsStore: () => ({ outputDir: '/output' }) },
      '@/features/audio-tools/runtime': { useAudioToolRuntime: () => ({
        stateFor: () => ({}),
        execute: (...args) => { calls.push(args); return completion?.() },
      }) },
      '@/features/audio-tools/useAudioInputDrop': { useAudioInputDrop: () => ({ dropZone: { value: null }, dragging: { value: false }, scanning: { value: false } }) },
    })[name] || {},
  })
  return { ...exports, values, calls }
}

test('slicer refuses cleared and non-finite numeric controls before starting an operation', () => {
  const { valid, run, values, calls } = slicer()
  assert.equal(valid.value, true)
  for (const name of ['threshold', 'minLength', 'minInterval', 'hopSize', 'maxSilKept']) {
    const ref = values.get(name), original = ref.value
    for (const value of [null, undefined, NaN, Infinity, -Infinity, false, '10']) {
      ref.value = value
      assert.equal(valid.value, false, `${name}=${String(value)}`)
      run()
      assert.equal(calls.length, 0)
    }
    ref.value = original
  }
  values.get('threshold').value = -40.5
  assert.equal(valid.value, true)
  run()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].threshold, -40.5)
})

test('slicer requires integer timings and preserves the ordering constraints', () => {
  const { valid, values } = slicer()
  for (const name of ['minLength', 'minInterval', 'hopSize', 'maxSilKept']) {
    const ref = values.get(name), original = ref.value
    ref.value += 0.5
    assert.equal(valid.value, false, name)
    ref.value = original
  }
  values.get('hopSize').value = 301
  assert.equal(valid.value, false)
  values.get('hopSize').value = 10
  values.get('threshold').value = 0
  assert.equal(valid.value, true)
})

test('slicer only clears submitted inputs that produced clips, including paths resolved by the backend', async () => {
  const selected = ['/audio/session/../normal.wav', '/audio/quiet.wav']
  let finish
  const { run, values, calls } = slicer(() => new Promise(resolve => { finish = resolve }))
  const inputs = values.get('inputs')
  inputs.value = [...selected]
  const task = run()
  inputs.value.push('/audio/next.wav')
  assert.deepEqual(Array.from(calls[0][1].inputs), selected)
  finish({
    operation: 'slicer', sourceCount: 2, processedInputs: [selected[0]],
    segments: [{ sourcePath: '/audio/normal.wav' }],
  })
  await task
  assert.deepEqual(Array.from(inputs.value), [selected[1], '/audio/next.wav'])
})

test('slicer preserves inputs after cancellation or a result with no clips', async () => {
  const selected = ['/audio/quiet.wav']
  for (const result of [null, { operation: 'slicer', sourceCount: 1, processedInputs: [], segments: [] }]) {
    const { run, values } = slicer(() => result)
    const inputs = values.get('inputs')
    inputs.value = [...selected]
    await run()
    assert.deepEqual(Array.from(inputs.value), selected)
  }
})
