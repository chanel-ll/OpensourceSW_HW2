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
  keywords: string[]; paper_count: number; last_updated: string | null; authors: SourceAuthor[]
}
export type Candidate = {
  provider: 'openalex' | 's2'; id: string; name: string; affiliation: string
  paper_count: number | null; recent_papers: { title: string; year: number }[]
}
export type Status = {
  llm: { enabled: boolean; model: string; reason: string }
  job: { running: boolean; kind: string; message: string; error: string; queued: number }
  last_update: string | null; update_due: boolean; unread_changes: number; credit: number | null
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
