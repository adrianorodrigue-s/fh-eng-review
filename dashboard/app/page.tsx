'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import FindingCard from '@/components/FindingCard'
import HistoryChart from '@/components/HistoryChart'
import SeverityBadge from '@/components/SeverityBadge'
import { SEVERITY_ORDER, severityRank } from '@/lib/severity'
import type { Finding, ProjectSummary, Report, StepResult } from '@/lib/types'

const STATUS_ICON: Record<string, string> = { OK: '✅', FAIL: '❌', SKIP: '⏭' }
const STEP_ICON: Record<string, string> = {
  ruff: '🧹',
  format: '📐',
  pytest: '🧪',
  semgrep: '🛡️',
  trivy: '📦',
}

function shortTitle(step: StepResult): string {
  return step.title.split('—')[0].trim()
}

function exportCsv(report: Report) {
  const rows: string[][] = [['etapa', 'severidade', 'regra', 'arquivo', 'linha', 'mensagem']]
  for (const step of report.steps) {
    for (const f of step.findings) {
      rows.push([
        shortTitle(step),
        f.severity,
        f.rule,
        f.file,
        f.line != null ? String(f.line) : '',
        f.message,
      ])
    }
  }
  const csv = rows
    .map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `review_${report.project}_${report.run_id}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function Dashboard() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [project, setProject] = useState('')
  const [runId, setRunId] = useState('')
  const [report, setReport] = useState<Report | null>(null)
  const [tab, setTab] = useState('overview')
  const [severityFilter, setSeverityFilter] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadProjects = useCallback(async () => {
    try {
      const res = await fetch('/api/projects', { cache: 'no-store' })
      const data = (await res.json()) as { projects: ProjectSummary[] }
      setProjects(data.projects)
      return data.projects
    } catch {
      setError('Não foi possível carregar os relatórios.')
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // deep-link: /?project=X&run=Y&tab=Z
    const params = new URLSearchParams(window.location.search)
    const wantProject = params.get('project')
    const wantRun = params.get('run')
    const wantTab = params.get('tab')
    loadProjects().then((list) => {
      if (list.length === 0) return
      const proj = list.find((p) => p.name === wantProject) ?? list[0]
      const run = proj.runs.find((r) => r.id === wantRun) ?? proj.runs[0]
      setProject(proj.name)
      setRunId(run.id)
      if (wantTab) setTab(wantTab)
    })
  }, [loadProjects])

  useEffect(() => {
    if (!project || !runId) return
    fetch(`/api/report?project=${project}&run=${runId}`, { cache: 'no-store' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Report | null) => {
        setReport(data)
        setSeverityFilter([])
        setSearch('')
      })
      .catch(() => setError('Não foi possível carregar o relatório.'))
  }, [project, runId])

  useEffect(() => {
    if (!project || !runId) return
    const url = `?project=${project}&run=${runId}&tab=${tab}`
    window.history.replaceState(null, '', url)
  }, [project, runId, tab])

  const currentProject = projects.find((p) => p.name === project)

  const selectProject = (name: string) => {
    setProject(name)
    const first = projects.find((p) => p.name === name)?.runs[0]
    if (first) setRunId(first.id)
  }

  const refresh = async () => {
    const list = await loadProjects()
    const proj = list.find((p) => p.name === project) ?? list[0]
    if (!proj) return
    if (proj.name !== project) setProject(proj.name)
    const stillExists = proj.runs.some((r) => r.id === runId)
    if (!stillExists) setRunId(proj.runs[0].id)
    else {
      // força re-fetch do relatório atual
      setRunId('')
      setTimeout(() => setRunId(runId), 0)
    }
  }

  const allFindings = useMemo(
    () =>
      (report?.steps ?? []).flatMap((s) =>
        s.findings.map((f) => ({ ...f, stepTitle: shortTitle(s) }))
      ),
    [report]
  )

  const severityCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const f of allFindings) counts.set(f.severity, (counts.get(f.severity) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => severityRank(a[0]) - severityRank(b[0]))
  }, [allFindings])

  const topFiles = useMemo(() => {
    const counts = new Map<string, number>()
    for (const f of allFindings) counts.set(f.file, (counts.get(f.file) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
  }, [allFindings])

  if (loading) {
    return <main className="empty-state">Carregando…</main>
  }
  if (projects.length === 0) {
    return (
      <main className="empty-state">
        <h1>🔍 Code Review</h1>
        <p>{error || 'Nenhum relatório encontrado ainda.'}</p>
        <pre>./review.sh /caminho/da/engenharia</pre>
      </main>
    )
  }

  const activeStep = report?.steps.find((s) => s.key === tab)
  // se o tab da URL não existir neste relatório, cai na visão geral
  const showOverview = tab === 'overview' || (report != null && !activeStep)

  return (
    <>
      <header className="topbar">
        <span className="brand">🔍 Code Review</span>
        <label>
          Engenharia
          <select value={project} onChange={(e) => selectProject(e.target.value)}>
            {projects.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Execução
          <select value={runId} onChange={(e) => setRunId(e.target.value)}>
            {currentProject?.runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.passed ? '✅' : '❌'} {r.id.replace('_', ' ')}
              </option>
            ))}
          </select>
        </label>
        <button className="refresh" onClick={refresh}>
          🔄 Atualizar
        </button>
        {report && (
          <span className={report.passed ? 'gate gate-pass' : 'gate gate-fail'}>
            {report.passed ? '✅ APROVADO' : '❌ REPROVADO'}
          </span>
        )}
      </header>

      {report && (
        <main>
          <p className="meta">
            Execução <strong>{report.run_id.replace('_', ' ')}</strong> · duração{' '}
            {report.duration_s}s · alvo <code>{report.target}</code> ·{' '}
            {allFindings.length} achado(s) no total
          </p>

          <section className="step-cards">
            {report.steps.map((s) => (
              <button
                key={s.key}
                className={`step-card status-${s.status.toLowerCase()} ${
                  tab === s.key ? 'active' : ''
                }`}
                onClick={() => setTab(s.key)}
              >
                <span className="step-icon">{STEP_ICON[s.key] ?? '🔎'}</span>
                <span className="step-name">{shortTitle(s)}</span>
                <span className="step-count">
                  {STATUS_ICON[s.status]} {s.findings.length} achado(s)
                </span>
                <span className="step-duration">{s.duration_s}s</span>
              </button>
            ))}
          </section>

          <nav className="tabs">
            <button className={showOverview ? 'active' : ''} onClick={() => setTab('overview')}>
              📋 Visão geral
            </button>
            {report.steps.map((s) => (
              <button
                key={s.key}
                className={tab === s.key ? 'active' : ''}
                onClick={() => setTab(s.key)}
              >
                {STATUS_ICON[s.status]} {shortTitle(s)} ({s.findings.length})
              </button>
            ))}
          </nav>

          {showOverview && (
            <section className="panel-grid">
              <div className="panel">
                <h2>Achados por severidade</h2>
                {severityCounts.length === 0 && <p className="ok-note">Nenhum achado. ✨</p>}
                {severityCounts.map(([sev, count]) => (
                  <div key={sev} className="sev-row">
                    <SeverityBadge severity={sev} />
                    <div className="sev-bar-track">
                      <div
                        className="sev-bar"
                        style={{ width: `${(count / allFindings.length) * 100}%` }}
                      />
                    </div>
                    <span className="sev-count">{count}</span>
                  </div>
                ))}
              </div>

              <div className="panel">
                <h2>Arquivos com mais achados</h2>
                {topFiles.length === 0 && <p className="ok-note">Nenhum achado. ✨</p>}
                <ul className="top-files">
                  {topFiles.map(([file, count]) => (
                    <li key={file}>
                      <code>{file}</code>
                      <span>{count}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="panel panel-wide">
                <h2>Histórico de execuções</h2>
                <HistoryChart
                  runs={[...(currentProject?.runs ?? [])].reverse()}
                  selected={runId}
                  onSelect={setRunId}
                />
              </div>

              {allFindings.length > 0 && (
                <div className="panel panel-wide export-row">
                  <button className="refresh" onClick={() => report && exportCsv(report)}>
                    ⬇️ Exportar todos os achados (CSV)
                  </button>
                </div>
              )}
            </section>
          )}

          {activeStep && (
            <StepPanel
              step={activeStep}
              severityFilter={severityFilter}
              setSeverityFilter={setSeverityFilter}
              search={search}
              setSearch={setSearch}
            />
          )}
        </main>
      )}
    </>
  )
}

function StepPanel({
  step,
  severityFilter,
  setSeverityFilter,
  search,
  setSearch,
}: {
  step: StepResult
  severityFilter: string[]
  setSeverityFilter: (v: string[]) => void
  search: string
  setSearch: (v: string) => void
}) {
  const severities = SEVERITY_ORDER.filter((sev) =>
    step.findings.some((f) => f.severity === sev)
  )

  const toggleSeverity = (sev: string) => {
    setSeverityFilter(
      severityFilter.includes(sev)
        ? severityFilter.filter((s) => s !== sev)
        : [...severityFilter, sev]
    )
  }

  const matches = (f: Finding) => {
    if (severityFilter.length > 0 && !severityFilter.includes(f.severity)) return false
    if (!search) return true
    const haystack = `${f.file} ${f.rule} ${f.message} ${f.detail}`.toLowerCase()
    return haystack.includes(search.toLowerCase())
  }

  const visible = step.findings
    .filter(matches)
    .sort(
      (a, b) =>
        severityRank(a.severity) - severityRank(b.severity) ||
        a.file.localeCompare(b.file) ||
        (a.line ?? 0) - (b.line ?? 0)
    )

  return (
    <section className="panel step-panel">
      <h2>{step.title}</h2>

      {step.status === 'SKIP' && <p className="ok-note">Passo ignorado nesta execução.</p>}
      {step.status === 'OK' && step.findings.length === 0 && (
        <p className="ok-note">Sem achados. ✨</p>
      )}
      {step.status === 'FAIL' && step.findings.length === 0 && (
        <>
          <p className="fail-note">A ferramenta falhou ao executar:</p>
          <pre className="error-output">{step.error_output || '(sem saída)'}</pre>
        </>
      )}

      {step.findings.length > 0 && (
        <>
          <div className="filters">
            {severities.map((sev) => (
              <button
                key={sev}
                className={`chip ${
                  severityFilter.length === 0 || severityFilter.includes(sev) ? 'chip-on' : ''
                }`}
                onClick={() => toggleSeverity(sev)}
              >
                {sev} ({step.findings.filter((f) => f.severity === sev).length})
              </button>
            ))}
            <input
              type="search"
              placeholder="Buscar arquivo, regra, mensagem… ex.: CVE-2026, urllib3"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <p className="meta">
            {visible.length} de {step.findings.length} achado(s)
          </p>
          {visible.map((f, i) => (
            <FindingCard key={`${f.rule}-${f.file}-${f.line}-${i}`} finding={f} />
          ))}
        </>
      )}
    </section>
  )
}
