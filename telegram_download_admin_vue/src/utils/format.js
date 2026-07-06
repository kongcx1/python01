export function formatBytes(bytes) {
  const value = Number(bytes)
  if (!Number.isFinite(value) || value < 0) return '--'
  if (value < 1024) return `${value.toFixed(0)}B`
  const kb = value / 1024
  if (kb < 1024) return `${kb.toFixed(1)}KB`
  const mb = kb / 1024
  if (mb < 1024) return `${mb.toFixed(2)}MB`
  const gb = mb / 1024
  return `${gb.toFixed(2)}GB`
}

export function formatSpeed(bps) {
  const value = Number(bps)
  if (!Number.isFinite(value) || value <= 0) return '--'
  const kb = value / 1024
  if (kb < 1024) return `${kb.toFixed(1)}KB/s`
  const mb = kb / 1024
  return `${mb.toFixed(1)}MB/s`
}

export function formatDateTime(value) {
  if (!value) return '--'
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = number => String(number).padStart(2, '0')
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate())
  ].join('-') + ' ' + [
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds())
  ].join(':')
}

export function parseProgress(raw) {
  if (!raw) return {}
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch (error) {
    return {}
  }
}
