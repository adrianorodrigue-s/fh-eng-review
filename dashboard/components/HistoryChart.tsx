'use client'

import type { RunSummary } from '@/lib/types'

interface Props {
  runs: RunSummary[] // ordem cronológica (mais antiga primeiro)
  selected: string
  onSelect: (runId: string) => void
}

const H = 120
const STEP_X = 64
const PAD = 24

export default function HistoryChart({ runs, selected, onSelect }: Props) {
  if (runs.length === 0) return null
  const width = Math.max(280, PAD * 2 + STEP_X * (runs.length - 1))
  const max = Math.max(...runs.map((r) => r.totalFindings), 1)
  const x = (i: number) => PAD + i * STEP_X
  const y = (v: number) => H - PAD - (v / max) * (H - PAD * 2)
  const points = runs.map((r, i) => `${x(i)},${y(r.totalFindings)}`).join(' ')

  return (
    <div className="history-scroll">
      <svg width={width} height={H} role="img" aria-label="Histórico de achados por execução">
        <polyline points={points} fill="none" stroke="var(--border-strong)" strokeWidth="2" />
        {runs.map((r, i) => (
          <g key={r.id} className="history-dot" onClick={() => onSelect(r.id)}>
            <circle
              cx={x(i)}
              cy={y(r.totalFindings)}
              r={r.id === selected ? 8 : 5}
              fill={r.passed ? 'var(--ok)' : 'var(--fail)'}
              stroke={r.id === selected ? 'var(--text)' : 'transparent'}
              strokeWidth="2"
            >
              <title>{`${r.id} — ${r.totalFindings} achado(s)`}</title>
            </circle>
            <text x={x(i)} y={y(r.totalFindings) - 12} textAnchor="middle" className="history-value">
              {r.totalFindings}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}
