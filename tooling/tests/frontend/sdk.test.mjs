import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'
import { effectScope, reactive, ref, watch } from 'vue'

const source = ts.createSourceFile('sdk.ts', readFileSync(new URL('../../frontend/src/sdk.ts', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true)
const code = ts.transpileModule(source.statements.filter(statement => !ts.isImportDeclaration(statement)).map(statement => statement.getText(source)).join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText

async function host(t, saved = {}, timers = { setTimeout, clearTimeout }) {
  const scope = effectScope()
  t.after(() => scope.stop())
  const exports = {}, calls = [], callbacks = {}
  const requirements = {
    sdkVersion: 1,
    requiredCapabilities: ['app.info', 'operations.start', 'settings.read', 'settings.write'],
  }
  let settings = saved
  const receive = message => callbacks.message({ source: parent, data: message })
  const parent = { postMessage(message) {
    // Real postMessage structured cloning must succeed, including reactive input lists.
    const request = structuredClone(message)
    calls.push(request)
    queueMicrotask(() => {
      if (request.method === 'pymss.ready') return receive({ jsonrpc: '2.0', method: 'host.ready' })
      const result = request.method === 'app.info' ? {
        sdkVersion: requirements.sdkVersion, capabilities: requirements.requiredCapabilities,
        locale: 'en', defaultOutputDir: '/output',
      }
        : request.method === 'settings.read' ? settings
        : request.method === 'settings.write' ? (settings = request.params.data) : { ok: true }
      receive({ jsonrpc: '2.0', id: request.id, result })
    })
  } }
  const window = { parent, innerWidth: 946, innerHeight: 350,
    addEventListener(name, callback) { callbacks[name] = callback }, removeEventListener(name) { delete callbacks[name] } }
  const properties = new Map(), classes = new Set()
  const document = { documentElement: {
    style: { setProperty: (key, value) => properties.set(key, value), removeProperty: key => properties.delete(key) },
    classList: { toggle: (key, enabled) => enabled ? classes.add(key) : classes.delete(key) },
  } }
  scope.run(() => vm.runInNewContext(code, {
    exports, window, document, structuredClone, ref, watch, ...timers,
    presentation: {}, refreshToolLayout() {}, useSettingsStore: () => ({}), __FILE_TOOL__: 'slicer', __OPERATION_ID__: 'pymss.slicer.tool',
    __STUDIO_REQUIREMENTS__: requirements,
  }))
  await exports.connect()
  return { sdk: exports, calls, scope, receive, properties, classes, window, resize: () => callbacks.resize() }
}

test('log overlays anchor the form without retaining stale or invalid layout coordinates', async t => {
  const { receive, properties, classes, window, resize } = await host(t)
  const send = params => receive({ jsonrpc: '2.0', method: 'host.overlay', params })
  send({ open: true, bounds: { left: 304, top: -30, width: 910 } })
  assert.equal(classes.has('tool-overlay-anchored'), true)
  assert.equal(properties.get('--tool-overlay-top'), '-30px')
  assert.equal(properties.get('--tool-overlay-width'), '910px')
  send({ open: true, bounds: { left: 0, top: 0, width: '100vw' } })
  assert.equal(classes.size, 0)
  assert.equal(properties.size, 0)
  send({ open: true, bounds: { left: 0, top: 0, width: 640 } })
  send({ open: false })
  window.innerWidth = 640
  resize()
  assert.equal(classes.size, 0)
  assert.equal(properties.size, 0)
})

test('log overlays wait for the promoted viewport and keep the form anchored until it returns', async t => {
  const { sdk, receive, calls, window, resize, classes, properties } = await host(t)
  let opened = false
  const opening = sdk.openToolOverlay().then(() => { opened = true })
  const generation = calls.at(-1).params.generation
  receive({ jsonrpc: '2.0', method: 'host.overlay', params: {
    open: true, prepare: true, generation,
    bounds: { left: 302, top: 156, width: 946 }, viewport: { width: 1280, height: 900 },
  } })
  await Promise.resolve()
  assert.equal(opened, false)
  assert.equal(classes.has('tool-overlay-anchored'), false)
  assert.equal(calls.at(-1).params.prepared, generation)
  window.innerWidth = 1280
  window.innerHeight = 900
  resize()
  await opening
  assert.equal(opened, true)
  assert.equal(properties.get('--tool-overlay-left'), '302px')
  sdk.closeToolOverlay()
  receive({ jsonrpc: '2.0', method: 'host.overlay', params: { open: false } })
  assert.equal(classes.has('tool-overlay-anchored'), true)
  window.innerWidth = 946
  window.innerHeight = 350
  resize()
  assert.equal(classes.size, 0)
  assert.equal(properties.size, 0)
})

test('a cancelled overlay ignores its late preparation and legacy hosts still open logs', async t => {
  const { sdk, receive, calls, classes } = await host(t)
  const first = sdk.openToolOverlay()
  const generation = calls.at(-1).params.generation
  sdk.closeToolOverlay()
  await first
  receive({ jsonrpc: '2.0', method: 'host.overlay', params: {
    open: true, prepare: true, generation, bounds: { left: 302, top: 156, width: 946 }, viewport: { width: 1280, height: 900 },
  } })
  assert.equal(classes.size, 0)
  const second = sdk.openToolOverlay()
  receive({ jsonrpc: '2.0', method: 'host.overlay', params: { open: true, bounds: { left: 302, top: 156, width: 946 } } })
  await second
  assert.equal(classes.has('tool-overlay-anchored'), true)
  sdk.closeToolOverlay()
})

test('an unresponsive overlay handshake clears its timer and restores the tool', async t => {
  const timers = new Map()
  let sequence = 0
  const { sdk, classes, calls } = await host(t, {}, {
    setTimeout: callback => { timers.set(++sequence, callback); return sequence },
    clearTimeout: id => timers.delete(id),
  })
  assert.equal(timers.size, 0)
  const opening = sdk.openToolOverlay()
  const failed = assert.rejects(opening, /Studio did not respond/)
  assert.equal(timers.size, 1)
  timers.values().next().value()
  await failed
  assert.equal(timers.size, 0)
  assert.equal(classes.size, 0)
  assert.equal(calls.at(-1).params.open, false)
})

test('closing after a window resize restores a different inline size for synchronized and legacy hosts', async t => {
  for (const synchronized of [true, false]) {
    const { sdk, receive, calls, window, resize, classes } = await host(t)
    const opening = sdk.openToolOverlay()
    window.innerWidth = 1280
    window.innerHeight = 900
    receive({ jsonrpc: '2.0', method: 'host.overlay', params: { open: true,
      ...(synchronized ? { prepare: true, generation: calls.at(-1).params.generation, viewport: { width: 1280, height: 900 } } : {}),
      bounds: { left: 302, top: 156, width: 946 },
    } })
    await opening
    window.innerWidth = 1100
    window.innerHeight = 800
    receive({ jsonrpc: '2.0', method: 'host.overlay', params: { open: true,
      ...(synchronized ? { viewport: { width: 1100, height: 800 } } : {}),
      bounds: { left: 302, top: 156, width: 766 },
    } })
    sdk.closeToolOverlay()
    assert.equal(classes.has('tool-overlay-anchored'), true)
    window.innerWidth = 766
    window.innerHeight = 430
    resize()
    assert.equal(classes.size, 0)
  }
})

test('SDK transports reactive nested inputs as public JSON values', async t => {
  const { sdk, calls } = await host(t)
  await sdk.call('operations.start', reactive({ inputs: { request: { inputs: ['/audio/a.wav'] } } })).promise
  assert.deepEqual(calls.at(-1).params.inputs.request.inputs, ['/audio/a.wav'])
})

test('tool form preferences survive remounts without discarding existing settings', async t => {
  const { sdk, calls, scope } = await host(t, { mergeSortBy: 'regex', form: { inputs: ['/audio/previous.wav'] } })
  const inputs = scope.run(() => sdk.toolRef('inputs', []))
  assert.equal(inputs.value[0], '/audio/previous.wav')
  inputs.value.push('/audio/new.wav')
  const saved = await sdk.readSettings()
  assert.equal(saved.mergeSortBy, 'regex')
  assert.equal(saved.form.inputs.length, 2)
  assert.deepEqual(calls.findLast(request => request.method === 'settings.write').params.data.form.inputs, ['/audio/previous.wav', '/audio/new.wav'])
})

test('invalid stored form values fall back to valid defaults', async t => {
  const { sdk, scope } = await host(t, { form: { inputs: [17], threshold: 'bad', bpm: Infinity, audioPaths: null } })
  scope.run(() => {
    assert.equal(sdk.toolRef('inputs', []).value.length, 0)
    assert.equal(sdk.toolRef('threshold', -40).value, -40)
    assert.equal(sdk.toolRef('bpm', null).value, null)
    assert.equal(Object.keys(sdk.toolRef('audioPaths', {}).value).length, 0)
  })
})
