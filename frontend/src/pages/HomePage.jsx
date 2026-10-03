import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { atlasApi, loadOrganizations, rememberLibrary, signIn } from '../api'

const PAGE = 24

function kindLabel(kind) {
  if (kind === 'system') return 'Architecture'
  if (kind === 'design') return 'Design'
  if (!kind) return 'Map'
  return kind.replace(/[-_]/g, ' ')
}

function kindOrder(kinds) {
  const rank = kind => (kind === 'system' ? 0 : kind === 'design' ? 1 : 2)
  return [...kinds].sort((left, right) => rank(left) - rank(right) || left.localeCompare(right))
}

function when(iso) {
  const time = Date.parse(iso || '')
  if (Number.isNaN(time)) return ''
  const minutes = Math.round((Date.now() - time) / 60000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 36) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 14) return `${days}d ago`
  return new Date(time).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

function countLabel(shown, total) {
  const noun = total === 1 ? 'map' : 'maps'
  if (shown < total) return `${shown.toLocaleString()} of ${total.toLocaleString()} ${noun}`
  return `${total.toLocaleString()} ${noun}`
}

function pagePath({ q, organizationId, kind, offset }) {
  const params = new URLSearchParams()
  if (q) params.set('q', q)
  if (organizationId) params.set('organization_id', organizationId)
  if (kind) params.set('kind', kind)
  params.set('limit', String(PAGE))
  params.set('offset', String(offset))
  return `/maps?${params.toString()}`
}

export default function HomePage() {
  const [params, setParams] = useSearchParams()
  const qParam = params.get('q') || ''
  const org = params.get('org') || ''
  const kind = params.get('kind') || ''
  const [q, setQ] = useState(qParam)
  const [debounced, setDebounced] = useState(qParam)
  const [maps, setMaps] = useState(null)
  const [total, setTotal] = useState(0)
  const [kinds, setKinds] = useState([])
  const [names, setNames] = useState({})
  const [organizations, setOrganizations] = useState([])
  const [error, setError] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const generation = useRef(0)
  const writtenQuery = useRef(qParam)

  useEffect(() => {
    const incoming = params.get('q') || ''
    if (incoming === writtenQuery.current) return
    writtenQuery.current = incoming
    setQ(incoming)
    setDebounced(incoming)
  }, [params])

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(q.trim()), 180)
    return () => clearTimeout(handle)
  }, [q])

  useEffect(() => {
    const current = new URLSearchParams(window.location.search)
    if ((current.get('q') || '') === debounced) return
    writtenQuery.current = debounced
    if (debounced) current.set('q', debounced)
    else current.delete('q')
    setParams(current, { replace: true })
  }, [debounced, setParams])

  useEffect(() => {
    rememberLibrary(window.location.search || '')
  }, [params])

  useEffect(() => {
    let live = true
    Promise.all([
      loadOrganizations(),
      atlasApi('/session').catch(() => null),
    ]).then(([orgs, session]) => {
      if (!live) return
      const named = Object.fromEntries(orgs.map(item => [String(item.id), item.name]))
      setNames(named)
      const memberships = Object.keys(session?.memberships || {})
      setOrganizations(memberships
        .map(id => ({ id, name: named[id] || `Workspace ${id}` }))
        .sort((left, right) => left.name.localeCompare(right.name)))
    })
    return () => { live = false }
  }, [])

  useEffect(() => {
    const ticket = ++generation.current
    let live = true
    setError('')
    atlasApi(pagePath({ q: debounced, organizationId: org, kind, offset: 0 })).then(payload => {
      if (!live || generation.current !== ticket) return
      setMaps(payload.maps || [])
      setTotal(payload.total || 0)
      setKinds(payload.kinds || [])
    }).catch(failure => {
      if (!live || generation.current !== ticket) return
      setError(failure.message)
      setMaps(current => current || [])
    })
    return () => { live = false }
  }, [debounced, org, kind])

  const filtering = Boolean(debounced || org || kind)
  const shown = maps?.length || 0
  const chips = kindOrder(kinds.includes(kind) || !kind ? kinds : [...kinds, kind])

  function setFilter(key, value) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  function showMore() {
    if (!maps || loadingMore || maps.length >= total) return
    const ticket = generation.current
    setLoadingMore(true)
    atlasApi(pagePath({ q: debounced, organizationId: org, kind, offset: maps.length })).then(payload => {
      if (generation.current !== ticket) return
      setMaps(current => [...(current || []), ...(payload.maps || [])])
      setTotal(payload.total || 0)
    }).catch(failure => {
      if (generation.current === ticket) setError(failure.message)
    }).finally(() => {
      if (generation.current === ticket) setLoadingMore(false)
    })
  }

  return (
    <main className="shell">
      <header className="bar library-bar">
        <div className="brand">
          <p className="kicker">Shizuha</p>
          <strong>Atlas</strong>
        </div>
        <label className="search">
          <span className="sr" >Search</span>
          <input
            value={q}
            placeholder="Search maps"
            aria-label="Search maps"
            autoComplete="off"
            onChange={event => setQ(event.target.value)}
          />
          {q && <button type="button" aria-label="Clear search" onClick={() => setQ('')}>Clear</button>}
        </label>
        <div className="actions">
          <a className="button" href="/apps/shizuha/">Apps</a>
          <Link className="button primary" to="/editor" state={{ library: window.location.search }}>New map</Link>
        </div>
      </header>
      <section className="library">
        <div className="filters">
          <p className="count" aria-live="polite">{error ? 'Maps unavailable' : maps ? countLabel(shown, total) : 'Opening maps'}</p>
          <label className="workspace">
            <span className="sr">Workspace</span>
            <select aria-label="Workspace" value={org} onChange={event => setFilter('org', event.target.value)}>
              <option value="">All workspaces</option>
              {organizations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <div className="chips" role="group" aria-label="Map type">
            <button type="button" className="chip" aria-pressed={kind === ''} onClick={() => setFilter('kind', '')}>All</button>
            {chips.map(item => (
              <button key={item} type="button" className="chip" aria-pressed={kind === item} onClick={() => setFilter('kind', item === kind ? '' : item)}>
                {kindLabel(item)}
              </button>
            ))}
          </div>
        </div>
        {maps === null && !error && (
          <div className="grid" aria-hidden="true">
            {Array.from({ length: 6 }, (_, index) => <div className="skeleton-card" key={index} />)}
          </div>
        )}
        {error && (
          <div className="empty-state">
            <h1>{error.includes('Sign in') ? 'Sign in to see your maps' : 'Atlas is unavailable'}</h1>
            <p>{error}</p>
            {error.includes('Sign in') && <button className="button primary" type="button" onClick={signIn}>Sign in</button>}
          </div>
        )}
        {maps && maps.length === 0 && !error && (
          <div className="empty-state">
            <h1>{filtering ? 'No maps match' : 'No maps yet'}</h1>
            <p>{filtering ? 'Try another workspace, type, or search.' : 'Create a map in a workspace you belong to. The architecture map is one map in this library.'}</p>
            {filtering
              ? <button className="button" type="button" onClick={() => { setQ(''); setParams({}, { replace: true }) }}>Clear filters</button>
              : <Link className="button primary" to="/editor">New map</Link>}
          </div>
        )}
        {maps && maps.length > 0 && (
          <div className="grid">
            {maps.map(map => (
              <Link
                className={`card kind-${map.kind || 'map'}`}
                key={map.id}
                to={`/maps/${map.id}`}
                state={{ library: window.location.search }}
              >
                <span className="kind">{kindLabel(map.kind)}</span>
                <strong>{map.title}</strong>
                {map.summary && <span className="summary">{map.summary}</span>}
                <span className="meta">
                  {names[String(map.organization_id)] || `Workspace ${map.organization_id}`}
                  {when(map.updated_at) ? ` · ${when(map.updated_at)}` : ''}
                </span>
              </Link>
            ))}
          </div>
        )}
        {maps && maps.length < total && (
          <div className="more">
            <button className="button" type="button" onClick={showMore} disabled={loadingMore}>
              {loadingMore ? 'Loading…' : `Show more · ${countLabel(shown, total)}`}
            </button>
          </div>
        )}
      </section>
    </main>
  )
}
