import assert from 'node:assert/strict'
import test from 'node:test'
import { operationDescriptions } from '../../frontend/src/components/operationDescriptions.ts'

test('operation metadata requests are deduplicated and cached for immediate switching back', async () => {
  let calls = 0, resolve
  const descriptions = operationDescriptions(() => { calls++; return new Promise(done => { resolve = done }) })
  const first = descriptions.get('one'), second = descriptions.get('one')
  assert.equal(first, second)
  await Promise.resolve()
  assert.equal(calls, 1)
  resolve({ id: 'one' })
  await first
  assert.deepEqual(descriptions.peek('one'), { id: 'one' })
  assert.deepEqual(await descriptions.get('one'), { id: 'one' })
  assert.equal(calls, 1)
})

test('failed metadata remains retryable and operations do not share cached schemas', async () => {
  const requests = []
  const descriptions = operationDescriptions(async operation => {
    requests.push(operation)
    if (requests.length === 1) throw Error('worker unavailable')
    return { id: operation }
  })
  await assert.rejects(descriptions.get('one'), /worker unavailable/)
  assert.equal(descriptions.peek('one'), undefined)
  assert.deepEqual(await descriptions.get('one'), { id: 'one' })
  assert.deepEqual(await descriptions.get('two'), { id: 'two' })
  assert.deepEqual(requests, ['one', 'one', 'two'])
})
