import client from './client'

// Share only public manifest requests. Each subscriber keeps its own abort
// signal; one component unmounting cannot cancel another component's request.
const flights = new Map()
export function sharedManifest(url, params = {}, config = {}) {
  const key = JSON.stringify([url, Object.entries(params).sort()])
  let flight = flights.get(key)
  if (!flight) {
    const controller = new AbortController()
    const {signal, ...rest} = config
    flight = {controller, users: 0}
    flight.promise = client.get(url, {...rest, params, signal: controller.signal})
      .finally(() => { if (flights.get(key) === flight) flights.delete(key) })
    flights.set(key, flight)
  }
  flight.users++
  return new Promise((resolve, reject) => {
    let done = false
    const finish = (fn, value) => {
      if (done) return
      done = true
      config.signal?.removeEventListener('abort', abort)
      flight.users--
      fn(value)
      if (!flight.users && flights.get(key) === flight && config.signal?.aborted) {
        flights.delete(key); flight.controller.abort()
      }
    }
    const abort = () => finish(reject, new DOMException('Request aborted', 'AbortError'))
    config.signal?.addEventListener('abort', abort, {once: true})
    flight.promise.then(v => finish(resolve, v), e => finish(reject, e))
    if (config.signal?.aborted) abort()
  })
}
