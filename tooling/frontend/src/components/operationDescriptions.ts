/** Cache descriptions for the lifetime of one mounted tool, including in-flight requests. */
export function operationDescriptions<T>(load: (operation: string) => Promise<T>) {
  const resolved = new Map<string, T>()
  const pending = new Map<string, Promise<T>>()
  return {
    peek: (operation: string) => resolved.get(operation),
    get(operation: string): Promise<T> {
      if (resolved.has(operation)) return Promise.resolve(resolved.get(operation)!)
      const existing = pending.get(operation)
      if (existing) return existing
      const request = Promise.resolve().then(() => load(operation)).then(value => {
        resolved.set(operation, value)
        return value
      }).finally(() => pending.delete(operation))
      pending.set(operation, request)
      return request
    },
  }
}
