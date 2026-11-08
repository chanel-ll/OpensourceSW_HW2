import { useEffect, useState } from 'react'
import { api, href, venueLabel, type Brief, type PaperDetail, type Status } from './api'
import { MarkdownEditor } from './MarkdownEditor'
import { AddToProject } from './PaperCard'

type WorldLite = { fields: { id: number; name: string; subfields: { id: number; name: string }[] }[] }

function BriefList({ items, empty }: { items: Brief[]; empty: string }) {
  if (!items.length) return <p className="muted small">{empty}</p>
  return (
    <ul className="brief-list">
      {items.map((b) => (
        <li key={b.id}>
          <a href={href('paper', b.id)}>{b.title}</a>
          <span className="muted"> · {b.venue} {b.year ?? ''}{b.similarity !== undefined ? ` · 유사도 ${b.similarity}` : ''}</span>
        </li>
      ))}
    </ul>
  )
}

export function PaperNote({ id, llm, registered }: { id: number; llm: Status['llm']; registered: Set<string> }) {
  const [p, setP] = useState<PaperDetail | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [subs, setSubs] = useState<WorldLite['fields']>([])

  const load = () => api<PaperDetail>(`/papers/${id}`).then(setP, (e) => setErr(e.message))
  useEffect(() => { setP(null); setErr(''); load() }, [id])

  async function summarize() {
    setBusy(true)
    setErr('')
    try {
      await api(`/papers/${id}/summarize`, { method: 'POST' })
      await load()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  async function star() {
    await api(`/papers/${id}`, { method: 'PATCH', json: { starred: !p!.starred } })
    load()
  }
  async function move(subfield_id: number) {
    await api(`/papers/${id}/subfield`, { method: 'PATCH', json: { subfield_id } })
    load()
  }

  if (err && !p) return <section className="page"><p className="error">{err}</p></section>
  if (!p) return <section className="page"><p className="muted">불러오는 중…</p></section>
  const cls = p.classification
  return (
    <section className="page note-page">
      <div className="note-main">
        <header className="note-head">
          <div className="card-meta">
            <span className={`venue${p.is_preprint || !p.venue ? ' venue-pre' : ''}`}>{venueLabel(p)}</span>
            <span className="muted">{p.pub_date ?? p.year ?? ''}</span>
          </div>
          <h1>{p.title}</h1>
          <p className="authors">
            {p.authors.map((a, i) => {
              const reg = (a.openalex_id && registered.has(a.openalex_id)) || (a.s2_id && registered.has(a.s2_id))
              return <span key={i} className={reg ? 'author-reg' : ''}>{a.name}{i < p.authors.length - 1 ? ', ' : ''}</span>
            })}
          </p>
          <div className="row">
            {Object.entries(p.links).map(([k, v]) => <a key={k} href={v} target="_blank" rel="noreferrer" className="chip">{k}</a>)}
            {p.sources.map((s) => <a key={s.id} href={href('source', s.id)} className="tag">{s.name}</a>)}
          </div>
          <div className="row">
            <button onClick={star} aria-pressed={p.starred}>{p.starred ? '★ 관심 논문' : '☆ 관심 표시'}</button>
            <AddToProject paperId={p.id} onAdded={load} />
          </div>
        </header>

        <section className="panel">
          <h2>AI 요약</h2>
          {p.summary ? (
            <>
              <p className="summary"><b>한줄 요약</b> {p.summary.one_line}</p>
              {p.summary.contributions.length > 0 && <ul>{p.summary.contributions.map((c, i) => <li key={i}>{c}</li>)}</ul>}
              <p className="muted small">{p.summary.model} · 제목과 abstract만 사용해 생성</p>
            </>
          ) : (
            <>
              <button className="primary" onClick={summarize} disabled={!llm.enabled || busy} title={llm.reason}>{busy ? '요약 중…' : '요약 생성'}</button>
              {!llm.enabled && <p className="muted small">{llm.reason}</p>}
            </>
          )}
          {err && <p className="error">{err}</p>}
        </section>

        <section className="panel">
          <h2>Abstract</h2>
          <p className="abstract">{p.abstract || 'abstract 정보가 없습니다.'}</p>
        </section>

        <section className="panel">
          <h2>내 메모</h2>
          <MarkdownEditor key={p.id} initial={p.memo} private
            onSave={async (content) => {
              const r = await api<{ path: string }>(`/papers/${id}/note`, { method: 'PUT', json: { content } })
              if (!p.note_path) setP({ ...p, note_path: r.path, memo: content })
            }} />
          {p.note_path && <p className="muted small">파일: {p.note_path}</p>}
        </section>
      </div>

      <aside className="note-side">
        <section className="panel">
          <h2>키워드 · 분류</h2>
          <div className="chips">{[...p.keywords, ...p.categories].map((k) => <span key={k} className="chip">{k}</span>)}</div>
          {cls.field ? (
            <p>
              <a href={href('world', `field-${cls.field.id}`)}>{cls.field.name}</a> › {cls.subfield?.name}
            </p>
          ) : <p className="muted small">Research World에 포함되면(⭐ 관심 표시, 소스의 "World에 포함", 프로젝트 레퍼런스) 분야가 자동 분류됩니다.</p>}
          {cls.subfield && (
            <details onToggle={(e) => { if ((e.target as HTMLDetailsElement).open && !subs.length) api<WorldLite>('/world').then((w) => setSubs(w.fields)) }}>
              <summary className="small">다른 세부 분야로 옮기기</summary>
              <select value={cls.subfield.id} onChange={(e) => move(+e.target.value)} aria-label="세부 분야">
                {subs.map((f) => (
                  <optgroup key={f.id} label={f.name}>
                    {f.subfields.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </optgroup>
                ))}
              </select>
            </details>
          )}
        </section>
        <section className="panel">
          <h2>관련 논문</h2>
          <h3>이 논문이 인용한 논문</h3>
          <BriefList items={p.related.cites} empty="앱에 있는 논문 중 없음" />
          <h3>이 논문을 인용한 논문</h3>
          <BriefList items={p.related.cited_by} empty="앱에 있는 논문 중 없음" />
          <h3>의미적으로 비슷한 논문</h3>
          <BriefList items={p.related.similar} empty="비슷한 논문 없음" />
        </section>
        <section className="panel">
          <h2>사용처</h2>
          {p.projects.length ? (
            <ul className="brief-list">{p.projects.map((r) => <li key={r.project_id}><a href={href('project', r.project_id, 'references')}>{r.name}</a> <span className="tag">{r.role}</span></li>)}</ul>
          ) : <p className="muted small">이 논문을 레퍼런스로 등록한 프로젝트가 없습니다.</p>}
        </section>
        <section className="panel">
          <h2>백링크</h2>
          {p.backlinks.length ? (
            <ul className="brief-list">
              {p.backlinks.map((b, i) => (
                <li key={i}>{b.kind === 'paper'
                  ? <a href={href('paper', b.paper_id)}>{b.title}</a>
                  : <a href={href('project', b.project_id, 'notes', b.note)}>{b.project} / {b.note}</a>}</li>
              ))}
            </ul>
          ) : <p className="muted small">이 논문을 [[링크]]한 노트가 없습니다.</p>}
        </section>
      </aside>
    </section>
  )
}

