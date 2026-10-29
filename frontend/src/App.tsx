import { useCallback, useEffect, useRef, useState } from 'react'
import { AddSource } from './AddSource'
import { api, fmtDate, type Source, type Status } from './api'
import { PaperList, registeredSet, SourceView } from './SourceView'
import { Weekly } from './Weekly'

type View =
  | { kind: 'home' } | { kind: 'add' } | { kind: 'weekly' }
  | { kind: 'source'; id: number } | { kind: 'search'; q: string } | { kind: 'soon'; name: string; phase: string }

const SOON = { world: ['Research World', 'P2'], research: ['My Research', 'P1'], settings: ['설정', 'P3'] } as const

export default function App() {
  const [view, setView] = useState<View>({ kind: 'home' })
  const [sources, setSources] = useState<Source[]>([])
  const [status, setStatus] = useState<Status | null>(null)
  const [statusErr, setStatusErr] = useState('')
  const [search, setSearch] = useState('')
  const [flash, setFlash] = useState('')
  const wasBusy = useRef(false)

  const loadSources = useCallback(() => api<Source[]>('/sources').then(setSources, () => {}), [])
  const loadStatus = useCallback(() => api<Status>('/status').then((s) => {
    setStatus(s)
    setStatusErr('')
    const busy = s.job.running || s.job.queued > 0
    if (busy || wasBusy.current) loadSources() // refresh tabs while collecting and once after
    wasBusy.current = busy
  }, (e) => setStatusErr(`백엔드에 연결할 수 없습니다 (${e.message}). 백엔드 서버가 켜져 있는지 확인하세요.`)), [loadSources])

  useEffect(() => {
    loadSources()
    loadStatus()
    const t = setInterval(loadStatus, 2500)
    return () => clearInterval(t)
  }, [loadSources, loadStatus])

  useEffect(() => {
    if (view.kind === 'home' && sources.length) setView({ kind: 'source', id: sources[0].id })
  }, [view.kind, sources])

  async function update() {
    try {
      await api('/weekly/update', { method: 'POST' })
      loadStatus()
    } catch (e) {
      setFlash((e as Error).message)
    }
  }
  const busy = !!status && (status.job.running || status.job.queued > 0)
  const current = view.kind === 'source' ? sources.find((s) => s.id === view.id) : undefined
  const registered = registeredSet(sources)
  const llm = status?.llm ?? { enabled: false, model: '', reason: '상태 확인 중' }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Research Tracker</div>
        <form className="search" onSubmit={(e) => { e.preventDefault(); if (search.trim()) setView({ kind: 'search', q: search.trim() }) }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="논문 제목 · 키워드 · 저자 검색" aria-label="전역 검색" />
        </form>
        <div className="top-status">
          <span className={`pill${llm.enabled ? ' pill-on' : ''}`} title={llm.reason || `모델 ${llm.model}`}>
            {llm.enabled ? `LLM ${llm.model} · 크레딧 ${status?.credit ?? '확인 불가'}` : 'LLM 꺼짐 · 요약 비활성'}
          </span>
          <span className="muted">마지막 업데이트 {fmtDate(status?.last_update ?? null)}</span>
          <button onClick={update} disabled={busy}>{busy && status?.job.kind === 'weekly' ? '업데이트 중…' : '지금 업데이트'}</button>
        </div>
      </header>
      {busy && <div className="jobbar">{status!.job.kind === 'weekly' ? 'Weekly 업데이트' : '논문 수집'}: {status!.job.message}</div>}
      {statusErr && <div className="jobbar error">{statusErr}</div>}
      {flash && <div className="jobbar warn" onClick={() => setFlash('')}>{flash} (닫기)</div>}

      <nav className="sidebar" aria-label="메뉴">
        <div className="nav-group">Research Scrap</div>
        {sources.map((s) => (
          <button key={s.id} className={`nav-item sub${view.kind === 'source' && view.id === s.id ? ' active' : ''}`} onClick={() => setView({ kind: 'source', id: s.id })} title={s.name}>
            <span className="ellipsis">{s.name}</span>
            <span className="muted">{s.status === 'collecting' ? '수집 중' : s.status === 'error' ? '오류' : s.paper_count}</span>
          </button>
        ))}
        <button className={`nav-item sub add${view.kind === 'add' ? ' active' : ''}`} onClick={() => setView({ kind: 'add' })}>+ 소스 추가</button>
        <button className={`nav-item${view.kind === 'weekly' ? ' active' : ''}`} onClick={() => setView({ kind: 'weekly' })}>
          Weekly Paper {!!status?.unread_changes && <span className="badge badge-new">{status.unread_changes}</span>}
        </button>
        {(['world', 'research'] as const).map((k) => (
          <button key={k} className="nav-item" onClick={() => setView({ kind: 'soon', name: SOON[k][0], phase: SOON[k][1] })}>
            {SOON[k][0]} <span className="tag">준비 중</span>
          </button>
        ))}
        <div className="spacer" />
        <button className="nav-item" onClick={() => setView({ kind: 'soon', name: SOON.settings[0], phase: SOON.settings[1] })}>설정 <span className="tag">준비 중</span></button>
      </nav>

      <main className="main">
        {view.kind === 'add' && <AddSource onCreated={(s) => { loadSources(); loadStatus(); setView({ kind: 'source', id: s.id }) }} />}
        {view.kind === 'source' && current && (
          <SourceView key={current.id} source={current} llm={llm} registered={registered} onChanged={() => { loadSources(); loadStatus() }}
            onDeleted={() => { loadSources(); setView({ kind: 'home' }) }} />
        )}
        {view.kind === 'weekly' && status && <Weekly status={status} sources={sources} registered={registered} onUpdate={update} onRead={loadStatus} />}
        {view.kind === 'search' && (
          <section className="page">
            <h1>검색: “{view.q}”</h1>
            <PaperList query={`q=${encodeURIComponent(view.q)}`} llm={llm} registered={registered} reloadKey={view.q} />
          </section>
        )}
        {view.kind === 'soon' && (
          <section className="page soon"><h1>{view.name}</h1><p>준비 중입니다. ({view.phase} 단계에서 제공 예정)</p></section>
        )}
        {view.kind === 'home' && (
          <section className="page soon">
            <h1>Research Tracker</h1>
            <p>관심 연구실·팀·연구자를 등록하면 최근 2년 논문을 모아 보여줍니다.</p>
            <button className="primary" onClick={() => setView({ kind: 'add' })}>+ 첫 소스 추가</button>
          </section>
        )}
      </main>
    </div>
  )
}
