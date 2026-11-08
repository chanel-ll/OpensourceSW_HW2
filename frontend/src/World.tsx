import ForceGraph3D from '3d-force-graph'
import ForceGraph from 'force-graph'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import SpriteText from 'three-spritetext'
import { api, go, type Source } from './api'

type Vec = [number, number, number]
type Sub = { id: number; name: string; count: number; center3: Vec; radius3: number; center2: Vec; radius2: number }
type FieldT = { id: number; name: string; center3: Vec; radius3: number; center2: Vec; radius2: number; subfields: Sub[] }
type WNode = {
  id: number | string; kind: 'paper' | 'project'; title: string; pos3: Vec; pos2: Vec
  authors?: string[]; n_authors?: number; venue?: string; is_preprint?: boolean; year?: number | null
  keywords?: string[]; one_line?: string; starred?: boolean; source_ids?: number[]
  subfield_id?: number | null; field_id?: number | null; project_id?: number; status?: string; n_refs?: number
  // runtime
  x?: number; y?: number; z?: number; fx?: number; fy?: number; fz?: number; __mat?: THREE.MeshLambertMaterial; __label?: SpriteText
}
type WEdge = { source: number | string | WNode; target: number | string | WNode; type: EdgeType; role?: string }
type EdgeType = 'citation' | 'similar' | 'coauthor' | 'manual' | 'project'
type WorldData = { fields: FieldT[]; nodes: WNode[]; edges: WEdge[]; candidates: number; candidate_min: number }

const PALETTE = ['#7aa2f7', '#f7768e', '#9ece6a', '#e0af68', '#bb9af7', '#2ac3de', '#ff9e64', '#73daca']
const EDGE: Record<EdgeType, { label: string; color: string; on: boolean }> = {
  citation: { label: '인용', color: '#e0af68', on: true },
  similar: { label: '의미 유사', color: '#7aa2f7', on: true },
  coauthor: { label: '같은 소스·공저자', color: '#9ece6a', on: false },
  manual: { label: '수동 링크', color: '#f7768e', on: true },
  project: { label: '프로젝트 레퍼런스', color: '#bb9af7', on: true },
}
const PROJECT_COLOR = '#ffd166'
// GPU disabled / remote desktop: 3D cannot start, so open in 2D instead of crashing
const HAS_WEBGL = (() => {
  try {
    const c = document.createElement('canvas')
    const gl = c.getContext('webgl2') || c.getContext('webgl')
    gl?.getExtension('WEBGL_lose_context')?.loseContext() // free the probe context
    return !!gl
  } catch {
    return false
  }
})()

export function World({ sources, focus, onSourcesChanged }: { sources: Source[]; focus: string; onSourcesChanged: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  const g3 = useRef<any>(null)
  const g2 = useRef<any>(null)
  const extras = useRef<{ field: number; obj: THREE.Object3D; label?: boolean; kind: 'field' | 'sub'; center: Vec }[]>([])
  const [data, setData] = useState<WorldData | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [mode, setMode] = useState<'3d' | '2d'>(HAS_WEBGL ? '3d' : '2d')
  const [edgeOn, setEdgeOn] = useState(() => Object.fromEntries(Object.entries(EDGE).map(([k, v]) => [k, v.on])) as Record<EdgeType, boolean>)
  const [src, setSrc] = useState('')
  const [year, setYear] = useState('')
  const [venue, setVenue] = useState('')
  const [starOnly, setStarOnly] = useState(false)
  const [focusField, setFocusField] = useState<number | null>(null)
  const [hover, setHover] = useState<WNode | null>(null)
  const [mouse, setMouse] = useState({ x: 0, y: 0 })
  const [q, setQ] = useState('')

  const load = (path = '/world', method = 'GET', json?: unknown) => {
    setErr('')
    return api<WorldData>(path, { method, json }).then(setData, (e) => setErr(e.message))
  }
  useEffect(() => { load() }, [])

  const fieldColor = useMemo(() => {
    const m = new Map<number, string>()
    data?.fields.forEach((f, i) => m.set(f.id, PALETTE[i % PALETTE.length]))
    return m
  }, [data])
  const visible = (n: WNode) => {
    if (n.kind === 'project') return !src && !year && !venue && !starOnly
    if (src && !n.source_ids?.includes(+src)) return false
    if (year && String(n.year) !== year) return false
    if (venue && (venue === 'arXiv preprint' ? !(n.is_preprint || !n.venue) : n.venue !== venue)) return false
    if (starOnly && !n.starred) return false
    return true
  }
  const visRef = useRef(visible)
  visRef.current = visible
  const edgeRef = useRef(edgeOn)
  edgeRef.current = edgeOn
  const focusRef = useRef(focusField)
  focusRef.current = focusField

  // ---------- build graph ----------
  useEffect(() => {
    if (!data || !box.current) return
    const el = box.current
    el.innerHTML = ''
    const nodes: WNode[] = data.nodes.map((n) => {
      const [x, y, z] = mode === '3d' ? n.pos3 : n.pos2
      return { ...n, x, y, z, fx: x, fy: y, fz: z }
    })
    const links = data.edges.map((e) => ({ ...e }))
    const color = (n: WNode) => (n.kind === 'project' ? PROJECT_COLOR : (n.field_id && fieldColor.get(n.field_id)) || '#8a8f98')
    const onHover = (n: WNode | null) => { setHover(n); el.style.cursor = n ? 'pointer' : 'default' }
    const onClick = (n: WNode) => (n.kind === 'project' ? go('project', n.project_id!) : go('paper', n.id as number))
    const linkVis = (l: WEdge) => edgeRef.current[l.type] && visRef.current(l.source as WNode) && visRef.current(l.target as WNode)

    let g3d
    if (mode === '3d') {
      try {
        g3d = new ForceGraph3D(el, { controlType: 'orbit' })
      } catch (e) {
        setErr(`3D를 시작할 수 없어 2D로 전환했습니다 (${(e as Error).message})`)
        setMode('2d')
        return
      }
    }
    if (mode === '3d' && g3d) {
      const g = g3d
        .backgroundColor('#0b0e14')
        .width(el.clientWidth).height(el.clientHeight)
        .graphData({ nodes, links } as any)
        .cooldownTicks(0)
        .nodeLabel(() => '')
        .nodeThreeObject((n: any) => {
          const node = n as WNode
          const mat = new THREE.MeshLambertMaterial({ color: color(node), transparent: true, opacity: 0.95 })
          const geo = node.kind === 'project' ? new THREE.OctahedronGeometry(9) : new THREE.SphereGeometry(node.starred ? 4.2 : 3, 12, 12)
          const mesh = new THREE.Mesh(geo, mat)
          const label = new SpriteText(node.title.length > 60 ? node.title.slice(0, 57) + '…' : node.title, 2.6, '#e6e9ef')
          label.position.set(0, node.kind === 'project' ? 14 : 7, 0)
          label.visible = node.kind === 'project'
          mesh.add(label)
          node.__mat = mat
          node.__label = label
          return mesh
        })
        .linkColor((l: any) => EDGE[(l as WEdge).type].color)
        .linkOpacity(0.45)
        .linkWidth((l: any) => ((l as WEdge).type === 'project' ? 0.8 : 0.3))
        .linkDirectionalArrowLength((l: any) => ((l as WEdge).type === 'citation' ? 3.5 : 0))
        .linkDirectionalArrowRelPos(1)
        .linkVisibility((l: any) => linkVis(l))
        .nodeVisibility((n: any) => visRef.current(n))
        .onNodeHover((n: any) => onHover(n))
        .onNodeClick((n: any) => onClick(n))
      g.d3Force('charge', null).d3Force('link', null).d3Force('center', null)
      // galaxies (fields) and clusters (subfields)
      extras.current = []
      data.fields.forEach((f) => {
        const c = new THREE.Color(fieldColor.get(f.id))
        const sphere = new THREE.Mesh(new THREE.SphereGeometry(f.radius3, 32, 16),
          new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.045, depthWrite: false }))
        sphere.position.set(...f.center3)
        const label = new SpriteText(f.name, 16, fieldColor.get(f.id))
        label.position.set(f.center3[0], f.center3[1] + f.radius3 + 10, f.center3[2])
        g.scene().add(sphere, label)
        extras.current.push({ field: f.id, obj: sphere, kind: 'field', center: f.center3 },
          { field: f.id, obj: label, label: true, kind: 'field', center: f.center3 })
        f.subfields.forEach((s) => {
          const ring = new THREE.Mesh(new THREE.SphereGeometry(s.radius3, 16, 8),
            new THREE.MeshBasicMaterial({ color: c, wireframe: true, transparent: true, opacity: 0.06, depthWrite: false }))
          ring.position.set(...s.center3)
          const sl = new SpriteText(s.name, 6, '#c8ccd4')
          sl.position.set(s.center3[0], s.center3[1] + s.radius3 + 4, s.center3[2])
          g.scene().add(ring, sl)
          extras.current.push({ field: f.id, obj: ring, kind: 'sub', center: s.center3 },
            { field: f.id, obj: sl, label: true, kind: 'sub', center: s.center3 })
        })
      })
      g.cameraPosition({ x: 0, y: 0, z: 300 + 220 * Math.max(1, data.fields.length) })
      g3.current = g
      // zoom-dependent labels: far -> field names, mid -> subfield names, near -> paper titles
      const cam = g.camera()
      const tick = setInterval(() => {
        const cp = cam.position
        const dist = (c: Vec | THREE.Vector3) => (Array.isArray(c) ? cp.distanceTo(new THREE.Vector3(...c)) : cp.distanceTo(c))
        for (const e of extras.current) {
          if (!e.label) continue
          const d = dist(e.center)
          e.obj.visible = e.kind === 'field' ? d > 420 : d > 90 && d < 900
        }
        for (const n of nodes) {
          if (n.__label && n.kind === 'paper') n.__label.visible = dist(new THREE.Vector3(n.x, n.y, n.z)) < 130
        }
      }, 200)
      const onResize = () => g.width(el.clientWidth).height(el.clientHeight)
      window.addEventListener('resize', onResize)
      return () => { clearInterval(tick); window.removeEventListener('resize', onResize); g._destructor(); g3.current = null }
    }

    // ---------- 2D ----------
    const g = new ForceGraph(el)
      .backgroundColor('#0b0e14')
      .width(el.clientWidth).height(el.clientHeight)
      .graphData({ nodes, links } as any)
      .cooldownTicks(0)
      .nodeLabel(() => '')
      .nodeRelSize(4)
      .nodeCanvasObject((n: any, ctx: CanvasRenderingContext2D, scale: number) => {
        const node = n as WNode
        const dim = focusRef.current && node.field_id !== focusRef.current && node.kind === 'paper'
        ctx.globalAlpha = dim ? 0.15 : 1
        ctx.fillStyle = color(node)
        ctx.beginPath()
        if (node.kind === 'project') {
          const r = 8
          ctx.moveTo(node.x!, node.y! - r); ctx.lineTo(node.x! + r, node.y!); ctx.lineTo(node.x!, node.y! + r); ctx.lineTo(node.x! - r, node.y!)
        } else ctx.arc(node.x!, node.y!, node.starred ? 4 : 3, 0, 2 * Math.PI)
        ctx.fill()
        if (scale > 2.2 || node.kind === 'project') {
          ctx.font = `${11 / scale}px sans-serif`
          ctx.fillStyle = '#e6e9ef'
          ctx.textAlign = 'center'
          ctx.fillText(node.title.length > 50 ? node.title.slice(0, 48) + '…' : node.title, node.x!, node.y! - 6)
        }
        ctx.globalAlpha = 1
      })
      .nodePointerAreaPaint((n: any, c: string, ctx: CanvasRenderingContext2D) => {
        ctx.fillStyle = c
        ctx.beginPath()
        ctx.arc(n.x, n.y, (n as WNode).kind === 'project' ? 9 : 5, 0, 2 * Math.PI)
        ctx.fill()
      })
      .onRenderFramePre((ctx: CanvasRenderingContext2D, scale: number) => {
        data.fields.forEach((f) => {
          const col = fieldColor.get(f.id)!
          const dim = focusRef.current && focusRef.current !== f.id
          ctx.globalAlpha = dim ? 0.25 : 1
          ctx.strokeStyle = col
          ctx.lineWidth = 1.5 / scale
          ctx.setLineDash([])
          ctx.beginPath(); ctx.arc(f.center2[0], f.center2[1], f.radius2, 0, 2 * Math.PI); ctx.stroke()
          ctx.fillStyle = col + '10'
          ctx.fill()
          if (scale < 1.6) {
            ctx.font = `bold ${16 / scale}px sans-serif`
            ctx.fillStyle = col
            ctx.textAlign = 'center'
            ctx.fillText(f.name, f.center2[0], f.center2[1] - f.radius2 - 6 / scale)
          }
          f.subfields.forEach((s) => {
            ctx.setLineDash([4 / scale, 4 / scale])
            ctx.strokeStyle = col + '99'
            ctx.beginPath(); ctx.arc(s.center2[0], s.center2[1], s.radius2, 0, 2 * Math.PI); ctx.stroke()
            if (scale >= 1.0 && scale < 4) {
              ctx.font = `${10 / scale}px sans-serif`
              ctx.fillStyle = '#c8ccd4'
              ctx.textAlign = 'center'
              ctx.fillText(s.name, s.center2[0], s.center2[1] - s.radius2 - 3 / scale)
            }
          })
          ctx.globalAlpha = 1
          ctx.setLineDash([])
        })
      })
      .linkColor((l: any) => EDGE[(l as WEdge).type].color + '88')
      .linkWidth((l: any) => ((l as WEdge).type === 'project' ? 1.2 : 0.5))
      .linkDirectionalArrowLength((l: any) => ((l as WEdge).type === 'citation' ? 3 : 0))
      .linkDirectionalArrowRelPos(1)
      .linkVisibility((l: any) => linkVis(l))
      .nodeVisibility((n: any) => visRef.current(n))
      .onNodeHover((n: any) => onHover(n))
      .onNodeClick((n: any) => onClick(n))
    g.d3Force('charge', null).d3Force('link', null).d3Force('center', null)
    setTimeout(() => g.zoomToFit(400, 40), 50)
    g2.current = g
    const onResize = () => g.width(el.clientWidth).height(el.clientHeight)
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); g._destructor(); g2.current = null }
  }, [data, mode, fieldColor])

  // re-evaluate visibility when filters change
  useEffect(() => {
    const g = g3.current ?? g2.current
    if (!g) return
    g.nodeVisibility(g.nodeVisibility()).linkVisibility(g.linkVisibility())
  }, [edgeOn, src, year, venue, starOnly, data, mode])

  // focus a field: fly the camera there and dim everything else
  useEffect(() => {
    if (!data) return
    const f = data.fields.find((x) => x.id === focusField)
    if (g3.current) {
      for (const n of g3.current.graphData().nodes as WNode[])
        if (n.__mat && n.kind === 'paper') n.__mat.opacity = !focusField || n.field_id === focusField ? 0.95 : 0.12
      for (const e of extras.current)
        if (!e.label) ((e.obj as THREE.Mesh).material as THREE.MeshBasicMaterial).opacity =
          !focusField || e.field === focusField ? (e.kind === 'field' ? 0.045 : 0.06) : 0.01
      if (f) g3.current.cameraPosition({ x: f.center3[0], y: f.center3[1], z: f.center3[2] + f.radius3 * 2.6 }, { x: f.center3[0], y: f.center3[1], z: f.center3[2] }, 1000)
    }
    if (g2.current && f) { g2.current.centerAt(f.center2[0], f.center2[1], 800); g2.current.zoom(Math.min(4, 300 / f.radius2), 800) }
  }, [focusField, data, mode])

  function flyTo(n: WNode) {
    if (g3.current) {
      const p = g3.current.graphData().nodes.find((x: WNode) => x.id === n.id) as WNode
      g3.current.cameraPosition({ x: p.x!, y: p.y!, z: p.z! + 60 }, { x: p.x!, y: p.y!, z: p.z! }, 1200)
    } else if (g2.current) {
      g2.current.centerAt(n.pos2[0], n.pos2[1], 800)
      g2.current.zoom(6, 800)
    }
    setHover(n)
  }
  // deep link: #/world/field-3 or #/world/project-2
  useEffect(() => {
    if (!data || !focus) return
    const [kind, id] = focus.split('-')
    if (kind === 'field') setFocusField(+id)
    if (kind === 'project') {
      const n = data.nodes.find((x) => x.id === focus)
      if (n) setTimeout(() => flyTo(n), 300)
    }
  }, [data, focus])

  function search(e: React.FormEvent) {
    e.preventDefault()
    const s = q.toLowerCase()
    const n = data?.nodes.find((x) => x.title.toLowerCase().includes(s)) ?? data?.nodes.find((x) => x.keywords?.some((k) => k.includes(s)))
    if (n) flyTo(n)
    else setErr(`'${q}'에 해당하는 노드가 없습니다.`)
  }
  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    try { await fn() } catch (e) { setErr((e as Error).message) } finally { setBusy('') }
  }
  const rename = (kind: 'fields' | 'subfields', id: number, old: string) => {
    const name = window.prompt('새 이름 (재분류 때도 유지됩니다)', old)
    if (name && name !== old) act('이름 변경', async () => { await api(`/world/${kind}/${id}`, { method: 'PATCH', json: { name } }); await load() })
  }
  const merge = (kind: 'fields' | 'subfields', id: number, into: number) =>
    act('합치는 중', () => load(`/world/${kind}/${id}/merge`, 'POST', { into }))

  const papers = data?.nodes.filter((n) => n.kind === 'paper') ?? []
  const years = [...new Set(papers.map((n) => n.year).filter(Boolean))].sort((a, b) => b! - a!)
  const venues = [...new Set(papers.map((n) => (n.is_preprint || !n.venue ? 'arXiv preprint' : n.venue!)))].sort()
  const allSubs = data?.fields.flatMap((f) => f.subfields.map((s) => ({ ...s, field: f.name }))) ?? []

  return (
    <section className="world">
      <aside className="world-side">
        <div className="row toggle" role="group" aria-label="보기 모드">
          <button aria-pressed={mode === '3d'} onClick={() => setMode('3d')} disabled={!HAS_WEBGL}
            title={HAS_WEBGL ? '' : '이 브라우저에서 WebGL을 사용할 수 없습니다 (하드웨어 가속 꺼짐 등)'}>3D</button>
          <button aria-pressed={mode === '2d'} onClick={() => setMode('2d')}>2D</button>
          <button onClick={() => act('재분류 중', () => load('/world/recluster', 'POST'))} disabled={!!busy} title="사용자가 고친 이름·이동·합치기는 유지됩니다">재분류</button>
        </div>
        {!HAS_WEBGL && <p className="notice small">WebGL을 사용할 수 없어 2D로 표시합니다. Chrome 설정의 "가능한 경우 그래픽 가속 사용"을 켜면 3D를 볼 수 있습니다.</p>}
        <h3>World에 넣을 것 <span className="muted small">논문 {papers.length}편</span></h3>
        {sources.map((s) => (
          <label key={s.id} className="check" title="이 소스의 논문 전체를 World에 넣습니다">
            <input type="checkbox" checked={s.include_in_world} disabled={!!busy}
              onChange={(e) => act('World 갱신 중', async () => {
                await api(`/sources/${s.id}`, { method: 'PATCH', json: { include_in_world: e.target.checked } })
                onSourcesChanged()
                await load()
              })} />
            <span className="ellipsis">{s.name}</span> <span className="muted">{s.paper_count}</span>
          </label>
        ))}
        <p className="muted small">+ ⭐ 관심 표시한 논문, 프로젝트 레퍼런스</p>
        <form onSubmit={search}><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목·키워드로 찾아가기" aria-label="World 검색" /></form>
        <h3>필터</h3>
        <select value={src} onChange={(e) => setSrc(e.target.value)} aria-label="소스"><option value="">전체 소스</option>{sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        <select value={year} onChange={(e) => setYear(e.target.value)} aria-label="연도"><option value="">전체 연도</option>{years.map((y) => <option key={y}>{y}</option>)}</select>
        <select value={venue} onChange={(e) => setVenue(e.target.value)} aria-label="학회"><option value="">전체 학회·저널</option>{venues.map((v) => <option key={v}>{v}</option>)}</select>
        <label className="check"><input type="checkbox" checked={starOnly} onChange={(e) => setStarOnly(e.target.checked)} /> 관심 논문만</label>
        <h3>연결선</h3>
        {(Object.keys(EDGE) as EdgeType[]).map((k) => (
          <label key={k} className="check">
            <input type="checkbox" checked={edgeOn[k]} onChange={(e) => setEdgeOn({ ...edgeOn, [k]: e.target.checked })} />
            <span className="swatch" style={{ background: EDGE[k].color }} /> {EDGE[k].label} <span className="muted">{data?.edges.filter((x) => x.type === k).length ?? 0}</span>
          </label>
        ))}
        <h3>분야 <span className="muted small">{focusField ? <button className="link-btn small" onClick={() => setFocusField(null)}>전체 보기</button> : '클릭하면 확대'}</span></h3>
        {data?.fields.map((f) => (
          <div key={f.id} className="field-item">
            <div className="row">
              <span className="swatch" style={{ background: fieldColor.get(f.id) }} />
              <button className={`link-btn${focusField === f.id ? ' on' : ''}`} onClick={() => setFocusField(f.id)}>{f.name}</button>
              <button className="link-btn small" onClick={() => rename('fields', f.id, f.name)} aria-label={`${f.name} 이름 변경`}>✎</button>
              {data.fields.length > 1 && (
                <select className="mini" value="" onChange={(e) => e.target.value && merge('fields', f.id, +e.target.value)} aria-label={`${f.name}을 다른 분야와 합치기`}>
                  <option value="">합치기</option>
                  {data.fields.filter((x) => x.id !== f.id).map((x) => <option key={x.id} value={x.id}>→ {x.name}</option>)}
                </select>
              )}
            </div>
            <ul>
              {f.subfields.map((s) => (
                <li key={s.id} className="row">
                  <span className="ellipsis">{s.name}</span> <span className="muted small">{s.count}</span>
                  <button className="link-btn small" onClick={() => rename('subfields', s.id, s.name)} aria-label={`${s.name} 이름 변경`}>✎</button>
                  {allSubs.length > 1 && (
                    <select className="mini" value="" onChange={(e) => e.target.value && merge('subfields', s.id, +e.target.value)} aria-label={`${s.name} 합치기`}>
                      <option value="">합치기</option>
                      {allSubs.filter((x) => x.id !== s.id).map((x) => <option key={x.id} value={x.id}>→ {x.name}</option>)}
                    </select>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {!!data?.candidates && (
          <div className={data.candidates >= data.candidate_min ? 'warn' : 'notice'}>
            어디에도 잘 맞지 않는 논문 {data.candidates}편 (아래쪽에 모여 있음)
            {data.candidates >= data.candidate_min && ' — 새 세부 분야 후보입니다.'}
            <button onClick={() => act('생성 중', () => load('/world/candidates', 'POST'))}>세부 분야로 만들기</button>
          </div>
        )}
        {busy && <p className="muted">{busy}…</p>}
        {err && <p className="error">{err}</p>}
      </aside>
      <div className="world-canvas" onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setMouse({ x: e.clientX - r.left, y: e.clientY - r.top }) }}>
        {data && papers.length < 2 && (
          <div className="world-empty">
            <p>World가 비어 있습니다.</p>
            <p className="muted">왼쪽 "World에 넣을 것"에서 소스를 체크하거나, 논문 카드의 ☆ 관심 표시·프로젝트 레퍼런스로 논문을 넣으세요.</p>
          </div>
        )}
        {!data && !err && <div className="world-empty"><p>분류 중… (처음에는 임베딩 계산으로 수십 초 걸릴 수 있습니다)</p></div>}
        <div ref={box} className="world-graph" />
        {hover && (
          <div className="hover-card" style={{ left: Math.min(mouse.x + 16, (box.current?.clientWidth ?? 800) - 320), top: mouse.y + 16 }}>
            {hover.kind === 'project' ? (
              <><b>◆ {hover.title}</b><div className="muted">내 프로젝트 · {hover.status} · 레퍼런스 {hover.n_refs}편</div></>
            ) : (
              <>
                <b>{hover.title}</b>
                <div className="muted">{hover.authors?.join(', ')}{(hover.n_authors ?? 0) > 2 ? ' 외' : ''}</div>
                <div><span className="venue">{hover.is_preprint || !hover.venue ? 'arXiv preprint' : hover.venue}</span> {hover.year}</div>
                <div className="chips">{hover.keywords?.slice(0, 4).map((k) => <span key={k} className="chip">{k}</span>)}</div>
                {hover.one_line && <div className="small">{hover.one_line}</div>}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
