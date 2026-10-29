import { useEffect, useMemo, useState } from 'react'
import { api, fmtDate, type Paper, type Source, type Status } from './api'
import { normName, PaperCard } from './PaperCard'

const ORG: Record<string, string> = { university: '대학 연구실', company: '기업 연구팀', individual: '개인 연구자' }

export function registeredSet(sources: Source[]) {
  const s = new Set<string>()
  for (const src of sources)
    for (const a of src.authors) {
      if (a.openalex_id) s.add(a.openalex_id)
      if (a.s2_id) s.add(a.s2_id)
      s.add(normName(a.name))
    }
  return s
}

export function PaperList({ query, llm, registered, reloadKey }: {
  query: string; llm: Status['llm']; registered: Set<string>; reloadKey: unknown
}) {
  const [papers, setPapers] = useState<Paper[] | null>(null)
  const [err, setErr] = useState('')
  const [year, setYear] = useState('')
  const [venue, setVenue] = useState('')
  const [kw, setKw] = useState('')
  const [q, setQ] = useState('')
  const [showHidden, setShowHidden] = useState(false)

  useEffect(() => {
    setErr('')
    api<Paper[]>(`/papers?${query}&include_hidden=true`).then(setPapers, (e) => setErr(e.message))
  }, [query, reloadKey])

  const opts = useMemo(() => {
    const ps = papers ?? []
    const count = (xs: string[]) => [...xs.reduce((m, x) => m.set(x, (m.get(x) ?? 0) + 1), new Map<string, number>())].sort((a, b) => b[1] - a[1])
    return {
      years: [...new Set(ps.map((p) => p.year).filter(Boolean))].sort((a, b) => b! - a!),
      venues: count(ps.map((p) => (p.is_preprint || !p.venue ? 'arXiv preprint' : p.venue))),
      kws: count(ps.flatMap((p) => [...p.keywords, ...p.categories])).slice(0, 40),
    }
  }, [papers])

  const shown = (papers ?? []).filter((p) =>
    (showHidden || !p.hidden) &&
    (!year || String(p.year) === year) &&
    (!venue || (venue === 'arXiv preprint' ? p.is_preprint || !p.venue : p.venue === venue)) &&
    (!kw || p.keywords.includes(kw) || p.categories.includes(kw)) &&
    (!q || p.title.toLowerCase().includes(q.toLowerCase())))
  const hiddenCount = (papers ?? []).filter((p) => p.hidden).length

  if (err) return <p className="error">논문 목록을 불러오지 못했습니다: {err}</p>
  if (!papers) return <p className="muted">불러오는 중…</p>
  return (
    <>
      <div className="filters">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목 검색" aria-label="제목 검색" />
        <select value={year} onChange={(e) => setYear(e.target.value)} aria-label="연도">
          <option value="">전체 연도</option>
          {opts.years.map((y) => <option key={y} value={String(y)}>{y}</option>)}
        </select>
        <select value={venue} onChange={(e) => setVenue(e.target.value)} aria-label="학회·저널">
          <option value="">전체 학회·저널</option>
          {opts.venues.map(([v, n]) => <option key={v} value={v}>{v} ({n})</option>)}
        </select>
        <select value={kw} onChange={(e) => setKw(e.target.value)} aria-label="키워드">
          <option value="">전체 키워드</option>
          {opts.kws.map(([k, n]) => <option key={k} value={k}>{k} ({n})</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)} /> 숨긴 논문 {hiddenCount}편 보기</label>
        <span className="muted">{shown.length} / {papers.length}편</span>
      </div>
      {!llm.enabled && <p className="notice">요약 기능 비활성: {llm.reason} 나머지 기능은 정상 동작합니다.</p>}
      <div className="cards">
        {shown.map((p) => (
          <PaperCard key={p.id} paper={p} llm={llm} registered={registered}
            onChange={(np) => setPapers((ps) => ps!.map((x) => (x.id === np.id ? np : x)))} />
        ))}
        {shown.length === 0 && <p className="muted">조건에 맞는 논문이 없습니다.</p>}
      </div>
    </>
  )
}

export function SourceView({ source: s, llm, registered, onChanged, onDeleted }: {
  source: Source; llm: Status['llm']; registered: Set<string>; onChanged: () => void; onDeleted: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(s.name)
  const [err, setErr] = useState('')
  useEffect(() => setName(s.name), [s.name])

  async function act(fn: () => Promise<unknown>) {
    setErr('')
    try {
      await fn()
      onChanged()
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  const rename = () => act(async () => {
    await api(`/sources/${s.id}`, { method: 'PATCH', json: { name } })
    setEditing(false)
  })

  return (
    <section className="page">
      <header className="source-head">
        {editing ? (
          <div className="row">
            <input value={name} onChange={(e) => setName(e.target.value)} aria-label="탭 이름" />
            <button className="primary" onClick={rename}>저장</button>
            <button onClick={() => { setEditing(false); setName(s.name) }}>취소</button>
          </div>
        ) : (
          <h1>{s.name} <button className="link-btn small" onClick={() => setEditing(true)}>이름 수정</button></h1>
        )}
        <dl className="meta-grid">
          <div><dt>소스 유형</dt><dd>저자 그룹 · {ORG[s.org_type] ?? s.org_type}</dd></div>
          <div><dt>등록 저자</dt><dd>{s.authors.map((a) => `${a.name}${a.affiliation ? ` (${a.affiliation.split('; ')[0]})` : ''} [${a.openalex_id ? 'OpenAlex' : 'S2'}]`).join(', ')}</dd></div>
          <div><dt>원본 페이지</dt><dd>{s.homepage_url ? <a href={s.homepage_url} target="_blank" rel="noreferrer">{s.homepage_url}</a> : '없음'}</dd></div>
          <div><dt>수집 논문</dt><dd>{s.paper_count}편</dd></div>
          <div><dt>마지막 업데이트</dt><dd>{fmtDate(s.last_updated)}</dd></div>
          <div><dt>대표 키워드</dt><dd className="chips">{s.keywords.map((k) => <span key={k} className="chip">{k}</span>)}</dd></div>
        </dl>
        <div className="row">
          <button onClick={() => act(() => api(`/sources/${s.id}/collect`, { method: 'POST' }))} disabled={s.status === 'collecting'}>다시 수집</button>
          <button disabled title="Research World는 P2에서 제공 예정">World에 포함 (준비 중)</button>
          <button className="danger" onClick={() => window.confirm(`'${s.name}' 소스를 삭제할까요?`) && act(async () => { await api(`/sources/${s.id}`, { method: 'DELETE' }); onDeleted() })}>소스 삭제</button>
        </div>
        {s.status === 'collecting' && <p className="notice">논문 수집 중… {s.status_message}</p>}
        {s.status_message && s.status !== 'collecting' && <p className={s.status === 'error' ? 'error' : 'warn'}>{s.status_message}</p>}
        {err && <p className="error">{err}</p>}
      </header>
      {s.status !== 'collecting' && (
        <PaperList query={`source_id=${s.id}`} llm={llm} registered={registered} reloadKey={s.last_updated} />
      )}
    </section>
  )
}
