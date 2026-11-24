import type { AudioToolResultBase } from './types'

export function remainingBatchInputs(current: string[], submitted: Set<string>, result: AudioToolResultBase): string[] {
  if (!result.succeeded) return current
  const retry = new Set([...(result.failed || []), ...(result.skipped || [])].map(item => item.path))
  // Keep all inputs if the report cannot account for the submitted batch.
  if ([...retry].some(path => !submitted.has(path)) || result.succeeded !== submitted.size - retry.size) return current
  return current.filter(path => !submitted.has(path) || retry.has(path))
}
