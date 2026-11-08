import { useEffect, useMemo, useState } from 'react'
import { api, go, href, type LibraryData, type Status } from './api'
import { PaperCard } from './PaperCard'

type Item = LibraryData['papers'][number]
const SORTS = { recent: '최근 관심순', year: '연도순', title: '제목순' } as const

export function Library({ group, llm, registered, onChanged }: {
  group: string; llm: Status['llm']; registered: Set<string>; onChanged: () => void
}) {
  const [data, setData] = useState<LibraryData | null>(null)
  const [err, setErr] = useState('')
  const [newName, setNewName] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<keyof typeof SORTS>('recent')
  const [picked, setPicked] = useState<Set<number>>(new Set())

  const load = () => api<LibraryData>('/library').then(setData, (e) => setErr(e.message))
  useEffect(() => { load() }, [])
  useEffect(() => setPicked(new Set()), [group])

  async function run(fn: () => Promise<unknown>) {
    setErr('')
    try {
      await fn()
      await load()
      onChanged()
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  const gid = +group || 0
  const current = data?.groups.find((g) => g.id === gid)
  const shown = useMemo(() => {
    const s = q.toLowerCase()
    const xs = (data?.papers ?? []).filter((p) =>
      p.starred &&
      (group === 'unsorted' ? !p.group_ids.length : gid ? p.group_ids.includes(gid) : true) &&
      (!s || p.title.toLowerCase().includes(s) || p.keywords.some((k) => k.includes(s)) || p.authors.some((a) => a.name.toLowerCase().includes(s))))
    if (sort === 'year') return [...xs].sort((a, b) => (b.pub_date ?? String(b.year)).localeCompare(a.pub_date ?? String(a.year)))
    if (sort === 'title') return [...xs].sort((a, b) => a.title.localeCompare(b.title))
    return xs
  }, [data, group, gid, q, sort])

  const create = (e: React.FormEvent) => {
    e.preventDefault()
    run(async () => {
      const g = await api<{ id: number }>('/library/groups', { method: 'POST', json: { name: newName } })
      setNewName('')
      go('library', g.id)
    })
  }
  const add = (g: number, ids: number[]) => run(() => Promise.all(ids.map((id) => api(`/library/groups/${g}/papers/${id}`, { method: 'PUT' }))))
  const remove = (g: number, ids: number[]) => run(() => Promise.all(ids.map((id) => api(`/library/groups/${g}/papers/${id}`, { method: 'DELETE' }))))
  const toggle = (id: number) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })

  const total = data?.papers.filter((p) => p.starred).length ?? 0
  const unsorted = data?.papers.filter((p) => p.starred && !p.group_ids.length).length ?? 0
  const groupName = (id: number) => data?.groups.find((g) => g.id === id)?.name ?? ''

  return (
    <section className="page wide library">
      <aside className="panel lib-groups">
        <h2>Library</h2>
        <a href={href('library')} className={`nav-item${!group ? ' active' : ''}`}>전체 관심 논문 <span className="muted">{total}</span></a>
        <a href={href('library', 'unsorted')} className={`nav-item${group === 'unsorted' ? ' active' : ''}`}>미분류 <span className="muted">{unsorted}</span></a>
        <h3>내 그룹</h3>
        {data?.groups.map((g) => (
          <a key={g.id} href={href('library', g.id)} className={`nav-item${gid === g.id ? ' active' : ''}`} title={g.name}>
            <span className="ellipsis">{g.name}</span> <span className="muted">{g.count}</span>
          </a>
        ))}
        <form onSubmit={create} className="row">
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="새 그룹 (예: 읽을 논문)" aria-label="새 그룹 이름" />
          <button disabled={!newName.trim()}>추가</button>
        </form>
      </aside>

      <div className="lib-main">
        <div className="row">
          <h1>{current ? current.name : group === 'unsorted' ? '미분류' : '전체 관심 논문'}</h1>
          {current && (
            <>
              <button className="link-btn small" onClick={() => {
                const name = window.prompt('그룹 이름', current.name)
                if (name && name !== current.name) run(() => api(`/library/groups/${current.id}`, { method: 'PATCH', json: { name } }))
              }}>이름 변경</button>
              <button className="link-btn small danger" onClick={() => {
                if (window.confirm(`'${current.name}' 그룹을 삭제할까요? 논문은 Library에 그대로 남습니다.`))
                  run(async () => { await api(`/library/groups/${current.id}`, { method: 'DELETE' }); go('library') })
              }}>그룹 삭제</button>
            </>
          )}
        </div>
        <div className="filters">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목 · 키워드 · 저자 검색" aria-label="Library 검색" />
          <select value={sort} onChange={(e) => setSort(e.target.value as keyof typeof SORTS)} aria-label="정렬">
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <span className="muted">{shown.length}편</span>
        </div>
        {picked.size > 0 && (
          <div className="notice row bulk">
            <b>{picked.size}편 선택</b>
            <select value="" onChange={(e) => { if (e.target.value) { add(+e.target.value, [...picked]); setPicked(new Set()) } }} aria-label="선택한 논문을 그룹에 추가">
              <option value="">그룹에 추가…</option>
              {data?.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
            {current && <button onClick={() => { remove(current.id, [...picked]); setPicked(new Set()) }}>이 그룹에서 빼기</button>}
            <button onClick={() => setPicked(new Set(shown.map((p) => p.id)))}>모두 선택</button>
            <button onClick={() => setPicked(new Set())}>선택 해제</button>
          </div>
        )}
        {err && <p className="error">{err}</p>}
        {data && total === 0 && <p className="muted">관심 논문이 없습니다. 논문 카드의 ☆를 누르면 여기에 모입니다.</p>}
        {data && total > 0 && !shown.length && <p className="muted">이 목록에 논문이 없습니다.</p>}
        <div className="cards">
          {shown.map((p) => (
            <PaperCard key={p.id} paper={p} llm={llm} registered={registered}
              onChange={(np) => { setData((d) => d && { ...d, papers: d.papers.map((x) => (x.id === np.id ? { ...x, ...np } : x)) }); if (np.starred !== p.starred) onChanged() }}
              extra={<GroupChips p={p} picked={picked.has(p.id)} onPick={() => toggle(p.id)} groups={data!.groups} groupName={groupName}
                onAdd={(g) => add(g, [p.id])} onRemove={(g) => remove(g, [p.id])} />} />
          ))}
        </div>
      </div>
    </section>
  )
}

function GroupChips({ p, picked, onPick, groups, groupName, onAdd, onRemove }: {
  p: Item; picked: boolean; onPick: () => void; groups: LibraryData['groups']; groupName: (id: number) => string
  onAdd: (g: number) => void; onRemove: (g: number) => void
}) {
  const free = groups.filter((g) => !p.group_ids.includes(g.id))
  return (
    <div className="chips lib-chips">
      <label className="check"><input type="checkbox" checked={picked} onChange={onPick} aria-label="선택" /></label>
      {p.group_ids.map((g) => (
        <span key={g} className="chip group-chip">
          <a href={href('library', g)}>{groupName(g)}</a>
          <button className="link-btn" onClick={() => onRemove(g)} aria-label={`${groupName(g)}에서 빼기`}>×</button>
        </span>
      ))}
      {free.length > 0 && (
        <select className="mini" value="" onChange={(e) => e.target.value && onAdd(+e.target.value)} aria-label="그룹에 추가">
          <option value="">+ 그룹</option>
          {free.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
      )}
    </div>
  )
}
