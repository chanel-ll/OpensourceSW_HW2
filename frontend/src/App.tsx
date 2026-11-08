import { Component, lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AddSource } from './AddSource'
import { api, fmtDate, go, href, parseHash, type Route, type Source, type Status } from './api'
import { Library } from './Library'
import { PaperNote } from './PaperNote'
import { ProjectList, ProjectPage } from './Projects'
import { PaperList, registeredSet, SourceView } from './SourceView'
import { Weekly } from './Weekly'

const World = lazy(() => import('./World').then((m) => ({ default: m.World }))) // three.js only when needed

/** One broken screen must not blank the whole app. */
class Boundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidUpdate(prev: { resetKey: string }) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }) }
  render() {
    return this.state.error
      ? <section className="page"><h1>화면을 표시하지 못했습니다</h1><p className="error">{this.state.error.message}</p><p className="muted">다른 메뉴는 정상적으로 사용할 수 있습니다.</p></section>
      : this.props.children
  }
}

function useRoute() {
  const [route, setRoute] = useState<Route>(() => parseHash(location.hash))
  useEffect(() => {
    const on = () => { setRoute(parseHash(location.hash)); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export default function App() {
  const view = useRoute()
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
    if (view.kind === 'home' && sources.length) location.replace(href('source', sources[0].id))
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
  const JOB: Record<string, string> = { weekly: 'Weekly 업데이트', collect: '논문 수집', embed: '임베딩 계산' }

  return (
    <div className={`app${view.kind === 'world' ? ' app-world' : ''}`}>
      <header className="topbar">
        <a className="brand" href="#/">Research Tracker</a>
        <form className="search" onSubmit={(e) => { e.preventDefault(); if (search.trim()) go('search', search.trim()) }}>
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
      {busy && <div className="jobbar">{JOB[status!.job.kind] ?? status!.job.kind}: {status!.job.message}</div>}
      {statusErr && <div className="jobbar error">{statusErr}</div>}
      {flash && <div className="jobbar warn" onClick={() => setFlash('')}>{flash} (닫기)</div>}

      <nav className="sidebar" aria-label="메뉴">
        <div className="nav-group">Research Scrap</div>
        {sources.map((s) => (
          <a key={s.id} href={href('source', s.id)} className={`nav-item sub${view.kind === 'source' && view.id === s.id ? ' active' : ''}`} title={s.name}>
            <span className="ellipsis">{s.name}</span>
            <span className="muted">{s.status === 'collecting' ? '수집 중' : s.status === 'error' ? '오류' : s.paper_count}</span>
          </a>
        ))}
        <a href={href('add')} className={`nav-item sub add${view.kind === 'add' ? ' active' : ''}`}>+ 소스 추가</a>
        <a href={href('weekly')} className={`nav-item${view.kind === 'weekly' ? ' active' : ''}`}>
          Weekly Paper {!!status?.unread_changes && <span className="badge badge-new">{status.unread_changes}</span>}
        </a>
        <a href={href('library')} className={`nav-item${view.kind === 'library' ? ' active' : ''}`}>
          Library {!!status?.starred_count && <span className="muted">{status.starred_count}</span>}
        </a>
        <a href={href('world')} className={`nav-item${view.kind === 'world' ? ' active' : ''}`}>Research World</a>
        <a href={href('projects')} className={`nav-item${view.kind === 'projects' || view.kind === 'project' ? ' active' : ''}`}>My Research</a>
        <div className="spacer" />
        <a href={href('settings')} className={`nav-item${view.kind === 'settings' ? ' active' : ''}`}>설정 <span className="tag">준비 중</span></a>
      </nav>

      <main className="main">
        <Boundary resetKey={location.hash}>
        {view.kind === 'add' && <AddSource onCreated={(s) => { loadSources(); loadStatus(); go('source', s.id) }} />}
        {view.kind === 'source' && current && (
          <SourceView key={current.id} source={current} llm={llm} registered={registered} onChanged={() => { loadSources(); loadStatus() }}
            onDeleted={() => { loadSources(); go('') }} />
        )}
        {view.kind === 'weekly' && status && <Weekly status={status} sources={sources} registered={registered} onUpdate={update} onRead={loadStatus} />}
        {view.kind === 'search' && (
          <section className="page">
            <h1>검색: “{view.q}”</h1>
            <PaperList query={`q=${encodeURIComponent(view.q)}`} llm={llm} registered={registered} reloadKey={view.q} />
          </section>
        )}
        {view.kind === 'paper' && <PaperNote key={view.id} id={view.id} llm={llm} registered={registered} />}
        {view.kind === 'library' && <Library group={view.group} llm={llm} registered={registered} onChanged={loadStatus} />}
        {view.kind === 'projects' && <ProjectList />}
        {view.kind === 'project' && <ProjectPage key={view.id} id={view.id} tab={view.tab} note={view.note} />}
        {view.kind === 'world' && <Suspense fallback={<p className="muted">Research World 불러오는 중…</p>}><World sources={sources} focus={view.focus} onSourcesChanged={loadSources} /></Suspense>}
        {view.kind === 'settings' && (
          <section className="page soon"><h1>설정</h1><p>준비 중입니다. (P3) 지금은 config.yaml과 .env를 직접 수정하세요.</p></section>
        )}
        {view.kind === 'home' && (
          <section className="page soon">
            <h1>Research Tracker</h1>
            <p>관심 연구실·팀·연구자를 등록하면 최근 2년 논문을 모아 보여줍니다.</p>
            <a className="btn primary" href={href('add')}>+ 첫 소스 추가</a>
          </section>
        )}
        </Boundary>
      </main>
    </div>
  )
}
