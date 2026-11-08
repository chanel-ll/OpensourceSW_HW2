import { useEffect, useState } from 'react'
import { api, fmtDate, go, href, ROLES, STATUSES, venueLabel, type ProjectFull, type ProjectSummary } from './api'
import { loadTitles, MarkdownEditor } from './MarkdownEditor'

export function ProjectList() {
  const [list, setList] = useState<ProjectSummary[] | null>(null)
  const [err, setErr] = useState('')
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [status, setStatus] = useState(STATUSES[0])
  useEffect(() => { api<ProjectSummary[]>('/projects').then(setList, (e) => setErr(e.message)) }, [])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    try {
      const p = await api<ProjectSummary>('/projects', { method: 'POST', json: { name, description: desc, status } })
      go('project', p.id)
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  return (
    <section className="page">
      <h1>My Research</h1>
      <form className="step row" onSubmit={create}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="새 프로젝트 이름" aria-label="프로젝트 이름" required />
        <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="한 줄 설명" aria-label="한 줄 설명" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="상태">{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        <button className="primary" disabled={!name.trim()}>프로젝트 만들기</button>
      </form>
      {err && <p className="error">{err}</p>}
      {list && list.length === 0 && <p className="muted">아직 프로젝트가 없습니다. 진행 중인 연구 하나를 옮겨 보세요.</p>}
      <div className="project-grid">
        {list?.map((p) => (
          <a key={p.id} href={href('project', p.id)} className="project-card">
            <div className="row"><b>{p.name}</b><span className={`status status-${STATUSES.indexOf(p.status)}`}>{p.status}</span></div>
            <p className="muted">{p.description || '설명 없음'}</p>
            <p className="small muted">노트 {p.note_count} · 레퍼런스 {p.ref_count} · 수정 {fmtDate(p.updated_at)}</p>
          </a>
        ))}
      </div>
    </section>
  )
}

type Cand = { openalex_id: string; title: string; year: number; venue: string }

export function ProjectPage({ id, tab, note }: { id: number; tab: string; note: string }) {
  const [p, setP] = useState<ProjectFull | null>(null)
  const [err, setErr] = useState('')
  const load = () => api<ProjectFull>(`/projects/${id}`).then(setP, (e) => setErr(e.message))
  useEffect(() => { load() }, [id])

  async function patch(body: Partial<ProjectFull>) {
    try {
      setP(await api<ProjectFull>(`/projects/${id}`, { method: 'PATCH', json: body }))
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  if (!p) return <section className="page">{err ? <p className="error">{err}</p> : <p className="muted">불러오는 중…</p>}</section>
  const tabs = [['overview', '개요'], ['notes', '노트'], ['references', '레퍼런스']]
  return (
    <section className="page wide">
      <header className="source-head">
        <div className="row">
          <input className="title-input" defaultValue={p.name} key={p.name} aria-label="프로젝트 이름"
            onBlur={(e) => e.target.value.trim() && e.target.value !== p.name && patch({ name: e.target.value })} />
          <select value={p.status} onChange={(e) => patch({ status: e.target.value })} aria-label="상태">
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <input className="desc-input" defaultValue={p.description} key={p.description} placeholder="한 줄 설명" aria-label="한 줄 설명"
          onBlur={(e) => e.target.value !== p.description && patch({ description: e.target.value })} />
        <nav className="row toggle" aria-label="프로젝트 탭">
          {tabs.map(([k, label]) => <a key={k} href={href('project', id, k)} className={`tab${tab === k ? ' on' : ''}`}>{label}</a>)}
        </nav>
        {err && <p className="error">{err}</p>}
      </header>
      {tab === 'notes' ? <NotesTab p={p} note={note} reload={load} />
        : tab === 'references' ? <RefsTab p={p} reload={load} setP={setP} />
          : <Overview p={p} />}
    </section>
  )
}

function Overview({ p }: { p: ProjectFull }) {
  return (
    <div className="panel">
      <dl className="meta-grid">
        <div><dt>상태</dt><dd>{p.status}</dd></div>
        <div><dt>노트</dt><dd>{p.notes.length}개</dd></div>
        <div><dt>레퍼런스</dt><dd>{p.references.length}편</dd></div>
        <div><dt>마지막 수정</dt><dd>{fmtDate(p.updated_at)}</dd></div>
        <div><dt>노트 폴더</dt><dd className="small">{p.folder}</dd></div>
      </dl>
      <div className="row">
        <a className="btn primary" href={href('world', `project-${p.id}`)}>World에서 보기</a>
        <button className="danger" onClick={async () => {
          if (window.confirm(`'${p.name}' 프로젝트를 삭제할까요? 노트 폴더는 notes/.trash로 옮겨집니다.`)) {
            await api(`/projects/${p.id}`, { method: 'DELETE' })
            go('projects')
          }
        }}>프로젝트 삭제</button>
      </div>
      <h2>최근 노트</h2>
      {p.notes.length ? <ul className="brief-list">{p.notes.slice(0, 5).map((n) => <li key={n.name}><a href={href('project', p.id, 'notes', n.name)}>{n.name}</a> <span className="muted small">{fmtDate(n.updated_at)}</span></li>)}</ul>
        : <p className="muted">노트가 없습니다.</p>}
    </div>
  )
}

function NotesTab({ p, note, reload }: { p: ProjectFull; note: string; reload: () => void }) {
  const current = note || p.notes[0]?.name || ''
  const [content, setContent] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => {
    setContent(null)
    if (current) api<{ content: string }>(`/projects/${p.id}/notes/${encodeURIComponent(current)}`).then((r) => setContent(r.content), (e) => setErr(e.message))
  }, [p.id, current])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    const r = await api<{ name: string }>(`/projects/${p.id}/notes`, { method: 'POST', json: { title } })
    setTitle('')
    reload()
    go('project', p.id, 'notes', r.name)
  }
  async function rename() {
    const t = window.prompt('새 노트 이름', current)
    if (!t || t === current) return
    const r = await api<{ name: string }>(`/projects/${p.id}/notes/${encodeURIComponent(current)}`, { method: 'PATCH', json: { title: t } })
    reload()
    go('project', p.id, 'notes', r.name)
  }
  async function remove() {
    if (!window.confirm(`'${current}' 노트를 삭제할까요? (notes/.trash로 이동)`)) return
    await api(`/projects/${p.id}/notes/${encodeURIComponent(current)}`, { method: 'DELETE' })
    reload()
    go('project', p.id, 'notes')
  }
  return (
    <div className="notes-layout">
      <aside className="panel notes-list">
        <form onSubmit={create} className="row">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="새 노트 (예: 실험 로그)" aria-label="새 노트 이름" required />
          <button disabled={!title.trim()}>추가</button>
        </form>
        {p.notes.map((n) => (
          <a key={n.name} href={href('project', p.id, 'notes', n.name)} className={`nav-item${n.name === current ? ' active' : ''}`}>
            <span className="ellipsis">{n.name}</span>
          </a>
        ))}
        {!p.notes.length && <p className="muted small">아이디어 정리, 실험 로그, 미팅 메모 등을 만들어 보세요.</p>}
      </aside>
      <div className="panel">
        {current ? (
          <>
            <div className="row"><h2>{current}</h2><button className="link-btn small" onClick={rename}>이름 변경</button><button className="link-btn small danger" onClick={remove}>삭제</button></div>
            {content === null ? <p className="muted">{err || '불러오는 중…'}</p> : (
              <MarkdownEditor key={`${p.id}/${current}`} initial={content} private
                onSave={(c) => api(`/projects/${p.id}/notes/${encodeURIComponent(current)}`, { method: 'PUT', json: { content: c } })} />
            )}
          </>
        ) : <p className="muted">왼쪽에서 노트를 만드세요.</p>}
      </div>
    </div>
  )
}

function RefsTab({ p, reload, setP }: { p: ProjectFull; reload: () => void; setP: (p: ProjectFull) => void }) {
  const [q, setQ] = useState('')
  const [role, setRole] = useState(ROLES[1])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [cands, setCands] = useState<Cand[]>([])

  async function add(body: object) {
    setBusy(true)
    setErr('')
    setCands([])
    try {
      setP(await api<ProjectFull>(`/projects/${p.id}/references`, { method: 'POST', json: { role, ...body } }))
      setQ('')
      loadTitles(true)
    } catch (e) {
      const m = (e as Error).message
      try {
        const d = JSON.parse(m)
        setErr(d.message)
        setCands(d.candidates ?? [])
      } catch {
        setErr(m)
      }
    } finally {
      setBusy(false)
    }
  }
  async function patchRef(pid: number, body: object) {
    await api(`/projects/${p.id}/references/${pid}`, { method: 'PATCH', json: body })
    reload()
  }
  const groups = ROLES.map((r) => [r, p.references.filter((x) => x.role === r)] as const).filter(([, xs]) => xs.length)
  return (
    <div>
      <div className="panel">
        <form className="row" onSubmit={(e) => { e.preventDefault(); add({ query: q }) }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="arXiv 링크, DOI 또는 논문 제목 붙여넣기" aria-label="레퍼런스 추가" />
          <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="역할 태그">{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
          <button className="primary" disabled={!q.trim() || busy}>{busy ? '찾는 중…' : '추가'}</button>
          <a className="btn" href={`/api/projects/${p.id}/bibtex`} download>BibTeX 내보내기</a>
        </form>
        {err && <p className="error">{err}</p>}
        {cands.length > 0 && (
          <ul className="brief-list">
            {cands.map((c) => (
              <li key={c.openalex_id}>
                <button className="link-btn" onClick={() => add({ openalex_id: c.openalex_id })}>{c.title}</button>
                <span className="muted"> · {c.venue} {c.year}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      {!p.references.length && <p className="muted">레퍼런스가 없습니다. 논문 카드의 "프로젝트에 추가"나 위 입력창을 사용하세요.</p>}
      {groups.map(([r, xs]) => (
        <section key={r} className="group">
          <h3>{r} <span className="muted">{xs.length}</span></h3>
          <div className="cards">
            {xs.map((x) => (
              <article key={x.id} className="card ref-card">
                <div className="card-meta"><span className="venue">{venueLabel(x)}</span></div>
                <h3 className="card-title"><a className="title-link" href={href('paper', x.id)}>{x.title}</a></h3>
                <p className="authors">{x.authors.slice(0, 6).map((a) => a.name).join(', ')}{x.authors.length > 6 ? ' 외' : ''}</p>
                <div className="row">
                  <input className="memo-input" defaultValue={x.memo} key={x.memo} placeholder="이 프로젝트에서 왜 중요한지"
                    aria-label="레퍼런스 메모" onBlur={(e) => e.target.value !== x.memo && patchRef(x.id, { memo: e.target.value })} />
                  <select value={x.role} onChange={(e) => patchRef(x.id, { role: e.target.value })} aria-label="역할 태그">
                    {ROLES.map((o) => <option key={o}>{o}</option>)}
                  </select>
                  <button onClick={async () => { await api(`/projects/${p.id}/references/${x.id}`, { method: 'DELETE' }); reload() }}>제거</button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
