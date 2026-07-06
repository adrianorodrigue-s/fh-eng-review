export const SEVERITY_ORDER = [
  'CRITICAL',
  'ERROR',
  'HIGH',
  'MEDIUM',
  'WARNING',
  'LOW',
  'INFO',
] as const

export function severityRank(severity: string): number {
  const idx = SEVERITY_ORDER.indexOf(severity as (typeof SEVERITY_ORDER)[number])
  return idx === -1 ? SEVERITY_ORDER.length : idx
}

/** Agrupa severidades equivalentes das ferramentas em 4 níveis visuais. */
export function severityBucket(severity: string): 'critical' | 'high' | 'medium' | 'low' {
  switch (severity) {
    case 'CRITICAL':
      return 'critical'
    case 'ERROR':
    case 'HIGH':
      return 'high'
    case 'MEDIUM':
    case 'WARNING':
      return 'medium'
    default:
      return 'low'
  }
}
