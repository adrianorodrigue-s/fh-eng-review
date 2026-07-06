export interface Finding {
  file: string
  line: number | null
  end_line: number | null
  rule: string
  severity: string
  message: string
  detail: string
  recommendation: string
  url: string
  snippet: string
  snippet_start: number | null
}

export interface StepResult {
  key: string
  title: string
  status: 'OK' | 'FAIL' | 'SKIP'
  duration_s: number
  findings: Finding[]
  error_output: string
}

export interface Report {
  run_id: string
  project: string
  target: string
  started_at: string
  duration_s: number
  passed: boolean
  steps: StepResult[]
}

export interface RunSummary {
  id: string
  passed: boolean
  totalFindings: number
  startedAt: string
  durationS: number
}

export interface ProjectSummary {
  name: string
  runs: RunSummary[]
}
