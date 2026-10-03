import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { AtlasEditor } from '@shizuha/atlas'
import { createAtlasDocument } from '@shizuha/atlas/core'
import { atlasApi, backToLibrary, loadOrganizations } from '../api'

export default function EditorPage() {
  const { mapId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const library = backToLibrary(location.state?.library)
  const [ready, setReady] = useState(false)
  const [document, setDocument] = useState(null)
  const [saved, setSaved] = useState(null)
  const [title, setTitle] = useState('Untitled map')
  const [organizationId, setOrganizationId] = useState('')
  const [organizations, setOrganizations] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    const load = async () => {
      const [session, named] = await Promise.all([
        atlasApi('/session'),
        loadOrganizations(),
      ])
      const memberships = Object.keys(session.memberships || {})
      const known = new Map(named.map(org => [String(org.id), org.name]))
      const choices = memberships.map(id => ({ id, name: known.get(id) || `Workspace ${id}` }))
      if (!live) return
      setOrganizations(choices)
      if (!mapId) {
        const created = createAtlasDocument()
        const initial = created.model?.title || 'Untitled map'
        const titled = { ...created, model: { ...created.model, title: initial } }
        setDocument(titled)
        setSaved(titled)
        setTitle(initial)
        setOrganizationId(choices[0]?.id || '')
        setReady(true)
        return
      }
      const map = await atlasApi(`/maps/${mapId}`)
      if (!live) return
      if (map.kind === 'system') {
        setError('The system map ships with Atlas. Create your own map to edit a design.')
        setReady(true)
        return
      }
      const opened = map.document?.model ? map.document : { model: map.model, format: 'shizuha-atlas', version: 1 }
      setDocument(opened)
      setSaved(opened)
      setTitle(map.title || opened.model?.title || 'Untitled map')
      setOrganizationId(String(map.organization_id))
      setReady(true)
    }
    load().catch(failure => {
      if (live) setError(failure.message)
    })
    return () => { live = false }
  }, [mapId])

  const changeDocument = next => {
    setDocument(next)
    if (next?.model?.title) setTitle(next.model.title)
  }

  const retitle = value => {
    setTitle(value)
    setDocument(current => (
      current?.model ? { ...current, model: { ...current.model, title: value } } : current
    ))
  }

  const save = async next => {
    const source = next && next.model ? next : document
    if (!source?.model) return
    if (!mapId && !organizationId) {
      setError('Choose a workspace.')
      return
    }
    const nextTitle = (source.model.title || title || 'Untitled map').trim() || 'Untitled map'
    const titled = { ...source, model: { ...source.model, title: nextTitle } }
    setSaving(true)
    setError('')
    try {
      const payload = mapId
        ? await atlasApi(`/maps/${mapId}`, { method: 'PUT', body: JSON.stringify({ title: nextTitle, document: titled }) })
        : await atlasApi('/maps', { method: 'POST', body: JSON.stringify({ title: nextTitle, document: titled, organization_id: Number(organizationId) }) })
      const stored = payload.document?.model ? payload.document : titled
      setSaved(stored)
      setDocument(stored)
      setTitle(payload.title || nextTitle)
      if (!mapId) navigate(`/editor/${payload.id}`, { replace: true, state: location.state })
    } catch (failure) {
      setError(failure.message)
      throw failure
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="shell">
      <header className="bar">
        <a className="button library-back" href={library}>Maps</a>
        <div className="brand"><p className="kicker">Design</p><strong>{title || 'Untitled map'}</strong></div>
        <div className="actions">
          {!mapId && (
            <select aria-label="Workspace" value={organizationId} onChange={event => setOrganizationId(event.target.value)}>
              {organizations.map(org => <option key={org.id} value={org.id}>{org.name}</option>)}
            </select>
          )}
          <input aria-label="Map title" value={title} onChange={event => retitle(event.target.value)} />
          <button className="button primary" type="button" onClick={() => save(document)} disabled={saving || !document}>{saving ? 'Saving…' : 'Save'}</button>
        </div>
      </header>
      {error && <p className="notice home">{error}</p>}
      {!ready && !error && <p className="home empty">Opening the editor…</p>}
      {document?.model && (
        <div className="atlas-editor">
          <AtlasEditor document={document} savedDocument={saved} onChange={changeDocument} onSave={save} saving={saving} saveError={error} />
        </div>
      )}
    </main>
  )
}
