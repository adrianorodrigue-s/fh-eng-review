import { promises as fs } from 'fs'
import path from 'path'
import type { ProjectSummary, Report, RunSummary } from './types'

const REPORTS_DIR = process.env.REPORTS_DIR ?? path.join(process.cwd(), '..', 'reports')

// nomes de projeto/execução vêm da URL — nunca deixar escapar da pasta de reports
const SAFE_NAME = /^[\w.\-]+$/

async function readReportFile(project: string, runFile: string): Promise<Report | null> {
  try {
    const raw = await fs.readFile(path.join(REPORTS_DIR, project, runFile), 'utf-8')
    return JSON.parse(raw) as Report
  } catch {
    return null
  }
}

export async function listProjects(): Promise<ProjectSummary[]> {
  let entries: string[]
  try {
    entries = await fs.readdir(REPORTS_DIR)
  } catch {
    return []
  }

  const projects: ProjectSummary[] = []
  for (const name of entries.sort()) {
    if (!SAFE_NAME.test(name)) continue
    const dir = path.join(REPORTS_DIR, name)
    const stat = await fs.stat(dir).catch(() => null)
    if (!stat?.isDirectory()) continue

    const files = (await fs.readdir(dir)).filter((f) => f.endsWith('.json')).sort().reverse()
    const runs: RunSummary[] = []
    for (const file of files) {
      const report = await readReportFile(name, file)
      if (!report) continue
      runs.push({
        id: file.replace(/\.json$/, ''),
        passed: report.passed,
        totalFindings: report.steps.reduce((n, s) => n + s.findings.length, 0),
        startedAt: report.started_at,
        durationS: report.duration_s,
      })
    }
    if (runs.length > 0) projects.push({ name, runs })
  }
  return projects
}

export async function readReport(project: string, run: string): Promise<Report | null> {
  if (!SAFE_NAME.test(project) || !SAFE_NAME.test(run)) return null
  return readReportFile(project, `${run}.json`)
}
