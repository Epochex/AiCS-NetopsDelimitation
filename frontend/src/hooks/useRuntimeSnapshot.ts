import { startTransition, useEffect, useState } from 'react'
import { runtimeSnapshot as fallbackSnapshot } from '../data/runtimeModel'
import type {
  RuntimeSnapshot,
  RuntimeStreamDelta,
  RuntimeStreamEnvelope,
} from '../types'

export type RuntimeConnectionState =
  | 'connecting'
  | 'live'
  | 'degraded'
  | 'fallback'

const SNAPSHOT_ENDPOINT = '/api/runtime/snapshot'
const STREAM_ENDPOINT = '/api/runtime/stream'
const SNAPSHOT_TIMEOUT_MS = 8_000
const STREAM_HANDSHAKE_TIMEOUT_MS = 8_000

function activeSuggestion(snapshot: RuntimeSnapshot) {
  return (
    snapshot.suggestions.find(
      (suggestion) => suggestion.id === snapshot.defaultSuggestionId,
    ) ??
    snapshot.suggestions[0] ??
    null
  )
}

function snapshotIntegrityIssue(snapshot: RuntimeSnapshot) {
  const suggestion = activeSuggestion(snapshot)

  if (!suggestion) {
    return 'Live snapshot returned no suggestion slice, so the console stayed on the guarded local model.'
  }

  const missingTimeline = (suggestion.timeline?.length ?? 0) === 0
  const missingTelemetry = (suggestion.stageTelemetry?.length ?? 0) === 0

  if (missingTimeline || missingTelemetry) {
    return `Live snapshot for ${suggestion.id} is missing timeline/stageTelemetry, so the console kept the last known good slice instead of swapping into drift.`
  }

  return null
}

export function useRuntimeSnapshot() {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot>(fallbackSnapshot)
  const [latestDelta, setLatestDelta] = useState<RuntimeStreamDelta | null>(null)
  const [connectionState, setConnectionState] =
    useState<RuntimeConnectionState>('connecting')
  const [transportIssue, setTransportIssue] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    let didTimeout = false
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => {
      didTimeout = true
      controller.abort()
    }, SNAPSHOT_TIMEOUT_MS)

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
        const issue = snapshotIntegrityIssue(nextSnapshot)
        if (issue) {
          setTransportIssue(issue)
          setConnectionState('degraded')
          return
        }
        startTransition(() => setSnapshot(nextSnapshot))
        setTransportIssue(null)
        setConnectionState('live')
      } catch {
        if (!isMounted) {
          return
        }
        if (!controller.signal.aborted) {
          setConnectionState('fallback')
          setTransportIssue(
            'Initial live snapshot request failed, so the console stayed on the guarded local model.',
          )
        } else if (didTimeout) {
          setConnectionState('fallback')
          setTransportIssue(
            `Initial live snapshot request timed out after ${SNAPSHOT_TIMEOUT_MS / 1000}s, so the console stayed on the guarded local model.`,
          )
        }
      } finally {
        window.clearTimeout(timeoutId)
      }
    }

    hydrate()
    return () => {
      isMounted = false
      controller.abort()
      window.clearTimeout(timeoutId)
    }
  }, [])

  useEffect(() => {
    let isMounted = true
    let retryTimer: number | undefined
    let eventSource: EventSource | undefined
    let handshakeTimer: number | undefined

    const connect = () => {
      if (!isMounted) {
        return
      }
      setConnectionState((previousState) =>
        previousState === 'live' ? 'live' : 'connecting',
      )
      eventSource = new EventSource(STREAM_ENDPOINT)
      handshakeTimer = window.setTimeout(() => {
        eventSource?.close()
        if (!isMounted) {
          return
        }
        setTransportIssue(
          `Live stream did not emit snapshot/delta/heartbeat inside ${STREAM_HANDSHAKE_TIMEOUT_MS / 1000}s, so the console kept the last known good slice.`,
        )
        setConnectionState((previousState) =>
          previousState === 'live' ? 'degraded' : 'fallback',
        )
        retryTimer = window.setTimeout(connect, 5000)
      }, STREAM_HANDSHAKE_TIMEOUT_MS)

      const handleEnvelope = (
        event: MessageEvent<string>,
        expectedType: RuntimeStreamEnvelope['type'],
      ) => {
        try {
          const envelope = JSON.parse(event.data) as RuntimeStreamEnvelope
          if (envelope.type !== expectedType) {
            return
          }
          if (!isMounted) {
            return
          }
          if (handshakeTimer) {
            window.clearTimeout(handshakeTimer)
            handshakeTimer = undefined
          }
          if (envelope.type === 'heartbeat') {
            return
          }
          const issue = snapshotIntegrityIssue(envelope.snapshot)
          if (issue) {
            setTransportIssue(issue)
            setConnectionState('degraded')
            return
          }
          startTransition(() => setSnapshot(envelope.snapshot))
          if (envelope.type === 'delta') {
            setLatestDelta(envelope.delta)
          } else {
            setLatestDelta(null)
          }
          setTransportIssue(null)
          setConnectionState('live')
        } catch {
          if (isMounted) {
            setTransportIssue(
              'Live stream emitted an unreadable envelope, so the console kept the last known good slice.',
            )
            setConnectionState('degraded')
          }
        }
      }

      eventSource.addEventListener('snapshot', (event) =>
        handleEnvelope(event as MessageEvent<string>, 'snapshot'),
      )
      eventSource.addEventListener('delta', (event) =>
        handleEnvelope(event as MessageEvent<string>, 'delta'),
      )
      eventSource.addEventListener('heartbeat', (event) =>
        handleEnvelope(event as MessageEvent<string>, 'heartbeat'),
      )

      eventSource.onerror = () => {
        if (handshakeTimer) {
          window.clearTimeout(handshakeTimer)
          handshakeTimer = undefined
        }
        eventSource?.close()
        if (!isMounted) {
          return
        }
        setTransportIssue(
          'Live stream connection degraded, so the console kept the last known good slice while retrying.',
        )
        setConnectionState((previousState) =>
          previousState === 'live' ? 'degraded' : 'fallback',
        )
        retryTimer = window.setTimeout(connect, 5000)
      }
    }

    connect()

    return () => {
      isMounted = false
      if (handshakeTimer) {
        window.clearTimeout(handshakeTimer)
      }
      eventSource?.close()
      if (retryTimer) {
        window.clearTimeout(retryTimer)
      }
    }
  }, [])

  return { snapshot, latestDelta, connectionState, transportIssue }
}
