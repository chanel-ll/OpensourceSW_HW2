import { useState, type ReactNode } from 'react'
import { api, href, ROLES, type Paper, type ProjectSummary, type Status } from './api'

/** "프로젝트에 추가": pick a project (and role) inline. */
export function AddToProject({ paperId, onAdded }: { paperId: number; onAdded?: () => void }) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [role, setRole] = useState(ROLES[1])
  const [msg, setMsg] = useState('')
  if (projects === null)
    return <button onClick={() => api<ProjectSummary[]>('/projects').then(setProjects, (e) => setMsg(e.message))}>프로젝트에 추가</button>
  if (!projects.length) return <span className="muted small">프로젝트가 없습니다. <a href={href('projects')}>My Research</a>에서 먼저 만드세요.</span>
  async function add(pid: number) {
    try {
      await api(`/projects/${pid}/references`, { method: 'POST', json: { paper_id: paperId, role } })
      setMsg(`'${projects!.find((p) => p.id === pid)?.name}'에 추가됨`)
      setProjects(null)
      onAdded?.()
    } catch (e) {
      setMsg((e as Error).message)
    }
  }
  return (
    <span className="row inline">
      <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="역할 태그">{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
      <select defaultValue="" onChange={(e) => e.target.value && add(+e.target.value)} aria-label="추가할 프로젝트">
        <option value="" disabled>프로젝트 선택…</option>
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <button onClick={() => setProjects(null)}>취소</button>
      {msg && <span className="muted small">{msg}</span>}
    </span>
  )
}

type Props = {
  paper: Paper
  llm: Status['llm']
  registered: Set<string> // openalex ids, s2 ids and normalized names of registered authors
  onChange: (p: Paper) => void
  onRead?: (ids: number[]) => void
  extra?: ReactNode // e.g. Library group chips
}

const LINK_LABEL: Record<string, string> = { arxiv: 'arXiv', pdf: 'PDF', doi: 'DOI', s2: 'Semantic Scholar', code: '코드', project: '프로젝트' }
export const normName = (n: string) => n.toLowerCase().replace(/[^a-z]/g, '')

export function PaperCard({ paper: p, llm, registered, onChange, onRead, extra }: Props) {
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
        <a className="title-link" href={href('paper', p.id)} title="논문 노트 열기" onClick={() => { if (p.change && !read) onRead?.(p.change.ids) }}>
          {p.title}
        </a>
        <button className="link-btn small" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? 'abstract 접기' : 'abstract'}</button>
      </h3>
      <p className="authors">
        {authors.map((a, i) => (
          <span key={i} className={isReg(a) ? 'author-reg' : ''}>{a.name}{i < authors.length - 1 ? ', ' : ''}</span>
        ))}
      </p>
      {chips.length > 0 && <div className="chips">{chips.map((k) => <span key={k} className="chip">{k}</span>)}</div>}
      {extra}
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
          <button onClick={() => patch({ starred: !p.starred })} aria-pressed={p.starred} title="관심 표시 — Research World에 포함">
            {p.starred ? '★' : '☆'}
          </button>
          <AddToProject paperId={p.id} />
          <button onClick={() => patch({ hidden: !p.hidden })}>{p.hidden ? '보이기' : '숨기기'}</button>
          {p.change && !read && <button onClick={() => onRead?.(p.change!.ids)}>읽음</button>}
        </div>
      </div>
      {err && <p className="error">{err}</p>}
    </article>
  )
}
