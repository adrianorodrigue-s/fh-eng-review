import { NextRequest, NextResponse } from 'next/server'
import { readReport } from '@/lib/reports'

export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest) {
  const project = request.nextUrl.searchParams.get('project') ?? ''
  const run = request.nextUrl.searchParams.get('run') ?? ''
  const report = await readReport(project, run)
  if (!report) {
    return NextResponse.json({ error: 'relatório não encontrado' }, { status: 404 })
  }
  return NextResponse.json(report)
}
