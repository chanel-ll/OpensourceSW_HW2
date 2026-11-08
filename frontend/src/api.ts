export type Author = { name: string; openalex_id?: string; s2_id?: string }
export type Change = { kinds: string[]; detail: string[]; read: boolean; ids: number[]; source_id: number | null }
export type Summary = { one_line: string; contributions: string[]; keywords: string[]; model: string }
export type Paper = {
  id: number; title: string; abstract: string; year: number | null; pub_date: string | null
  venue: string; is_preprint: boolean; authors: Author[]; links: Record<string, string>
  keywords: string[]; categories: string[]; summary: Summary | null
  starred: boolean; hidden: boolean; source_ids: number[]; change?: Change | null
}
export type SourceAuthor = { id: number; name: string; affiliation: string; openalex_id: string | null; s2_id: string | null; dblp_pid: string | null }
export type Source = {
  id: number; name: string; name_source: string; kind: string; org_type: string; homepage_url: string
  page_title: string; status: 'draft' | 'collecting' | 'ready' | 'error'; status_message: string
  keywords: string[]; paper_count: number; last_updated: string | null; authors: SourceAuthor[]; include_in_world: boolean
}
export type Candidate = {
  provider: 'openalex' | 's2'; id: string; name: string; affiliation: string
  paper_count: number | null; recent_papers: { title: string; year: number }[]
}
export type Status = {
  llm: { enabled: boolean; model: string; reason: string }
  job: { running: boolean; kind: string; message: string; error: string; queued: number }
  last_update: string | null; update_due: boolean; unread_changes: number; starred_count: number; credit: number | null
}
export type WeeklyRun = {
  id: number; started_at: string; finished_at: string | null; status: string; trigger: string
  errors: string[]; period_start: string
  counts: { new: number; accepted: number; updated: number; sources: number }
  items: Paper[]
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const res = await fetch('/api' + path, {
    ...rest,
    headers: json !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const d = data?.detail
    throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : `HTTP ${res.status}`)
  }
  return data as T
}

export const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }) : '없음'

export const venueLabel = (p: Paper) => (p.is_preprint || !p.venue ? 'arXiv preprint' : `${p.venue}${p.year ? ' ' + p.year : ''}`)

// ---------- P1 / P2 ----------
export type Brief = { id: number; title: string; year: number | null; venue: string; similarity?: number }
export type Backlink = { kind: 'paper'; paper_id: number; title: string } | { kind: 'project'; project_id: number; project: string; note: string }
export type PaperDetail = Paper & {
  sources: { id: number; name: string }[]
  classification: { field: { id: number; name: string } | null; subfield: { id: number; name: string } | null }
  related: { cites: Brief[]; cited_by: Brief[]; similar: Brief[] }
  memo: string; note_path: string; backlinks: Backlink[]
  projects: { project_id: number; name: string; role: string; memo: string }[]
}
export type TitleRef = { id: number; title: string; link: string; year: number | null }
export type ProjectSummary = {
  id: number; name: string; description: string; status: string; folder: string
  note_count: number; ref_count: number; updated_at: string
}
export type ProjectFull = ProjectSummary & {
  references: (Paper & { role: string; memo: string })[]
  notes: { name: string; updated_at: string }[]
}
export const STATUSES = ['아이디어', '진행 중', '투고 준비', '완료']
export const ROLES = ['베이스라인', '관련 연구', '방법론 참고', '데이터셋']

export type Route =
  | { kind: 'home' } | { kind: 'add' } | { kind: 'weekly' } | { kind: 'projects' } | { kind: 'settings' }
  | { kind: 'source'; id: number } | { kind: 'search'; q: string } | { kind: 'paper'; id: number }
  | { kind: 'project'; id: number; tab: string; note: string } | { kind: 'world'; focus: string } | { kind: 'library'; group: string }

export function parseHash(hash: string): Route {
  const [, kind = '', a = '', b = '', c = ''] = hash.replace(/^#/, '').split('/').map(decodeURIComponent)
  if (kind === 'add') return { kind: 'add' }
  if (kind === 'weekly') return { kind: 'weekly' }
  if (kind === 'projects') return { kind: 'projects' }
  if (kind === 'settings') return { kind: 'settings' }
  if (kind === 'source' && +a) return { kind: 'source', id: +a }
  if (kind === 'paper' && +a) return { kind: 'paper', id: +a }
  if (kind === 'project' && +a) return { kind: 'project', id: +a, tab: b || 'overview', note: c }
  if (kind === 'search') return { kind: 'search', q: a }
  if (kind === 'world') return { kind: 'world', focus: a }
  if (kind === 'library') return { kind: 'library', group: a }
  return { kind: 'home' }
}
export const href = (...parts: (string | number)[]) => '#/' + parts.map((p) => encodeURIComponent(String(p))).join('/')
export const go = (...parts: (string | number)[]) => { location.hash = href(...parts) }

/** Same normalization as the backend's norm_title: [[links]] resolve regardless of punctuation/case. */
export const normTitle = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, '')

export type LibraryGroup = { id: number; name: string; count: number }
export type LibraryData = { groups: LibraryGroup[]; papers: (Paper & { group_ids: number[] })[] }
