import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, href, normTitle, type TitleRef } from './api'

let titlesCache: Promise<TitleRef[]> | null = null
export const loadTitles = (fresh = false) => {
  if (fresh || !titlesCache) titlesCache = api<TitleRef[]>('/titles').catch(() => [])
  return titlesCache
}

/** [[target|alias]] -> link to the paper note when the title is in the app, otherwise a dimmed span. */
export function renderMarkdown(text: string, titles: TitleRef[]) {
  const byNorm = new Map(titles.map((t) => [normTitle(t.title), t]))
  const withLinks = text.replace(/\[\[([^[\]|#]+)(?:[#|]([^[\]]*))?\]\]/g, (_, target: string, alias?: string) => {
    const hit = byNorm.get(normTitle(target))
    const label = (alias || target).replace(/[[\]]/g, '')
    return hit ? `[${label}](${href('paper', hit.id)})` : `<span class="wikilink-missing" title="앱에 없는 논문">${label}</span>`
  })
  return DOMPurify.sanitize(marked.parse(withLinks, { async: false }) as string)
}

type Props = {
  initial: string
  onSave: (content: string) => Promise<unknown>
  placeholder?: string
  private?: boolean
}

export function MarkdownEditor({ initial, onSave, placeholder, private: isPrivate }: Props) {
  const [text, setText] = useState(initial)
  const [mode, setMode] = useState<'edit' | 'preview'>(initial ? 'preview' : 'edit')
  const [state, setState] = useState<'saved' | 'dirty' | 'saving' | 'error'>('saved')
  const [err, setErr] = useState('')
  const [titles, setTitles] = useState<TitleRef[]>([])
  const [query, setQuery] = useState<string | null>(null)
  const [sel, setSel] = useState(0)
  const ta = useRef<HTMLTextAreaElement>(null)
  const pending = useRef<string | null>(null)
  const save = useRef(onSave)
  save.current = onSave

  useEffect(() => { loadTitles().then(setTitles) }, [])

  async function flush() {
    if (pending.current === null) return
    const content = pending.current
    pending.current = null
    setState('saving')
    try {
      await save.current(content)
      setState(pending.current === null ? 'saved' : 'dirty')
      setErr('')
    } catch (e) {
      pending.current = pending.current ?? content
      setState('error')
      setErr((e as Error).message)
    }
  }
  useEffect(() => {
    if (state !== 'dirty') return
    const t = setTimeout(flush, 800)
    return () => clearTimeout(t)
  }, [text, state])
  useEffect(() => () => { void flush() }, []) // never lose the last keystrokes when navigating away

  const matches = useMemo(() => {
    if (query === null) return []
    const q = query.toLowerCase()
    return titles.filter((t) => t.title.toLowerCase().includes(q)).slice(0, 8)
  }, [query, titles])

  function onChange(v: string) {
    setText(v)
    pending.current = v
    setState('dirty')
    detect(v)
  }
  function detect(v = text) {
    const pos = ta.current?.selectionStart ?? v.length
    const m = /\[\[([^[\]\n]*)$/.exec(v.slice(0, pos))
    setQuery(m ? m[1] : null)
    setSel(0)
  }
  function insert(t: TitleRef) {
    const el = ta.current!
    const pos = el.selectionStart
    const before = text.slice(0, pos).replace(/\[\[([^[\]\n]*)$/, `[[${t.link}]]`)
    const after = text.slice(pos).replace(/^[^[\]\n]*\]\]/, '')
    onChange(before + after)
    setQuery(null)
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(before.length, before.length) })
  }
  function onKeyDown(e: React.KeyboardEvent) {
    if (!matches.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((sel + 1) % matches.length) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((sel - 1 + matches.length) % matches.length) }
    else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insert(matches[sel]) }
    else if (e.key === 'Escape') setQuery(null)
  }

  const label = { saved: '저장됨', dirty: '수정 중…', saving: '저장 중…', error: `저장 실패: ${err}` }[state]
  return (
    <div className="md-editor">
      <div className="md-toolbar">
        <div className="row toggle" role="group" aria-label="편집 모드">
          <button aria-pressed={mode === 'edit'} onClick={() => setMode('edit')}>편집</button>
          <button aria-pressed={mode === 'preview'} onClick={() => { void flush(); setMode('preview') }}>미리보기</button>
        </div>
        <span className={state === 'error' ? 'error' : 'muted'}>{label}</span>
        {isPrivate && <span className="tag" title="개인 메모는 LLM에 전송되지 않습니다">비공개 · LLM 전송 안 함</span>}
      </div>
      {mode === 'edit' ? (
        <div className="md-input">
          <textarea ref={ta} value={text} onChange={(e) => onChange(e.target.value)} onKeyDown={onKeyDown}
            onClick={() => detect()} onKeyUp={(e) => { if (!['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(e.key)) detect() }}
            onBlur={() => { setTimeout(() => setQuery(null), 150); void flush() }}
            placeholder={placeholder ?? '마크다운으로 작성하세요. [[ 를 입력하면 논문 제목을 찾아 링크합니다.'} aria-label="마크다운 메모" />
          {matches.length > 0 && (
            <ul className="suggest" role="listbox" aria-label="논문 제목 자동완성">
              {matches.map((t, i) => (
                <li key={t.id} role="option" aria-selected={i === sel} className={i === sel ? 'on' : ''}
                  onMouseDown={(e) => { e.preventDefault(); insert(t) }}>
                  {t.title} <span className="muted">{t.year ?? ''}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="md-preview" onDoubleClick={() => setMode('edit')}
          dangerouslySetInnerHTML={{ __html: text.trim() ? renderMarkdown(text, titles) : '<p class="muted">메모가 없습니다. 편집을 눌러 작성하세요.</p>' }} />
      )}
    </div>
  )
}
