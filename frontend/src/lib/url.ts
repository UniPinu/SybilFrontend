import { useCallback, useSyncExternalStore } from 'react'

/** The query string is the app's router: `?p=` is the story page, `?view=explore`
 *  (plus `participant`, `blind` and the search filters) is Explore. Keeping it in
 *  the URL makes every view linkable and the back button work. */

const EVENT = 'urlchange'

function subscribe(callback: () => void) {
  window.addEventListener('popstate', callback)
  window.addEventListener(EVENT, callback)
  return () => {
    window.removeEventListener('popstate', callback)
    window.removeEventListener(EVENT, callback)
  }
}

const snapshot = () => window.location.search

export type ParamUpdate = Record<string, string | number | boolean | null | undefined>

function write(params: URLSearchParams, replace: boolean, state: object = {}) {
  const query = params.toString()
  const url = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`
  if (replace) window.history.replaceState(state, '', url)
  else window.history.pushState(state, '', url)
  window.dispatchEvent(new Event(EVENT))
}

/** Merge into the current query; null, undefined, false and '' remove a key. */
export function setParams(
  update: ParamUpdate,
  { replace = false, state }: { replace?: boolean; state?: object } = {},
) {
  const params = new URLSearchParams(window.location.search)
  for (const [key, value] of Object.entries(update)) {
    if (value === null || value === undefined || value === false || value === '') params.delete(key)
    else params.set(key, value === true ? '1' : String(value))
  }
  write(params, replace, state)
}

/** Replace the whole query, e.g. to switch views. */
export function goTo(update: ParamUpdate) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(update)) {
    if (value !== null && value !== undefined && value !== false && value !== '') {
      params.set(key, value === true ? '1' : String(value))
    }
  }
  write(params, false)
  window.scrollTo({ top: 0 })
}

export function useSearchParams(): URLSearchParams {
  const search = useSyncExternalStore(subscribe, snapshot)
  return new URLSearchParams(search)
}

export function useParam(key: string): [string | null, (value: string | null) => void] {
  const params = useSearchParams()
  const set = useCallback((value: string | null) => setParams({ [key]: value }), [key])
  return [params.get(key), set]
}
