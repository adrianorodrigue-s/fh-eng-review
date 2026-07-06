'use client'

import { useState } from 'react'
import type { Finding } from '@/lib/types'
import SeverityBadge from './SeverityBadge'
import Snippet from './Snippet'

export default function FindingCard({ finding }: { finding: Finding }) {
  const [copied, setCopied] = useState(false)
  const location = finding.line ? `${finding.file}:${finding.line}` : finding.file

  const copyLocation = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    navigator.clipboard.writeText(location).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }

  return (
    <details className="finding">
      <summary>
        <SeverityBadge severity={finding.severity} />
        <code className="rule-chip">{finding.rule}</code>
        <button className="loc" onClick={copyLocation} title="Copiar arquivo:linha">
          {location} {copied ? '✓ copiado' : '⧉'}
        </button>
        <span className="finding-msg">{finding.message}</span>
        <span className="chevron">▾</span>
      </summary>
      <div className="finding-body">
        {finding.detail && <p className="finding-detail">{finding.detail}</p>}
        <Snippet finding={finding} />
        {finding.recommendation && (
          <div className="fix-box">
            <span className="fix-label">🛠️ Como corrigir</span>
            <p>{finding.recommendation}</p>
          </div>
        )}
        {finding.url && (
          <a className="doc-link" href={finding.url} target="_blank" rel="noreferrer">
            📖 Documentação da regra / CVE ↗
          </a>
        )}
      </div>
    </details>
  )
}
