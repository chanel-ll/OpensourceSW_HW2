import { useEffect, useState } from 'react'
import { api, fmtDate, type Paper, type Source, type Status, type WeeklyRun } from './api'
import { PaperCard } from './PaperCard'

const day = (iso: string) => new Date(iso).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' })

function group(items: Paper[], by: 'source' | 'keyword', sources: Source[]) {
  const m = new Map<string, Paper[]>()
  for (const p of items) {
    const keys = by === 'source'
      ? [sources.find((s) => s.id === p.change?.source_id)?.name ?? '삭제된 소스']
      : [p.keywords[0] ?? '키워드 없음']
    for (const k of keys) m.set(k, [...(m.get(k) ?? []), p])
  }
  return [...m].sort((a, b) => b[1].length - a[1].length)
}

function RunSection({ run, open, onToggle, by, sources, llm, registered, onRead, onChange }: {
  run: WeeklyRun; open: boolean; onToggle: () => void; by: 'source' | 'keyword'; sources: Source[]
  llm: Status['llm']; registered: Set<string>; onRead: (ids: number[]) => void; onChange: (p: Paper) => void
}) {
  const c = run.counts
  return (
    <section className={`week${open ? ' week-open' : ''}`}>
      <button className="week-bar" onClick={onToggle} aria-expanded={open}>
        <span>{day(run.period_start)} – {day(run.started_at)}</span>
        <span>신규 {c.new} · 게재 확정 {c.accepted} · 정보 변경 {c.updated} · 변화 소스 {c.sources}</span>
        <span className="muted">{run.trigger === 'auto' ? '자동' : '수동'} · {run.status === 'running' ? '진행 중' : run.status}</span>
      </button>
      {open && (
        <div className="week-body">
          {run.errors.length > 0 && (
            <details className="warn"><summary>일부 API 호출 실패 {run.errors.length}건</summary><ul>{run.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></details>
          )}
          {run.items.length === 0 && <p className="muted">이 기간에는 새 논문이나 변경 사항이 없습니다.</p>}
          {group(run.items, by, sources).map(([g, ps]) => (
            <div key={g} className="group">
              <h3>{g} <span className="muted">{ps.length}</span></h3>
              <div className="cards">
                {ps.map((p) => <PaperCard key={p.id} paper={p} llm={llm} registered={registered} onRead={onRead} onChange={onChange} />)}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

export function Weekly({ status, sources, registered, onUpdate, onRead }: {
  status: Status; sources: Source[]; registered: Set<string>; onUpdate: () => void; onRead: () => void
}) {
  const [runs, setRuns] = useState<WeeklyRun[] | null>(null)
  const [err, setErr] = useState('')
  const [by, setBy] = useState<'source' | 'keyword'>('source')
  const [openIds, setOpenIds] = useState<Set<number>>(new Set())
  const busy = status.job.running || status.job.queued > 0

  useEffect(() => {
    if (busy) return
    api<WeeklyRun[]>('/weekly').then((r) => {
      setRuns(r)
      if (r[0]) setOpenIds((s) => new Set(s).add(r[0].id))
    }, (e) => setErr(e.message))
  }, [busy])

  async function markRead(ids: number[]) {
    await api('/changes/read', { method: 'POST', json: { change_ids: ids } })
    setRuns((rs) => rs!.map((r) => ({ ...r, items: r.items.map((p) => (p.change && ids.includes(p.change.ids[0]) ? { ...p, change: { ...p.change, read: true } } : p)) })))
    onRead()
  }
  const replace = (np: Paper) => setRuns((rs) => rs!.map((r) => ({ ...r, items: r.items.map((p) => (p.id === np.id ? { ...np, change: p.change } : p)) })))
  const latest = runs?.[0]

  return (
    <section className="page">
      <h1>Weekly Paper</h1>
      <div className="summary-band">
        {latest ? (
          <>
            <div><span className="muted">기간</span><b>{day(latest.period_start)} – {day(latest.started_at)}</b></div>
            <div><span className="muted">신규 논문</span><b>{latest.counts.new}</b></div>
            <div><span className="muted">게재 확정</span><b>{latest.counts.accepted}</b></div>
            <div><span className="muted">변화 있었던 소스</span><b>{latest.counts.sources}</b></div>
          </>
        ) : <div className="muted">아직 주간 업데이트 기록이 없습니다.</div>}
        <div className="band-actions">
          <span className="muted">마지막 업데이트 {fmtDate(status.last_update)}</span>
          <button className="primary" onClick={onUpdate} disabled={busy}>{busy ? `업데이트 중… ${status.job.message}` : '지금 업데이트'}</button>
        </div>
      </div>
      {status.job.error && status.job.kind === 'weekly' && <p className="error">업데이트 실패: {status.job.error}</p>}
      <div className="row toggle" role="group" aria-label="묶기">
        <button aria-pressed={by === 'source'} onClick={() => setBy('source')}>소스별 묶기</button>
        <button aria-pressed={by === 'keyword'} onClick={() => setBy('keyword')}>키워드별 묶기</button>
      </div>
      {!status.llm.enabled && <p className="notice">요약 기능 비활성: {status.llm.reason}</p>}
      {err && <p className="error">{err}</p>}
      {runs?.map((r) => (
        <RunSection key={r.id} run={r} open={openIds.has(r.id)} by={by} sources={sources} llm={status.llm} registered={registered}
          onToggle={() => setOpenIds((s) => { const n = new Set(s); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n })}
          onRead={markRead} onChange={replace} />
      ))}
    </section>
  )
}
