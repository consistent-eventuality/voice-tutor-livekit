export function timeAgo(iso: string): string {
  // Backend emits naive datetimes (no TZ offset). Treat them as UTC so the JS
  // Date parser doesn't interpret them as local time and put them in the future.
  const utcIso = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z'
  const ms = Date.now() - new Date(utcIso).getTime()
  const min = Math.floor(ms / 60_000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} hr ago`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day} day${day === 1 ? '' : 's'} ago`
  const wk = Math.floor(day / 7)
  return `${wk} week${wk === 1 ? '' : 's'} ago`
}
