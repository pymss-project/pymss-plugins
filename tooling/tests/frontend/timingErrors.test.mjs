import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createI18n } from 'vue-i18n'
import { timingErrorMessage } from '../../../plugins/timing/ui/src/errors.ts'

const messages = Object.fromEntries(['zh-CN', 'en'].map(locale => [locale,
  JSON.parse(readFileSync(new URL(`../../../plugins/timing/ui/src/locales/${locale}.json`, import.meta.url), 'utf8')),
]))

test('Radius compatibility failures show localized versions and actionable guidance', () => {
  for (const locale of ['zh-CN', 'en']) {
    const i18n = createI18n({ legacy: false, locale, messages })
    const translate = (key, values) => i18n.global.t(key, values)
    const failure = Object.assign(new Error('raw native failure'), {
      code: 'TIMING_RADIUS_GLIBC_UNSUPPORTED', data: { requiredGlibc: '2.43', currentGlibc: '2.35' },
    })
    const result = timingErrorMessage(failure, translate)
    assert.match(result, /2\.43/)
    assert.match(result, /2\.35/)
    assert.match(result, /PYMSS_RADIUS/)
    assert.ok(result.startsWith(locale === 'zh-CN' ? '内置 Radius' : 'Bundled Radius'))
    assert.doesNotMatch(result, /raw native failure|\{required\}|\{current\}/)
    const unavailable = timingErrorMessage({ code: 'TIMING_RADIUS_GLIBC_UNAVAILABLE', data: { requiredGlibc: '2.43' } }, translate)
    assert.match(unavailable, /2\.43/)
    assert.match(unavailable, /PYMSS_RADIUS/)
    assert.match(timingErrorMessage({ code: 'TIMING_RADIUS_RUNTIME_INVALID' }, translate), locale === 'zh-CN' ? /重新安装/ : /Reinstall/)
  }
})

test('unrelated or incomplete errors retain their original diagnostic message', () => {
  const translate = () => { throw new Error('unexpected translation') }
  for (const error of [
    new Error('native failure'),
    { code: 'OTHER_ERROR', message: 'native failure' },
    { code: 'TIMING_RADIUS_GLIBC_UNSUPPORTED', message: 'native failure', data: { requiredGlibc: '2.43' } },
    { code: 'TIMING_RADIUS_GLIBC_UNAVAILABLE', message: 'native failure', data: { requiredGlibc: 2.43 } },
  ]) assert.equal(timingErrorMessage(error, translate), 'native failure')
  assert.equal(timingErrorMessage('raw rejection', translate), 'raw rejection')
  assert.equal(timingErrorMessage(null, translate), 'null')
})
