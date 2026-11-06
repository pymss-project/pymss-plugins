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

async function host(t, saved = {}, timers = { setTimeout, clearTimeout }, { fileTool = 'slicer', operationId = 'pymss.slicer.tool', respond } = {}) {
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
      // A custom responder returns {result} or {error}, or 'pending' to leave the request open.
      const custom = request.id !== undefined ? respond?.(request, receive) : undefined
      if (custom === 'pending') return
      if (custom) return receive({ jsonrpc: '2.0', id: request.id, ...custom })
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
    presentation: {}, refreshToolLayout() {}, useSettingsStore: () => ({}), __FILE_TOOL__: fileTool, __OPERATION_ID__: operationId,
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

const plain = value => JSON.parse(JSON.stringify(value))
const flush = () => new Promise(setImmediate)
const BPM_OPERATION = 'pymss.tempo_key.detect_bpm'

async function gameHost(t, respond) {
  const fixture = await host(t, {}, undefined, { fileTool: 'midi', operationId: 'pymss.game.tool', respond })
  const events = []
  await fixture.sdk.listen('pymss://worker-event', event => events.push(plain(event.payload)))
  return { ...fixture, events }
}

const detect = (sdk, requestId = 'bpm-1', inputs = ['/audio/vocals.wav']) => sdk.invoke('start_audio_tool', {
  payload: { operation: 'midi', action: 'detect_bpm', inputs, requestId },
})
const report = value => ({ result: { operation: BPM_OPERATION, outputs: { report: { kind: 'object', value } } } })

test('GAME BPM detection starts the tempo_key operation and adapts its report to the page result', async t => {
  const { sdk, calls, events } = await gameHost(t, (request, receive) => {
    if (request.method === 'operations.describe') return { result: { id: request.params.operation } }
    if (request.method === 'operations.start') {
      receive({ jsonrpc: '2.0', method: 'task.progress', params: { id: request.id, event: { type: 'audio_tool_progress',
        payload: { operation: 'tempo_key', phase: 'analyzing_tempo_key', completed: 1, total: 1, current: 'vocals.wav' } } } })
      return report({ bpm: 127.6, roundedBpm: 128, duration: 31.5 })
    }
  })
  assert.deepEqual(plain(await detect(sdk)), { taskId: 'bpm-1', started: true })
  await flush()
  const describe = calls.findIndex(request => request.method === 'operations.describe')
  const start = calls.findIndex(request => request.method === 'operations.start')
  assert.equal(calls[describe].params.operation, BPM_OPERATION)
  assert.ok(describe < start)
  assert.deepEqual(calls[start].params, { operation: BPM_OPERATION, inputs: { audio: '/audio/vocals.wav' }, params: {} })
  assert.equal(calls.some(request => request.method === 'audio.analyze'), false)
  assert.deepEqual(events, [
    { type: 'audio_tool_progress', taskId: 'bpm-1', requestId: 'bpm-1',
      payload: { operation: 'midi', phase: 'analyzing_tempo_key', completed: 1, total: 1, current: 'vocals.wav' } },
    { type: 'audio_tool_result', taskId: 'bpm-1', requestId: 'bpm-1',
      payload: { bpm: 127.6, roundedBpm: 128, duration: 31.5, operation: 'midi', action: 'detect_bpm' } },
  ])
})

test('GAME BPM detection reports a missing provider without starting work', async t => {
  const { sdk, calls, events } = await gameHost(t, request => request.method === 'operations.describe'
    ? { error: { code: -32000, message: 'Unknown operation', data: { code: 'OPERATION_NOT_FOUND' } } } : undefined)
  await assert.rejects(detect(sdk), error => {
    assert.equal(error.code, 'TEMPO_KEY_PROVIDER_UNAVAILABLE')
    assert.equal(error.data.code, 'TEMPO_KEY_PROVIDER_UNAVAILABLE')
    assert.equal(error.data.operation, BPM_OPERATION)
    assert.equal(error.data.causeCode, 'OPERATION_NOT_FOUND')
    assert.match(error.message, /Unknown operation/)
    return true
  })
  await flush()
  assert.equal(calls.some(request => request.method === 'operations.start'), false)
  assert.equal(events.length, 0)
  assert.equal(await sdk.invoke('cancel_task', { taskId: 'bpm-1' }), false)
})

test('GAME BPM detection requires exactly one input and leaves MIDI conversion on its own operation', async t => {
  const { sdk, calls } = await gameHost(t, request => request.method === 'operations.start' ? 'pending' : undefined)
  for (const inputs of [[], ['/a.wav', '/b.wav'], [''], [17]]) {
    await assert.rejects(detect(sdk, 'bpm-invalid', inputs), /exactly one audio file/)
  }
  assert.equal(calls.some(request => request.method === 'operations.describe' || request.method === 'operations.start'), false)
  await sdk.invoke('start_audio_tool', { payload: { operation: 'midi', inputPath: '/audio/vocals.wav', bpm: 96, requestId: 'midi-1' } })
  const start = calls.find(request => request.method === 'operations.start')
  assert.equal(start.params.operation, 'pymss.game.tool')
  assert.equal(start.params.inputs.request.bpm, 96)
  assert.equal(calls.some(request => request.method === 'operations.describe'), false)
})

test('invalid BPM reports become structured errors instead of results', async t => {
  const values = [{ bpm: 120, roundedBpm: 400 }, { bpm: 120.4, roundedBpm: 120.4 }, { bpm: null, roundedBpm: 120 },
    { bpm: 120, roundedBpm: '120' }, { bpm: -1, roundedBpm: 120 }, { bpm: 0, roundedBpm: 120 },
    { bpm: 85, roundedBpm: 120 }, {}, null,
    ...[undefined, NaN, Infinity, -1, 0, 4, 29.9, 1801, '31'].map(duration => ({ bpm: 120, roundedBpm: 120, duration }))]
  let index = 0
  const { sdk, events } = await gameHost(t, request => {
    if (request.method === 'operations.describe') return { result: {} }
    if (request.method === 'operations.start') return report(values[index++])
  })
  for (let item = 0; item < values.length; item += 1) {
    await detect(sdk, `bpm-${item}`)
    await flush()
  }
  assert.equal(events.length, values.length)
  for (const event of events) {
    assert.equal(event.type, 'error')
    assert.equal(event.payload.code, 'TEMPO_KEY_INVALID_OUTPUT')
    assert.equal(event.payload.operation, 'midi')
  }
})

test('GAME identifies an unloaded BPM provider after static discovery succeeded', async t => {
  const { sdk, events } = await gameHost(t, request => {
    if (request.method === 'operations.describe') return { result: {} }
    if (request.method === 'operations.start') return { error: { code: -32000, message: 'unknown operation',
      data: { code: 'OPERATION_UNAVAILABLE', operation: BPM_OPERATION } } }
  })
  await detect(sdk)
  await flush()
  assert.equal(events.length, 1)
  assert.equal(events[0].type, 'error')
  assert.equal(events[0].payload.code, 'TEMPO_KEY_PROVIDER_UNAVAILABLE')
  assert.equal(events[0].payload.causeCode, 'OPERATION_UNAVAILABLE')
  assert.equal(events[0].payload.operation, 'midi')
})

test('backend failures keep their code and structured fields through the worker event bridge', async t => {
  const { sdk, events } = await gameHost(t, request => {
    if (request.method === 'operations.describe') return { result: {} }
    if (request.method === 'operations.start') return { error: { code: -32000, message: 'rba requires glibc 2.28',
      data: { code: 'TEMPO_KEY_RBA_GLIBC_UNSUPPORTED', requiredGlibc: '2.28', currentGlibc: '2.17' } } }
  })
  await detect(sdk)
  await flush()
  assert.deepEqual(events, [{ type: 'error', taskId: 'bpm-1', requestId: 'bpm-1', payload: {
    code: 'TEMPO_KEY_RBA_GLIBC_UNSUPPORTED', requiredGlibc: '2.28', currentGlibc: '2.17',
    message: 'rba requires glibc 2.28', operation: 'midi',
  } }])
})

test('cancelling GAME BPM detection cancels the tempo_key operation and reports task_cancelled', async t => {
  let started
  const { sdk, calls, events, receive } = await gameHost(t, request => {
    if (request.method === 'operations.describe') return { result: {} }
    if (request.method === 'operations.start') { started = request; return 'pending' }
    if (request.method === 'operations.cancel') return { result: true }
  })
  await detect(sdk)
  await flush()
  assert.equal(started.params.operation, BPM_OPERATION)
  assert.equal(await sdk.invoke('cancel_task', { taskId: 'bpm-1' }), true)
  assert.equal(calls.findLast(request => request.method === 'operations.cancel').params.id, started.id)
  receive({ jsonrpc: '2.0', id: started.id, error: { code: -32000, message: 'Task cancelled', data: { code: 'TASK_CANCELLED' } } })
  await flush()
  assert.deepEqual(events.map(event => event.type), ['task_cancelled'])
  assert.equal(events[0].payload.operation, 'midi')
  assert.equal(await sdk.invoke('cancel_task', { taskId: 'bpm-1' }), false)
})

test('the tempo_key page uses its own tool operation and no longer exposes audio.analyze', async t => {
  const { sdk, calls } = await host(t, {}, undefined, {
    fileTool: 'tempo_key', operationId: 'pymss.tempo_key.tool',
    respond: request => request.method === 'operations.start' ? 'pending' : undefined,
  })
  await sdk.invoke('start_audio_tool', { payload: { operation: 'tempo_key', inputs: ['/audio/a.wav'], requestId: 'tk-1' } })
  const start = calls.find(request => request.method === 'operations.start')
  assert.equal(start.params.operation, 'pymss.tempo_key.tool')
  assert.deepEqual(start.params.inputs.request.inputs, ['/audio/a.wav'])
  assert.deepEqual(start.params.params, {})
  assert.equal(calls.some(request => request.method === 'operations.describe' || request.method === 'audio.analyze'), false)
  await assert.rejects(sdk.invoke('start_tempo_key_analysis', { payload: { operation: 'tempo_key', requestId: 'tk-2' } }), /Unsupported Studio tool service/)
})
