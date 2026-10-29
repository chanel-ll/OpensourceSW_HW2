import { useState } from 'react'
import { api, type Candidate, type Source } from './api'

type Inspect = { title: string; org_type: string; names: string[]; error: string }
const ORG = { university: '대학 연구실', company: '기업 연구팀', individual: '개인 연구자' }
const key = (c: Candidate) => `${c.provider}:${c.id}`

export function AddSource({ onCreated }: { onCreated: (s: Source) => void }) {
  const [url, setUrl] = useState('')
  const [info, setInfo] = useState<Inspect | null>(null)
  const [orgType, setOrgType] = useState('university')
  const [name, setName] = useState('')
  const [hint, setHint] = useState('')
  const [cands, setCands] = useState<Candidate[] | null>(null)
  const [candErrors, setCandErrors] = useState<string[]>([])
  const [picked, setPicked] = useState<Map<string, Candidate>>(new Map())
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')

  async function run<T>(label: string, fn: () => Promise<T>) {
    setBusy(label)
    setErr('')
    try {
      return await fn()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  const inspect = () => run('페이지 분석 중…', async () => {
    const r = await api<Inspect>('/sources/inspect', { method: 'POST', json: { url } })
    setInfo(r)
    setOrgType(r.org_type)
    setHint(r.title)
    if (r.names[0]) setName(r.names[0])
  })

  const search = () => run('학술 API에서 저자 후보 조회 중…', async () => {
    const r = await api<{ candidates: Candidate[]; errors: string[] }>(
      `/authors/candidates?name=${encodeURIComponent(name)}&hint=${encodeURIComponent(hint)}`)
    setCands(r.candidates)
    setCandErrors(r.errors)
  })

  function toggle(c: Candidate) {
    const m = new Map(picked)
    if (m.has(key(c))) m.delete(key(c))
    else m.set(key(c), c)
    setPicked(m)
  }

  const confirm = () => run('소스 생성 및 수집 시작…', async () => {
    const s = await api<Source>('/sources', {
      method: 'POST',
      json: { homepage_url: url, page_title: info?.title ?? '', name: info?.title || name, org_type: orgType },
    })
    await api(`/sources/${s.id}/authors`, {
      method: 'POST',
      json: {
        authors: [...picked.values()].map((c) => ({
          name: c.name, affiliation: c.affiliation,
          openalex_id: c.provider === 'openalex' ? c.id : null, s2_id: c.provider === 's2' ? c.id : null,
        })),
      },
    })
    await api(`/sources/${s.id}/collect`, { method: 'POST' })
    onCreated(s)
  })

  return (
    <section className="page add-source">
      <h1>트래킹 소스 추가</h1>

      <div className="step">
        <h2>1. 연구실·팀 페이지</h2>
        <div className="row">
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://… 연구실 또는 팀 웹페이지 (선택)" aria-label="페이지 링크" />
          <button onClick={inspect} disabled={!url || !!busy}>페이지 분석</button>
        </div>
        {info && (
          <div className="inspect">
            {info.error ? <p className="error">페이지를 읽지 못했습니다: {info.error} — 이름을 직접 입력하세요.</p> : <p><b>페이지 제목</b> {info.title || '(없음)'}</p>}
            {info.names.length > 0 && (
              <p>제안된 연구자: {info.names.map((n) => <button key={n} className="chip chip-btn" onClick={() => setName(n)}>{n}</button>)}</p>
            )}
          </div>
        )}
        <div className="row">
          <label>소스 유형
            <select value="author_group" onChange={() => {}}>
              <option value="author_group">저자 그룹</option>
              <option disabled>기관 + 분야 필터 (P3 준비 중)</option>
              <option disabled>페이지 파싱 (P3 준비 중)</option>
            </select>
          </label>
          <label>대상
            <select value={orgType} onChange={(e) => setOrgType(e.target.value)}>
              {Object.entries(ORG).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="step">
        <h2>2. 저자 후보 조회</h2>
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="PI 또는 핵심 연구자 이름 (영문)" aria-label="저자 이름" />
          <input value={hint} onChange={(e) => setHint(e.target.value)} placeholder="소속 힌트 (예: KAIST)" aria-label="소속 힌트" />
          <button onClick={search} disabled={name.trim().length < 2 || !!busy}>후보 찾기</button>
        </div>
        {candErrors.map((e) => <p key={e} className="error">{e}</p>)}
        {cands && cands.length === 0 && <p className="muted">후보가 없습니다. 이름 표기를 바꿔 다시 찾아보세요.</p>}
        {cands && cands.length > 0 && (
          <>
            <p className="muted">동명이인이 많으니 소속과 최근 논문을 보고 맞는 저자를 직접 선택하세요. 같은 사람이 여러 DB에 있으면 모두 선택해도 됩니다.</p>
            <div className="cands">
              {cands.map((c) => (
                <label key={key(c)} className={`cand${picked.has(key(c)) ? ' cand-on' : ''}`}>
                  <input type="checkbox" checked={picked.has(key(c))} onChange={() => toggle(c)} />
                  <div>
                    <div><b>{c.name}</b> <span className="tag">{c.provider === 's2' ? 'Semantic Scholar' : 'OpenAlex'}</span> <span className="muted">논문 {c.paper_count ?? '?'}편</span></div>
                    <div className="muted">{c.affiliation || '소속 정보 없음'}</div>
                    <ul>{c.recent_papers.map((p, i) => <li key={i}>{p.year} · {p.title}</li>)}</ul>
                  </div>
                </label>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="step">
        <h2>3. 확정 및 수집</h2>
        <p>선택한 저자 {picked.size}명: {[...picked.values()].map((c) => `${c.name} (${c.provider})`).join(', ') || '없음'}</p>
        <button className="primary" onClick={confirm} disabled={picked.size === 0 || !!busy}>저자 확정하고 최근 2년 논문 수집</button>
      </div>
      {busy && <p className="muted">{busy}</p>}
      {err && <p className="error">{err}</p>}
    </section>
  )
}
