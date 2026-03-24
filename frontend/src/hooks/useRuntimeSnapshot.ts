import { startTransition, useEffect, useState } from 'react'
import { runtimeSnapshot as fallbackSnapshot } from '../data/runtimeModel'
import type { RuntimeSnapshot } from '../types'

export type RuntimeConnectionState =
  | 'connecting'
  | 'live'
  | 'degraded'
  | 'fallback'

const SNAPSHOT_ENDPOINT = '/api/runtime/snapshot'
const STREAM_ENDPOINT = '/api/runtime/stream'

export function useRuntimeSnapshot() {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot>(fallbackSnapshot)
  const [connectionState, setConnectionState] =
    useState<RuntimeConnectionState>('connecting')

  useEffect(() => {
    const controller = new AbortController()

    async function hydrate() {
      try {
        const response = await fetch(SNAPSHOT_ENDPOINT, {
          signal: controller.signal,
          headers: { Accept: 'application/json' },
        })
        if (!response.ok) {
          throw new Error(`snapshot request failed: ${response.status}`)
        }
        const nextSnapshot = (await response.json()) as RuntimeSnapshot
        startTransition(() => setSnapshot(nextSnapshot))
        setConnectionState('live')
      } catch {
        if (!controller.signal.aborted) {
          setConnectionState('fallback')
        }
      }
    }

    hydrate()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    let isMounted = true
    let retryTimer: number | undefined
    let eventSource: EventSource | undefined

    const connect = () => {
      if (!isMounted) {
        return
      }
      setConnectionState((previousState) =>
        previousState === 'live' ? 'live' : 'connecting',
      )
      eventSource = new EventSource(STREAM_ENDPOINT)

      eventSource.onmessage = (event) => {
        try {
          const nextSnapshot = JSON.parse(event.data) as RuntimeSnapshot
          if (!isMounted) {
            return
          }
          startTransition(() => setSnapshot(nextSnapshot))
          setConnectionState('live')
        } catch {
          if (isMounted) {
            setConnectionState('degraded')
          }
        }
      }

      eventSource.onerror = () => {
        eventSource?.close()
        if (!isMounted) {
          return
        }
        setConnectionState((previousState) =>
          previousState === 'live' ? 'degraded' : 'fallback',
        )
        retryTimer = window.setTimeout(connect, 5000)
      }
    }

    connect()

    return () => {
      isMounted = false
      eventSource?.close()
      if (retryTimer) {
        window.clearTimeout(retryTimer)
      }
    }
  }, [])

  return { snapshot, connectionState }
}
