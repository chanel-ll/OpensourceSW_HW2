import { useState } from 'react'
import { api, type Paper, type Status } from './api'

type Props = {
  paper: Paper
  llm: Status['llm']
  registered: Set<string> // openalex ids, s2 ids and normalized names of registered authors
  onChange: (p: Paper) => void
  onRead?: (ids: number[]) => void
}

const LINK_LABEL: Record<string, string> = { arxiv: 'arXiv', pdf: 'PDF', doi: 'DOI', s2: 'Semantic Scholar', code: '코드', project: '프로젝트' }
export const normName = (n: string) => n.toLowerCase().replace(/[^a-z]/g, '')

export function PaperCard({ paper: p, llm, registered, onChange, onRead }: Props) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function patch(body: Partial<Paper>) {
    onChange({ ...p, ...(await api<Paper>(`/papers/${p.id}`, { method: 'PATCH', json: body })), change: p.change })
  }
  async function summarize() {
    setBusy(true)
    setErr('')
    try {
      onChange({ ...(await api<Paper>(`/papers/${p.id}/summarize`, { method: 'POST' })), change: p.change })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const isReg = (a: Paper['authors'][number]) =>
    (a.openalex_id && registered.has(a.openalex_id)) || (a.s2_id && registered.has(a.s2_id)) || registered.has(normName(a.name))
  const authors = p.authors.length > 12 ? [...p.authors.slice(0, 10), { name: `외 ${p.authors.length - 10}명` }] : p.authors
  const venue = p.is_preprint || !p.venue ? (p.links.arxiv ? 'arXiv preprint' : '미게재') : p.venue
  const chips = [...p.keywords, ...p.categories.slice(0, 1)].slice(0, 5)
  const read = p.change?.read

  return (
    <article className={`card${p.hidden ? ' is-hidden' : ''}${read ? ' is-read' : ''}`}>
      {p.change && (
        <div className="badges">
          {p.change.kinds.map((k) => <span key={k} className={`badge badge-${k.toLowerCase()}`}>{k}{k === 'ACCEPTED' ? ` · ${p.venue}` : ''}</span>)}
        </div>
      )}
      <div className="card-meta">
        <span className={`venue${p.is_preprint || !p.venue ? ' venue-pre' : ''}`}>{venue}</span>
        <span className="muted">{p.pub_date ?? p.year ?? ''}</span>
      </div>
      <h3 className="card-title">
        <button className="link-btn" title="abstract 펼치기 (논문 노트는 P1에서 제공)" onClick={() => { setOpen(!open); if (p.change && !read) onRead?.(p.change.ids) }}>
          {p.title}
        </button>
      </h3>
      <p className="authors">
        {authors.map((a, i) => (
          <span key={i} className={isReg(a) ? 'author-reg' : ''}>{a.name}{i < authors.length - 1 ? ', ' : ''}</span>
        ))}
      </p>
      {chips.length > 0 && <div className="chips">{chips.map((k) => <span key={k} className="chip">{k}</span>)}</div>}
      {p.summary && <p className="summary"><b>한줄 요약</b> {p.summary.one_line}</p>}
      {open && (
        <div className="detail">
          {p.summary && p.summary.contributions.length > 0 && (
            <><b>핵심 기여</b><ul>{p.summary.contributions.map((c, i) => <li key={i}>{c}</li>)}</ul></>
          )}
          {p.summary && p.summary.keywords.length > 0 && <p className="muted">정제 키워드: {p.summary.keywords.join(', ')}</p>}
          <p className="abstract">{p.abstract || 'abstract 정보가 없습니다.'}</p>
          {p.change && p.change.detail.length > 0 && <p className="muted">변경 내역: {p.change.detail.join(' / ')}</p>}
        </div>
      )}
      <div className="card-foot">
        <div className="links">
          {Object.entries(p.links).map(([k, v]) => <a key={k} href={v} target="_blank" rel="noreferrer">{LINK_LABEL[k] ?? k}</a>)}
        </div>
        <div className="actions">
          {!p.summary && (
            <button onClick={summarize} disabled={!llm.enabled || busy} title={llm.enabled ? `LLM(${llm.model})으로 제목·abstract 요약` : llm.reason}>
              {busy ? '요약 중…' : '요약'}
            </button>
          )}
          <button onClick={() => patch({ starred: !p.starred })} aria-pressed={p.starred} title="관심 표시 (Research World 연동은 P2)">
            {p.starred ? '★' : '☆'}
          </button>
          <button disabled title="My Research는 P1에서 제공 예정">프로젝트에 추가</button>
          <button onClick={() => patch({ hidden: !p.hidden })}>{p.hidden ? '보이기' : '숨기기'}</button>
          {p.change && !read && <button onClick={() => onRead?.(p.change!.ids)}>읽음</button>}
        </div>
      </div>
      {err && <p className="error">{err}</p>}
    </article>
  )
}
