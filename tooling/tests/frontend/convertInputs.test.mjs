import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { ref } from 'vue'
import { parse } from 'vue/compiler-sfc'
import { remainingBatchInputs } from '../../frontend/src/features/audio-tools/batchInputs.ts'

const script = parse(readFileSync(new URL('../../../plugins/convert/ui/src/ConvertTool.vue', import.meta.url), 'utf8')).descriptor.scriptSetup.content
const source = ts.createSourceFile('convert.ts', script, ts.ScriptTarget.Latest, true)
const run = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'run')
const code = ts.transpileModule(run.getText(source), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText

function converter(result, selected = ['a.wav', 'b.wav']) {
  const calls = []
  const state = { remainingBatchInputs, inputs: ref([...selected]), outputDir: ref('/output'), outputFormat: ref('mp3'),
    sampleRate: ref(48000), channels: ref(2), wavBitDepth: ref('PCM-24'), flacBitDepth: ref('16-bit'),
    mp3BitRate: ref('320k'), oggBitRate: ref('450k'),
    runtime: { async execute(tool, payload) { calls.push({ tool, payload }); return typeof result === 'function' ? await result() : result } },
  }
  const { run } = vm.runInNewContext(`${code}\n({run})`, state)
  return { ...state, calls, run }
}

test('successful conversion clears the submitted files and preserves conversion settings', async () => {
  const h = converter({ operation: 'convert', succeeded: 2, failed: [] })
  await h.run()
  assert.deepEqual(h.inputs.value, [])
  assert.equal(h.outputDir.value, '/output')
  assert.equal(h.outputFormat.value, 'mp3')
  assert.equal(h.sampleRate.value, 48000)
  assert.equal(h.mp3BitRate.value, '320k')
})

test('failed or cancelled conversions retain the inputs', async () => {
  for (const result of [null, { operation: 'convert', succeeded: 0, failed: [{ path: 'a.wav' }, { path: 'b.wav' }] }]) {
    const h = converter(result)
    await h.run()
    assert.deepEqual(h.inputs.value, ['a.wav', 'b.wav'])
  }
})

test('partial success keeps failed and skipped files available for retry', async () => {
  const h = converter({ operation: 'convert', succeeded: 1, failed: [{ path: 'b.wav' }], skipped: [{ path: 'c.wav' }] }, ['a.wav', 'b.wav', 'c.wav'])
  await h.run()
  assert.deepEqual(h.inputs.value, ['b.wav', 'c.wav'])
})

test('files added while conversion completes are not cleared or included in its request', async () => {
  let finish
  const h = converter(() => new Promise(resolve => { finish = resolve }))
  const task = h.run()
  h.inputs.value.push('next.wav')
  assert.deepEqual(Array.from(h.calls[0].payload.inputs), ['a.wav', 'b.wav'])
  finish({ operation: 'convert', succeeded: 2, failed: [] })
  await task
  assert.deepEqual(h.inputs.value, ['next.wav'])
})

test('inconsistent or unrecognized completion reports do not clear user inputs', async () => {
  for (const result of [
    { operation: 'convert', succeeded: 1, failed: [] },
    { operation: 'convert', succeeded: 1, failed: [{ path: '/normalized/b.wav' }] },
    { operation: 'inspect', succeeded: 2 },
  ]) {
    const h = converter(result)
    await h.run()
    assert.deepEqual(h.inputs.value, ['a.wav', 'b.wav'])
  }
})
