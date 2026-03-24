const localTimeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZoneName: 'short',
})

const localDateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZoneName: 'short',
})

const utcDateTimeFormatter = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'UTC',
  timeZoneName: 'short',
})

type TimestampStyle = 'time' | 'datetime'

export function parseTimestamp(value: string | null | undefined): Date | null {
  if (!value || value === 'n/a') {
    return null
  }

  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatMaybeTimestamp(
  value: string | null | undefined,
  style: TimestampStyle = 'datetime',
) {
  const parsed = parseTimestamp(value)
  if (!parsed) {
    return value ?? 'n/a'
  }

  return style === 'time'
    ? localTimeFormatter.format(parsed)
    : localDateTimeFormatter.format(parsed)
}

export function timestampTooltip(value: string | null | undefined) {
  const parsed = parseTimestamp(value)
  if (!parsed) {
    return undefined
  }

  return `${utcDateTimeFormatter.format(parsed)} · source UTC`
}

export function formatEvidenceValue(
  value: string | number | boolean | null | undefined,
) {
  if (value === null || value === undefined || value === '') {
    return '-'
  }

  if (typeof value === 'string') {
    return formatMaybeTimestamp(value)
  }

  return String(value)
}
