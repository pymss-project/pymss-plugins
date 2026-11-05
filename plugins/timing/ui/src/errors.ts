type Failure = { code?: unknown; message?: unknown; data?: Record<string, unknown> }
type Translate = (key: string, values: Record<string, string>) => string

export function timingErrorMessage(failure: unknown, translate: Translate): string {
  const error = failure as Failure | null
  const required = error?.data?.requiredGlibc
  const current = error?.data?.currentGlibc
  const version = (value: unknown): value is string => typeof value === 'string' && /^\d+\.\d+$/.test(value)
  if (error?.code === 'TIMING_RADIUS_RUNTIME_INVALID') return translate('plugin.errors.radiusRuntimeInvalid', {})
  if (error?.code === 'TIMING_RADIUS_GLIBC_UNAVAILABLE' && version(required)) {
    return translate('plugin.errors.radiusGlibcUnavailable', { required })
  }
  if (error?.code === 'TIMING_RADIUS_GLIBC_UNSUPPORTED' && version(required) && version(current)) {
    return translate('plugin.errors.radiusGlibcUnsupported', { required, current })
  }
  return typeof error?.message === 'string' ? error.message : String(failure)
}
