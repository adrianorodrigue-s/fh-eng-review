import type { Finding } from '@/lib/types'

export default function Snippet({ finding }: { finding: Finding }) {
  if (!finding.snippet) return null
  const start = finding.snippet_start ?? finding.line ?? 1
  const markFrom = finding.line ?? start
  const markTo = finding.end_line ?? markFrom

  return (
    <div className="snippet">
      {finding.snippet.split('\n').map((text, i) => {
        const n = start + i
        const hit = n >= markFrom && n <= markTo
        return (
          <div key={n} className={hit ? 'snippet-line hit' : 'snippet-line'}>
            <span className="snippet-num">{n}</span>
            <span className="snippet-code">{text || ' '}</span>
          </div>
        )
      })}
    </div>
  )
}
