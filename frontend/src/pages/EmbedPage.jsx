import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { AtlasExplorer } from '@shizuha/atlas'
import { indexAtlas, parseAtlasDocument } from '@shizuha/atlas/core'
import { atlasApi } from '../api'

export default function EmbedPage() {
  const { mapId } = useParams()
  const [model, setModel] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    if (mapId) {
      atlasApi(`/maps/${mapId}`).then(payload => {
        if (payload.model) indexAtlas(payload.model)
        if (live) setModel(payload.model)
      }).catch(failure => {
        if (live) setError(failure.message)
      })
      return () => { live = false }
    }
    const onMessage = event => {
      if (event.origin !== window.location.origin) return
      if (event.data?.type !== 'shizuha-atlas-document') return
      try {
        const source = typeof event.data.source === 'string' ? event.data.source : JSON.stringify(event.data.source)
        const parsed = parseAtlasDocument(source)
        indexAtlas(parsed.model)
        setModel(parsed.model)
        setError('')
      } catch (failure) {
        setError(failure.message)
      }
    }
    window.addEventListener('message', onMessage)
    window.parent?.postMessage({ type: 'shizuha-atlas-embed-ready' }, window.location.origin)
    return () => window.removeEventListener('message', onMessage)
  }, [mapId])

  if (error) return <p className="notice home">{error}</p>
  if (!model) return <p className="home empty">Waiting for the Atlas document…</p>
  return <div className="embed-frame"><AtlasExplorer model={model} backHref="/" backLabel="Overview" /></div>
}
