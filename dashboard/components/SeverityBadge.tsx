import { severityBucket } from '@/lib/severity'

export default function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge badge-${severityBucket(severity)}`}>{severity}</span>
}
